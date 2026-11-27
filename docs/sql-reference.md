# SQL Reference — Reports and Dashboard

42 raw SQL executions across the five report/dashboard service files. `%s` parameters and `{...}` placeholders are kept exactly as they appear in source, so these are templates rather than directly runnable SSMS statements. For executable validation queries with the window dates substituted, see `docs/queries.sql`.

| Module | Executes |
|---|---:|
| Dashboard | 6 |
| Sales | 4 |
| Customer profile | 12 |
| Revenue and loss | 9 |
| Cost | 11 |
| **Total** | **42** |

## Dashboard

### D1
Category filter options — `reporting/services/dashboard.py:38`

```sql
SELECT ProductCategoryID, Name FROM [Production].[ProductCategory] ORDER BY Name
```

### D2
KPI totals: revenue, cost, orders, customers, below-cost, current vs previous — `reporting/services/dashboard.py:117`

```sql
WITH lines AS (
    SELECT d.LineTotal AS rev,
           d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cost,
           h.SalesOrderID AS order_id,
           h.CustomerID AS customer_id,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
           CASE WHEN d.LineTotal
                     < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
                THEN 1 ELSE 0 END AS below
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    LEFT JOIN [Production].[ProductCostHistory] ch
      ON ch.ProductID = d.ProductID
     AND h.OrderDate >= ch.StartDate
     AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
    LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
    LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
)
SELECT
  COALESCE(SUM(CASE WHEN side = 'cur' THEN rev END), 0) AS rev,
  COALESCE(SUM(CASE WHEN side = 'prev' THEN rev END), 0) AS rev_prev,
  COALESCE(SUM(CASE WHEN side = 'cur' THEN cost END), 0) AS cogs,
  COALESCE(SUM(CASE WHEN side = 'prev' THEN cost END), 0) AS cogs_prev,
  COUNT(DISTINCT CASE WHEN side = 'cur' THEN order_id END) AS orders,
  COUNT(DISTINCT CASE WHEN side = 'prev' THEN order_id END) AS orders_prev,
  COUNT(DISTINCT CASE WHEN side = 'cur' THEN customer_id END) AS customers,
  COUNT(DISTINCT CASE WHEN side = 'prev' THEN customer_id END) AS customers_prev,
  COALESCE(SUM(CASE WHEN side = 'cur' THEN below ELSE 0 END), 0) AS below_n,
  COALESCE(SUM(CASE WHEN side = 'cur' AND below = 1 THEN cost - rev ELSE 0 END), 0) AS below_short
FROM lines
```

### D3
Monthly trend: revenue, cost, orders by month, current vs previous — `reporting/services/dashboard.py:206`

```sql
SELECT month, side, SUM(rev) AS rev, SUM(cogs) AS cogs,
       COUNT(DISTINCT order_id) AS orders
FROM (
    SELECT {month_expr("h.OrderDate")} AS month,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
           d.LineTotal AS rev,
           d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cogs,
           h.SalesOrderID AS order_id
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    LEFT JOIN [Production].[ProductCostHistory] ch
      ON ch.ProductID = d.ProductID
     AND h.OrderDate >= ch.StartDate
     AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
    LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
    LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
) base
GROUP BY month, side
ORDER BY month
```

### D4
Product rankings by units, revenue, cost and margin — `reporting/services/dashboard.py:337`

```sql
SELECT p.ProductID, p.Name, pc.Name,
       SUM(d.OrderQty) AS units,
       SUM(d.LineTotal) AS rev,
       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
GROUP BY p.ProductID, p.Name, pc.Name
ORDER BY SUM(d.LineTotal) DESC
{limit_clause(100)}
```

### D5
Category mix: revenue and cost per category when no category is selected — `reporting/services/dashboard.py:384`

```sql
SELECT pc.ProductCategoryID, pc.Name,
       SUM(d.LineTotal) AS rev,
       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
GROUP BY pc.ProductCategoryID, pc.Name
ORDER BY SUM(d.LineTotal) DESC
```

### D6
Customer mix: individuals vs stores — `reporting/services/dashboard.py:430`

```sql
SELECT CASE WHEN cu.StoreID IS NULL THEN 0 ELSE 1 END AS is_store,
       SUM(d.LineTotal) AS rev,
       COUNT(DISTINCT h.SalesOrderID) AS orders,
       COUNT(DISTINCT h.CustomerID) AS customers
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Sales].[Customer] cu ON cu.CustomerID = h.CustomerID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
GROUP BY CASE WHEN cu.StoreID IS NULL THEN 0 ELSE 1 END
```

## Sales

### S1
KPI totals: revenue, orders, customers, current vs previous — `reporting/services/sales.py:32`

```sql
WITH lines AS (
    SELECT h.OrderDate, h.SalesOrderID, h.CustomerID,
           d.LineTotal AS rev
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    WHERE 1 = 1{line_filter}
)
SELECT
  COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN rev END), 0) AS rev,
  COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate < %s THEN rev END), 0) AS rev_prev,
  COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN SalesOrderID END) AS orders,
  COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate < %s THEN SalesOrderID END) AS orders_prev,
  COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN CustomerID END) AS customers,
  COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate < %s THEN CustomerID END) AS customers_prev
FROM lines
WHERE OrderDate >= %s
```

### S2
Monthly sales trend, current vs previous — `reporting/services/sales.py:78`

```sql
SELECT month, side, SUM(rev) AS rev, COUNT(DISTINCT order_id) AS orders
FROM (
    SELECT {month_expr("h.OrderDate")} AS month,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
           d.LineTotal AS rev,
           h.SalesOrderID AS order_id
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
) base
GROUP BY month, side
ORDER BY month
```

### S3
High-performing products by revenue — `reporting/services/sales.py:134`

```sql
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY pr.Name
ORDER BY rev DESC
{limit_clause(100)}
```

### S4
Low-performing products by revenue — `reporting/services/sales.py:151`

```sql
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY pr.Name
ORDER BY rev ASC
{limit_clause(100)}
```

## Customer profile

### CP1
KPI figures: revenue, active customers, new revenue — `reporting/services/customer_profile.py:40`

```sql
SELECT
  COALESCE(SUM(CASE WHEN l.OrderDate >= %s AND l.OrderDate <= %s
                    THEN l.rev END), 0) AS rev,
  COALESCE(SUM(CASE WHEN l.OrderDate >= %s AND l.OrderDate < %s
                    THEN l.rev END), 0) AS rev_prev,
  COUNT(DISTINCT CASE WHEN l.OrderDate >= %s AND l.OrderDate <= %s
                      THEN l.CustomerID END) AS actives,
  COUNT(DISTINCT CASE WHEN l.OrderDate >= %s AND l.OrderDate < %s
                      THEN l.CustomerID END) AS actives_prev,
  COALESCE(SUM(CASE WHEN l.OrderDate >= %s AND l.OrderDate <= %s
                     AND f.first_date >= %s AND f.first_date <= %s
                    THEN l.rev END), 0) AS new_rev
FROM (
    SELECT h.CustomerID, h.OrderDate,
           d.LineTotal AS rev
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    WHERE 1 = 1{line_filter}
) l
JOIN (
    SELECT CustomerID, MIN(OrderDate) AS first_date
    FROM [Sales].[SalesOrderHeader] h
    WHERE 1 = 1{header_filter}
    GROUP BY CustomerID
) f ON f.CustomerID = l.CustomerID
WHERE l.OrderDate >= %s
```

### CP2
New customers first seen in the window vs previous window — `reporting/services/customer_profile.py:79`

```sql
SELECT
  COALESCE(SUM(CASE WHEN first_date >= %s AND first_date <= %s THEN 1 ELSE 0 END), 0),
  COALESCE(SUM(CASE WHEN first_date >= %s AND first_date < %s THEN 1 ELSE 0 END), 0)
FROM (
    SELECT CustomerID, MIN(h.OrderDate) AS first_date
    FROM [Sales].[SalesOrderHeader] h
    WHERE 1 = 1{header_filter}
    GROUP BY CustomerID
) first_seen
```

### CP3
Retention: active buyers who also bought in the compare window — `reporting/services/customer_profile.py:95`

```sql
SELECT COUNT(DISTINCT h.CustomerID)
FROM [Sales].[SalesOrderHeader] h
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
  AND h.CustomerID IN (
      SELECT h2.CustomerID FROM [Sales].[SalesOrderHeader] h2
      WHERE h2.OrderDate >= %s AND h2.OrderDate < %s
        {inner_filter}
  )
  {outer_filter}
```

### CP4
Active buyers per month — `reporting/services/customer_profile.py:119`

```sql
SELECT {month_expr("h.OrderDate")} AS month,
       COUNT(DISTINCT CustomerID) AS act
FROM [Sales].[SalesOrderHeader] h
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{header_filter}
GROUP BY {month_expr("h.OrderDate")}
ORDER BY month
```

### CP5
New buyers per month — `reporting/services/customer_profile.py:133`

```sql
SELECT {month_expr("first_date")} AS month, COUNT(*)
FROM (
    SELECT CustomerID, MIN(h.OrderDate) AS first_date
    FROM [Sales].[SalesOrderHeader] h
    WHERE 1 = 1{header_filter}
    GROUP BY CustomerID
) first_seen
WHERE first_date >= %s AND first_date <= %s
GROUP BY {month_expr("first_date")}
```

### CP6
Channels: individuals vs stores revenue, orders and customers — `reporting/services/customer_profile.py:172`

```sql
SELECT
  COALESCE(SUM(CASE WHEN cu.StoreID IS NULL
                    THEN d.LineTotal END), 0) AS ind_rev,
  COALESCE(SUM(CASE WHEN cu.StoreID IS NOT NULL
                    THEN d.LineTotal END), 0) AS st_rev,
  COUNT(DISTINCT CASE WHEN cu.StoreID IS NULL THEN h.SalesOrderID END) AS ind_orders,
  COUNT(DISTINCT CASE WHEN cu.StoreID IS NOT NULL THEN h.SalesOrderID END) AS st_orders,
  COUNT(DISTINCT CASE WHEN cu.StoreID IS NULL THEN h.CustomerID END) AS ind_customers,
  COUNT(DISTINCT CASE WHEN cu.StoreID IS NOT NULL THEN h.CustomerID END) AS st_customers
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Sales].[Customer] cu ON cu.CustomerID = h.CustomerID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
```

### CP7
Revenue and orders by ship-to country — `reporting/services/customer_profile.py:207`

```sql
SELECT co.Name, SUM(d.LineTotal) AS rev,
       COUNT(DISTINCT h.SalesOrderID) AS orders
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Person].[Address] a ON a.AddressID = h.ShipToAddressID
JOIN [Person].[StateProvince] sp ON sp.StateProvinceID = a.StateProvinceID
JOIN [Person].[CountryRegion] co ON co.CountryRegionCode = sp.CountryRegionCode
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY co.Name
ORDER BY rev DESC
{limit_clause(100)}
```

### CP8
Revenue by shipping city — `reporting/services/customer_profile.py:248`

```sql
SELECT a.City, sp.StateProvinceCode, sp.CountryRegionCode,
       SUM(d.LineTotal) AS rev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Person].[Address] a ON a.AddressID = h.ShipToAddressID
JOIN [Person].[StateProvince] sp ON sp.StateProvinceID = a.StateProvinceID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY a.City, sp.StateProvinceCode, sp.CountryRegionCode
ORDER BY rev DESC
{limit_clause(100)}
```

### CP9
Store demographics for business-type totals — `reporting/services/customer_profile.py:270`

```sql
SELECT Demographics FROM [Sales].[Store] WHERE Demographics IS NOT NULL
```

### CP10
Stores with sales by business type and square feet — `reporting/services/customer_profile.py:276`

```sql
SELECT s.BusinessEntityID, MAX(CONVERT(nvarchar(max), s.Demographics)), SUM(d.LineTotal) AS rev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Sales].[Customer] cu ON cu.CustomerID = h.CustomerID
JOIN [Sales].[Store] s ON s.BusinessEntityID = cu.StoreID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY s.BusinessEntityID
```

### CP11
Purchase frequency buckets — `reporting/services/customer_profile.py:319`

```sql
SELECT CASE WHEN n = 1 THEN '1 order'
            WHEN n = 2 THEN '2 orders'
            WHEN n <= 4 THEN '3–4 orders'
            WHEN n <= 9 THEN '5–9 orders'
            ELSE '10+ orders' END AS bucket,
       COUNT(*)
FROM (
    SELECT CustomerID, COUNT(*) AS n
    FROM [Sales].[SalesOrderHeader] h
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{header_filter}
    GROUP BY CustomerID
) q
GROUP BY CASE WHEN n = 1 THEN '1 order'
              WHEN n = 2 THEN '2 orders'
              WHEN n <= 4 THEN '3–4 orders'
              WHEN n <= 9 THEN '5–9 orders'
              ELSE '10+ orders' END
```

### CP12
Top customers by revenue — `reporting/services/customer_profile.py:348`

```sql
SELECT h.CustomerID, s.Name, p.FirstName, p.LastName, t.Name,
       CASE WHEN cu.StoreID IS NOT NULL THEN 1 ELSE 0 END AS is_store,
       COUNT(DISTINCT h.SalesOrderID) AS orders,
       SUM(d.LineTotal) AS rev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Sales].[Customer] cu ON cu.CustomerID = h.CustomerID
LEFT JOIN [Sales].[Store] s ON s.BusinessEntityID = cu.StoreID
LEFT JOIN [Person].[Person] p ON p.BusinessEntityID = cu.PersonID
LEFT JOIN [Sales].[SalesTerritory] t ON t.TerritoryID = cu.TerritoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY h.CustomerID, s.Name, p.FirstName, p.LastName, t.Name, cu.StoreID
ORDER BY rev DESC
{limit_clause(100)}
```

## Revenue and loss

### RL1
Monthly gross profit and cost of goods trend — `reporting/services/revenue_and_loss.py:39`

```sql
SELECT month, side, SUM(rev) AS rev, SUM(cogs) AS cogs
FROM (
    SELECT {month_expr("h.OrderDate")} AS month,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
           d.LineTotal AS rev,
           d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cogs
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    LEFT JOIN [Production].[ProductCostHistory] ch
      ON ch.ProductID = d.ProductID
     AND h.OrderDate >= ch.StartDate
     AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
) base
GROUP BY month, side
ORDER BY month
```

### RL2
KPI totals: revenue, cost of goods, current vs previous — `reporting/services/revenue_and_loss.py:122`

```sql
WITH lines AS (
    SELECT d.LineTotal AS rev,
           d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cost,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    LEFT JOIN [Production].[ProductCostHistory] ch
      ON ch.ProductID = d.ProductID
     AND h.OrderDate >= ch.StartDate
     AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
)
SELECT
  COALESCE(SUM(CASE WHEN side = 'cur' THEN rev END), 0) AS rev,
  COALESCE(SUM(CASE WHEN side = 'prev' THEN rev END), 0) AS rev_prev,
  COALESCE(SUM(CASE WHEN side = 'cur' THEN cost END), 0) AS cogs,
  COALESCE(SUM(CASE WHEN side = 'prev' THEN cost END), 0) AS cogs_prev
FROM lines
```

### RL3
Invoiced totals: tax, freight and total due — `reporting/services/revenue_and_loss.py:153`

```sql
SELECT
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                    THEN h.TaxAmt END), 0) AS tax,
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                    THEN h.Freight END), 0) AS freight,
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                    THEN h.TotalDue END), 0) AS due,
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                    THEN h.TotalDue END), 0) AS due_prev
FROM [Sales].[SalesOrderHeader] h
WHERE h.OrderDate >= %s{order_filter}
```

### RL4
Below-cost shortfall: count, revenue and cost — `reporting/services/revenue_and_loss.py:172`

```sql
SELECT COUNT(*),
       COALESCE(SUM(d.LineTotal), 0),
       COALESCE(SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)), 0)
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
  AND d.LineTotal
      < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
```

### RL5
Revenue trend by month, current vs previous — `reporting/services/revenue_and_loss.py:224`

```sql
SELECT month, side, SUM(rev) AS rev
FROM (
    SELECT {month_expr("h.OrderDate")} AS month,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
           d.LineTotal AS rev
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
) base
GROUP BY month, side
ORDER BY month
```

### RL6
Category mix: revenue and cost of goods by category — `reporting/services/revenue_and_loss.py:279`

```sql
SELECT cat.Name, SUM(d.LineTotal) AS rev,
       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
JOIN [Production].[ProductCategory] cat ON cat.ProductCategoryID = sc.ProductCategoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY cat.Name
ORDER BY rev DESC
```

### RL7
Declining products vs previous window — `reporting/services/revenue_and_loss.py:314`

```sql
SELECT Name, cur_rev, prev_rev
FROM (
    SELECT p.Name, p.ProductID,
           SUM(CASE WHEN h.OrderDate >= %s
                    THEN d.LineTotal ELSE 0 END) AS cur_rev,
           SUM(CASE WHEN h.OrderDate < %s
                    THEN d.LineTotal ELSE 0 END) AS prev_rev
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
    GROUP BY p.ProductID, p.Name
) product_rev
WHERE prev_rev > 0 AND cur_rev < prev_rev
ORDER BY (prev_rev - cur_rev) DESC
{limit_clause(100)}
```

### RL8
Below-cost products and shortfall — `reporting/services/revenue_and_loss.py:344`

```sql
SELECT p.Name,
       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost))
       - SUM(d.LineTotal) AS gap,
       COUNT(*) AS n
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
  AND d.LineTotal
      < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
GROUP BY p.Name
ORDER BY gap DESC
{limit_clause(100)}
```

### RL9
Product profitability: revenue, cost, profit and margin — `reporting/services/revenue_and_loss.py:372`

```sql
SELECT p.ProductID, p.Name,
       SUM(d.LineTotal) AS rev,
       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY p.ProductID, p.Name
ORDER BY rev DESC
{limit_clause(100)}
```

## Cost

### C1
Cost KPIs: cost of goods and revenue, current vs previous — `reporting/services/cost.py:62`

```sql
SELECT
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                    THEN d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) END), 0) AS cogs,
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                    THEN d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) END), 0) AS cogs_prev,
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                    THEN d.LineTotal END), 0) AS rev,
  COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                    THEN d.LineTotal END), 0) AS rev_prev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
WHERE h.OrderDate >= %s{line_filter}
```

### C2
Procurement spend and purchase-order count — `reporting/services/cost.py:87`

```sql
SELECT
  COALESCE(SUM(CASE WHEN po.OrderDate >= %s AND po.OrderDate <= %s
                    THEN {purchase_total} END), 0) AS spend,
  COALESCE(SUM(CASE WHEN po.OrderDate >= %s AND po.OrderDate < %s
                    THEN {purchase_total} END), 0) AS spend_prev,
  {purchase_orders} AS orders
FROM [Purchasing].[PurchaseOrderHeader] po
{purchase_detail_join}
WHERE po.OrderDate >= %s AND po.Status <> 3{purchase_filter}
```

### C3
Receipts: received and rejected quantities — `reporting/services/cost.py:104`

```sql
SELECT COALESCE(SUM(d.ReceivedQty), 0), COALESCE(SUM(d.RejectedQty), 0)
FROM [Purchasing].[PurchaseOrderDetail] d
JOIN [Purchasing].[PurchaseOrderHeader] h ON h.PurchaseOrderID = d.PurchaseOrderID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
```

### C4
Manufacturing: units started and scrapped — `reporting/services/cost.py:115`

```sql
SELECT
  COALESCE(SUM(CASE WHEN StartDate >= %s THEN OrderQty ELSE 0 END), 0) AS qty,
  COALESCE(SUM(CASE WHEN StartDate >= %s THEN ScrappedQty ELSE 0 END), 0) AS scr,
  COALESCE(SUM(CASE WHEN StartDate < %s THEN OrderQty ELSE 0 END), 0) AS qty_prev,
  COALESCE(SUM(CASE WHEN StartDate < %s THEN ScrappedQty ELSE 0 END), 0) AS scr_prev,
  COUNT(*) AS orders
FROM [Production].[WorkOrder] w
WHERE w.StartDate >= %s AND w.StartDate <= %s{work_filter}
```

### C5
Monthly cost-of-goods trend, current vs previous — `reporting/services/cost.py:167`

```sql
SELECT month, side, SUM(cogs) AS cogs, SUM(rev) AS rev
FROM (
    SELECT {month_expr("h.OrderDate")} AS month,
           CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
           d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cogs,
           d.LineTotal AS rev
    FROM [Sales].[SalesOrderDetail] d
    JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
    JOIN [Production].[Product] p ON p.ProductID = d.ProductID
    LEFT JOIN [Production].[ProductCostHistory] ch
      ON ch.ProductID = d.ProductID
     AND h.OrderDate >= ch.StartDate
     AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
    WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
) base
GROUP BY month, side
ORDER BY month
```

### C6
Category mix: cost of goods and revenue by category — `reporting/services/cost.py:228`

```sql
SELECT cat.Name, SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
       SUM(d.LineTotal) AS rev
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
JOIN [Production].[ProductCategory] cat ON cat.ProductCategoryID = sc.ProductCategoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY cat.Name
ORDER BY cogs DESC
```

### C7
Top vendors by procurement spend — `reporting/services/cost.py:263`

```sql
SELECT v.Name, SUM({purchase_total}) AS spend,
       {purchase_vendor_orders} AS orders, v.ActiveFlag
FROM [Purchasing].[PurchaseOrderHeader] po
{purchase_detail_join}
JOIN [Purchasing].[Vendor] v ON v.BusinessEntityID = po.VendorID
WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3{purchase_filter}
GROUP BY v.Name, v.ActiveFlag
ORDER BY spend DESC
{limit_clause(100)}
```

### C8
Products with the highest cost of goods — `reporting/services/cost.py:287`

```sql
SELECT p.Name, SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
       SUM(d.OrderQty) AS units
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = d.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
GROUP BY p.Name
ORDER BY cogs DESC
{limit_clause(100)}
```

### C9
Scrap reasons by cost, units and work orders — `reporting/services/cost.py:312`

```sql
SELECT sr.Name,
       SUM(w.ScrappedQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost,
       SUM(w.ScrappedQty) AS scr,
       COUNT(*) AS orders
FROM [Production].[WorkOrder] w
JOIN [Production].[ScrapReason] sr ON sr.ScrapReasonID = w.ScrapReasonID
JOIN [Production].[Product] p ON p.ProductID = w.ProductID
LEFT JOIN [Production].[ProductCostHistory] ch
  ON ch.ProductID = w.ProductID
 AND w.StartDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR w.StartDate <= ch.EndDate)
WHERE w.StartDate >= %s AND w.StartDate <= %s{work_filter}
GROUP BY sr.Name
ORDER BY cost DESC
{limit_clause(100)}
```

### C10
Standard cost changes and repricing — `reporting/services/cost.py:339`

```sql
WITH product_costs AS (
    SELECT h.ProductID, p.Name, h.StartDate, h.StandardCost,
           ROW_NUMBER() OVER (PARTITION BY h.ProductID ORDER BY h.StartDate) AS product_rank
    FROM [Production].[ProductCostHistory] h
    JOIN [Production].[Product] p ON p.ProductID = h.ProductID
    WHERE h.EndDate IS NOT NULL{history_filter}
), increases AS (
    SELECT first_cost.Name, first_cost.StartDate, first_cost.StandardCost AS old_cost,
           current_cost.StandardCost AS new_cost,
           ROW_NUMBER() OVER (
               PARTITION BY LTRIM(RTRIM(LEFT(first_cost.Name,
                   CHARINDEX(',', first_cost.Name + ',') - 1)))
               ORDER BY first_cost.StartDate
           ) AS name_rank
    FROM product_costs first_cost
    JOIN [Production].[ProductCostHistory] current_cost
      ON current_cost.ProductID = first_cost.ProductID
     AND current_cost.EndDate IS NULL
    WHERE first_cost.product_rank = 1
      AND current_cost.StandardCost > first_cost.StandardCost
)
SELECT Name, old_cost, new_cost
FROM increases
WHERE name_rank = 1
ORDER BY (new_cost - old_cost) / NULLIF(old_cost, 0) DESC
{limit_clause(100)}
```

### C11
Largest purchase orders — `reporting/services/cost.py:386`

```sql
SELECT po.PurchaseOrderID, v.Name, po.OrderDate, {biggest_po_total}, po.Status,
       {biggest_po_lines} AS lines
FROM [Purchasing].[PurchaseOrderHeader] po
{purchase_detail_join}
JOIN [Purchasing].[Vendor] v ON v.BusinessEntityID = po.VendorID
WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3{purchase_filter}
{biggest_po_group}
ORDER BY {biggest_po_order} DESC
{limit_clause(100)}
```
