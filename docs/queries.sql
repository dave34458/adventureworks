-- Q1. Top products by merchandise sales
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Production_Product pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
-- When selected, the live report adds these predicates to its WHERE clause:
-- AND EXISTS (SELECT 1 FROM Production_ProductSubcategory sc
--             WHERE sc.ProductSubcategoryID = pr.ProductSubcategoryID
--               AND sc.ProductCategoryID = %s)
-- AND EXISTS (SELECT 1 FROM Person_Address a
--             JOIN Person_StateProvince sp ON sp.StateProvinceID = a.StateProvinceID
--             WHERE a.AddressID = h.ShipToAddressID AND sp.CountryRegionCode = %s)
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
-- When selected, the live report adds category and ship-to-country EXISTS
-- predicates to this WHERE clause, using the same line and header relationships.
GROUP BY co.Name
ORDER BY rev DESC
OFFSET 0 ROWS FETCH NEXT 6 ROWS ONLY;

-- Q3. Purchase-order spend by vendor
SELECT v.Name, SUM(po.SubTotal) AS spend, COUNT(*) AS orders, v.ActiveFlag
FROM Purchasing_PurchaseOrderHeader po
JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3
-- Cost report category filtering joins Purchasing_PurchaseOrderDetail and sums
-- only selected-category line totals; it does not apply a country predicate.
GROUP BY v.Name, v.ActiveFlag
ORDER BY spend DESC
OFFSET 0 ROWS FETCH NEXT 8 ROWS ONLY;

-- Q4. Lowest-performing products by merchandise sales
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Production_Product pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
-- The live report appends the selected product-category and ship-to-country
-- predicates here before ranking, so the limit applies to the filtered rows.
GROUP BY pr.Name
ORDER BY rev ASC
OFFSET 0 ROWS FETCH NEXT 6 ROWS ONLY;
