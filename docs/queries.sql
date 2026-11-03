-- Q1. Top products by merchandise sales
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Production_Product pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
GROUP BY pr.Name
ORDER BY rev DESC
OFFSET 0 ROWS FETCH NEXT 8 ROWS ONLY;

-- Q2. Revenue by ship-to country
SELECT co.Name, SUM(d.LineTotal) AS rev,
       COUNT(DISTINCT h.SalesOrderID) AS orders
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Person_Address a ON a.AddressID = h.ShipToAddressID
JOIN Person_StateProvince sp ON sp.StateProvinceID = a.StateProvinceID
JOIN Person_CountryRegion co ON co.CountryRegionCode = sp.CountryRegionCode
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
GROUP BY co.Name
ORDER BY rev DESC
OFFSET 0 ROWS FETCH NEXT 6 ROWS ONLY;

-- Q3. Revenue contribution and gross margin by category
SELECT cat.Name, SUM(d.LineTotal) AS rev,
       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Production_Product p ON p.ProductID = d.ProductID
LEFT JOIN Production_ProductCostHistory ch
  ON ch.ProductID = d.ProductID
 AND h.OrderDate >= ch.StartDate
 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
JOIN Production_ProductCategory cat ON cat.ProductCategoryID = sc.ProductCategoryID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
GROUP BY cat.Name
ORDER BY rev DESC;

-- Q4. Purchase-order spend by vendor
SELECT v.Name, SUM(po.SubTotal) AS spend, COUNT(*) AS orders, v.ActiveFlag
FROM Purchasing_PurchaseOrderHeader po
JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3
GROUP BY v.Name, v.ActiveFlag
ORDER BY spend DESC
OFFSET 0 ROWS FETCH NEXT 8 ROWS ONLY;
