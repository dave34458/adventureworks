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

-- Q3. Lowest-performing products by merchandise sales
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Production_Product pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
GROUP BY pr.Name
ORDER BY rev ASC
OFFSET 0 ROWS FETCH NEXT 6 ROWS ONLY;

-- Q4. Purchase-order spend by vendor
SELECT v.Name, SUM(po.SubTotal) AS spend, COUNT(*) AS orders, v.ActiveFlag
FROM Purchasing_PurchaseOrderHeader po
JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3
GROUP BY v.Name, v.ActiveFlag
ORDER BY spend DESC
OFFSET 0 ROWS FETCH NEXT 8 ROWS ONLY;
