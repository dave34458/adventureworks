-- SSMS-ready validation queries for docs/database-sql-validation.md.
-- Window used by the captured evidence:
--   current:  2024-07-01 through 2025-06-30
--   previous: 2023-07-01 through 2024-06-30
-- The app derives this window from MAX(SalesOrderHeader.OrderDate).
-- Query IDs refer to docs/sql-reference.md.

-- D2 / S1 / RL2 / C1 — Revenue, cost, orders, customers and below-cost aggregates.
;WITH lines AS (
  SELECT d.LineTotal AS rev,
         d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cost,
         h.SalesOrderID,
         h.CustomerID,
         CASE WHEN d.LineTotal < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
              THEN 1 ELSE 0 END AS below
  FROM [Sales].[SalesOrderDetail] d
  JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
  JOIN [Production].[Product] p ON p.ProductID = d.ProductID
  LEFT JOIN [Production].[ProductCostHistory] ch
    ON ch.ProductID = d.ProductID
   AND h.OrderDate >= ch.StartDate
   AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
  WHERE h.OrderDate >= '2024-07-01' AND h.OrderDate <= '2025-06-30'
)
SELECT SUM(rev) AS revenue,
       SUM(cost) AS cogs,
       COUNT(DISTINCT SalesOrderID) AS orders,
       COUNT(DISTINCT CustomerID) AS customers,
       SUM(CASE WHEN below = 1 THEN 1 ELSE 0 END) AS below_cost_lines,
       SUM(CASE WHEN below = 1 THEN cost - rev ELSE 0 END) AS below_cost_shortfall
FROM lines;
GO

-- S1 — Average order value.
SELECT SUM(d.LineTotal) / COUNT(DISTINCT h.SalesOrderID) AS avg_order_value
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
WHERE h.OrderDate >= '2024-07-01' AND h.OrderDate <= '2025-06-30';
GO

-- CP1 — Active customers in the current window.
SELECT COUNT(DISTINCT CustomerID) AS active_customers
FROM [Sales].[SalesOrderHeader]
WHERE OrderDate >= '2024-07-01' AND OrderDate <= '2025-06-30';
GO

-- CP1 — Revenue in the current window.
SELECT SUM(d.LineTotal) AS revenue
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
WHERE h.OrderDate >= '2024-07-01' AND h.OrderDate <= '2025-06-30';
GO

-- CP1 — Active customers in the previous window (retention denominator).
SELECT COUNT(DISTINCT CustomerID) AS previous_active_customers
FROM [Sales].[SalesOrderHeader]
WHERE OrderDate >= '2023-07-01' AND OrderDate <= '2024-06-30';
GO

-- CP2 — New customers first seen in the current window.
SELECT COUNT(DISTINCT fs.CustomerID) AS new_customers
FROM (
  SELECT CustomerID, MIN(OrderDate) AS first_date
  FROM [Sales].[SalesOrderHeader]
  GROUP BY CustomerID
) fs
WHERE fs.first_date >= '2024-07-01' AND fs.first_date <= '2025-06-30';
GO

-- CP2 — Revenue from those new customers (repeat revenue share numerator input).
SELECT SUM(d.LineTotal) AS new_customer_revenue
FROM [Sales].[SalesOrderDetail] d
JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
JOIN (
  SELECT CustomerID, MIN(OrderDate) AS first_date
  FROM [Sales].[SalesOrderHeader]
  GROUP BY CustomerID
) fs ON fs.CustomerID = h.CustomerID
WHERE h.OrderDate >= '2024-07-01' AND h.OrderDate <= '2025-06-30'
  AND fs.first_date >= '2024-07-01' AND fs.first_date <= '2025-06-30';
GO

-- CP3 — Previous-window buyers who also bought in the current window.
SELECT COUNT(DISTINCT cur.CustomerID) AS retained_customers
FROM [Sales].[SalesOrderHeader] cur
WHERE cur.OrderDate >= '2024-07-01' AND cur.OrderDate <= '2025-06-30'
  AND EXISTS (
    SELECT 1
    FROM [Sales].[SalesOrderHeader] prev
    WHERE prev.CustomerID = cur.CustomerID
      AND prev.OrderDate >= '2023-07-01' AND prev.OrderDate <= '2024-06-30'
  );
GO

-- RL3 — Invoiced total from order headers (includes tax and freight).
SELECT SUM(TotalDue) AS invoiced_total
FROM [Sales].[SalesOrderHeader]
WHERE OrderDate >= '2024-07-01' AND OrderDate <= '2025-06-30';
GO

-- C2 — Procurement spend from non-rejected purchase orders.
SELECT SUM(SubTotal) AS procurement_spend
FROM [Purchasing].[PurchaseOrderHeader]
WHERE OrderDate >= '2024-07-01' AND OrderDate <= '2025-06-30'
  AND Status <> 3;
GO

-- C3 — Rejected receipts.
SELECT SUM(d.RejectedQty) AS rejected_qty,
       SUM(d.ReceivedQty) AS received_qty
FROM [Purchasing].[PurchaseOrderDetail] d
JOIN [Purchasing].[PurchaseOrderHeader] po ON po.PurchaseOrderID = d.PurchaseOrderID
WHERE po.OrderDate >= '2024-07-01' AND po.OrderDate <= '2025-06-30';
GO

-- C4 — Scrap rate inputs.
SELECT SUM(ScrappedQty) AS scrapped_qty,
       SUM(OrderQty) AS started_qty
FROM [Production].[WorkOrder]
WHERE StartDate >= '2024-07-01' AND StartDate <= '2025-06-30';
GO
