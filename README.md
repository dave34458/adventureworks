# AdventureWorks (2025 build): Django + SQL Server reporting application

Source data: Microsoft's `AdventureWorks-oltp-install-script.zip`
https://github.com/Microsoft/sql-server-samples/releases/tag/adventureworks

## 1. Completed work summary

As of this report, the project has finished the following:

- `AdventureWorks2025` is restored on SQL Server 2025 locally and on Cloud SQL SQL Server 2025 Express.
- We profiled the data: 31,465 sales orders, 121,317 order lines, 19,820 customers, 504 products,
  4,012 purchase orders and 72,591 work orders. Order dates run from 2022-05-30 to 2025-06-29;
  2022 and 2025 are partial years.
- We built 19 read-only `dbo` views over the source tables. The app reads those views and never
  edits the AdventureWorks source data.
- We built the Django 6.0.5 application: a dashboard, four report tabs (Sales, Customer Profile,
  Revenue and Loss, Cost), saved report snapshots, table browsers, user/role management, an audit
  trail and a versioned data privacy notice.
- We implemented 12 department roles plus the global Administrator, and seeded 13 demo accounts
  (one Administrator and one login per role).
- The test suite passes 69/69 on SQL Server. `manage.py check`, `makemigrations --check` and
  `migrate --check` are clean.
- The app is deployed on Cloud Run with a Cloud SQL Auth Proxy sidecar:
  https://adventureworks-4cfcg3oqqq-uc.a.run.app. Cloud SQL is restored from the current app
  database backup. The proxy uses Cloud SQL's public IP and IAM; no VPC is needed.
- Every panel is backed by a read-only SQL query in `core/services/`. Section 4 shows four
  representative queries; the rest live in the service modules.

## 2. Project purpose and business questions

AdventureWorks is a bicycle manufacturer and retailer that sells online and through resellers in
North America, Europe and the Pacific. Its data sits in about 80 operational tables, so managers
have no single place to see how the business is doing. The application gives each user only the
reports and actions their role allows.

The system has four kinds of users:

- C-level executives and department managers, who need company-wide performance.
- Supervisors, who need operational detail for their department.
- Employees, who need read-only access to the reports for their area.
- A system administrator, who manages users and permissions.

We built the panels first, then worked backward to the question each panel answers. The questions below use the panel's own measure, unit, and filter.

### Dashboard

| Panel | Business question |
|---|---|
| KPI cards (role-dependent) | Which role-visible cards — total sales or revenue, orders, gross profit, cost of goods, active customers, and below-cost shortfall — changed versus the previous period? |
| Category filter | How do the dashboard figures change when narrowed to one product category? |
| Sales trend by month / Revenue trend by month / Cost of goods sold by month (role-dependent) | How does the role-appropriate monthly measure — merchandise sales, revenue, or cost of goods sold — compare with the previous period? |
| Revenue contribution by category / Cost distribution by category (role-dependent) | Which product categories account for the largest share of merchandise revenue (sales) or cost of goods sold? |
| Gross margin by month | How does gross margin percent compare with the previous period? |
| Customer mix and spending | What are the merchandise revenue share, buyer share, customer count, and average order value of individuals versus stores? |
| Top products by sales / revenue / cost of goods | Which products rank highest by the role-appropriate measure — sales, revenue, or cost of goods — and what are their units and, where shown, gross profit and margin? |

### Sales Report

| Panel | Business question |
|---|---|
| KPI cards | What are total merchandise sales, order count, average order value, and distinct buyers in the period? |
| Total sales and sales trend | How do monthly merchandise sales compare with the previous period, and how many orders did each month have? |
| High-performing products | Which products have the highest merchandise sales (sum of line totals, excluding tax and freight)? |
| Low-performing products | Which products have the lowest merchandise sales among products sold in the period? |

### Customer Profile Report

| Panel | Business question |
|---|---|
| KPI cards | How many distinct buyers were active, how many were new, what share of merchandise revenue came from returning buyers, what was average merchandise revenue per active customer, and what share of the previous period's buyers returned? |
| Purchasing patterns and trends | How many distinct buyers purchased each month, and how many were new versus returning? |
| Who buys: segmentation and spending | What are the merchandise revenue share, buyer share, customer count, and average order value of individuals versus stores? |
| Customer distribution (revenue by ship-to country) | Which ship-to countries generate the most merchandise revenue, and how is that revenue distributed on the map? |
| Customer distribution by city (revenue by ship-to city) | Which ship-to cities generate the most merchandise revenue? |
| Customer segmentation by business type | Which store business types account for merchandise revenue, how many stores in each type had sales, and what was their average square footage? |
| Purchase frequency | How many distinct buyers placed 1, 2, 3-4, 5-9, or 10+ orders in the period? |
| Top customers by segment | Which six stores and three individuals generated the most merchandise revenue, and what were their territories, order counts, and revenue? (Ranked separately.) |

### Revenue and Loss Report

| Panel | Business question |
|---|---|
| KPI cards | What are total merchandise revenue, cost of goods at standard cost on the sale date, gross profit, invoiced total including tax and freight, and below-cost shortfall (standard cost minus line total on below-cost lines)? |
| Revenue trend by month | How does monthly merchandise revenue compare with the previous period? |
| Gross profit, selected period | What gross profit (merchandise revenue minus cost of goods) did each month produce? |
| Gross margin by month | How does gross margin percent compare with the previous period? |
| Revenue contribution by category | Which product categories account for the largest share of merchandise revenue, and what gross margin does each carry? |
| Declining revenue by product | Which products had the largest dollar decline in merchandise revenue versus the previous period? |
| Below-cost shortfall | Which products were sold below standard cost, and what was the shortfall (standard cost minus line total)? |
| Revenue contribution by product | Which products generated the most merchandise revenue, and what were their cost, gross profit, and margin? |
| Calculation method and limitations | What definitions and data limits apply to revenue, cost, gross profit, margin, below-cost, and invoiced total? |

### Cost Report

| Panel | Business question |
|---|---|
| KPI cards | What are cost of goods sold, cost per $1 of merchandise revenue, non-rejected procurement spend, unit scrap rate, and unit rejected-receipt rate? |
| Available cost information (Buy, Make, Waste, Sell) | What is the four-step cost flow: procurement spend (USD), units started, units scrapped, and cost of goods sold (USD)? |
| Cost trends and comparisons | How does monthly cost of goods sold compare with the previous period, and what gross margin did each month leave? |
| Cost distribution by category | Which product categories account for the largest share of cost of goods sold, and what gross margin does each carry? |
| Costs and business performance | What percentage of each merchandise revenue dollar is absorbed by cost of goods, and what gross margin remains? |
| Significant cost contributors: vendors | Which vendors account for the most merchandise purchase-order spend (PO subtotal, excluding tax/freight and rejected POs), and how many POs did each have? |
| Significant cost contributors: products | Which products account for the most cost of goods sold (quantity sold × standard cost on the sale date), and how many units did each contribute? |
| Significant cost contributors: scrap | Which scrap reasons have the highest estimated scrap cost (scrapped units × standard cost effective on the work-order date), and how many scrapped units and work orders did each reason account for? |
| Significant cost contributors: repricing | Which products had the largest percentage standard-cost increase, and what were the earliest recorded and current open costs (one row per base product name)? |
| Biggest purchase orders | Which non-rejected purchase orders had the largest merchandise subtotal in the period, and what were their order dates, line counts, and statuses? |

## 3. Initial data map

The app uses 19 read-only views. Each view is named `<Schema>_<Table>` and reads exactly one
AdventureWorks source table; the mapping is one-to-one, and every view has the same row count as its
source table. No view filters or aggregates rows. A few convert XML/spatial columns to text, and
`Production_ProductCostHistory` adds a computed `id` with `ROW_NUMBER()`. The primary keys come from
the source tables. The main joins are the joins the app uses; they are not a full list of every
source foreign key.

| App view | Source table | Primary key | Main joins | Important fields | Used by | Rows |
|---|---|---|---|---|---|---:|
| `Person_Address` | `Person.Address` | `AddressID` | `StateProvinceID` -> `Person.StateProvince` | `City`, `StateProvinceID` | Customer Profile | 19,614 |
| `Person_BusinessEntity` | `Person.BusinessEntity` | `BusinessEntityID` | none | `BusinessEntityID` | Customer Profile table browser | 20,777 |
| `Person_CountryRegion` | `Person.CountryRegion` | `CountryRegionCode` | none | `Name` | Customer Profile | 238 |
| `Sales_Customer` | `Sales.Customer` | `CustomerID` | `PersonID` -> `Person.Person`; `StoreID` -> `Sales.Store`; `TerritoryID` -> `Sales.SalesTerritory` | `PersonID`, `StoreID` | Customer Profile | 19,820 |
| `Person_Person` | `Person.Person` | `BusinessEntityID` | none | `FirstName`, `LastName`, `Demographics` | Customer Profile | 19,972 |
| `Production_Product` | `Production.Product` | `ProductID` | `ProductSubcategoryID` -> `Production.ProductSubcategory` | `Name`, `StandardCost`, `ListPrice`, `SellStartDate` | Sales, Revenue and Loss, Cost, Dashboard | 504 |
| `Production_ProductCategory` | `Production.ProductCategory` | `ProductCategoryID` | none | `Name` | Revenue and Loss, Cost, Dashboard | 4 |
| `Production_ProductCostHistory` | `Production.ProductCostHistory` | `id` (computed `ROW_NUMBER`; natural key `ProductID` + `StartDate`) | `ProductID` -> `Production.Product` | `StandardCost`, `StartDate`, `EndDate` | Revenue and Loss, Cost, Dashboard | 395 |
| `Production_ProductSubcategory` | `Production.ProductSubcategory` | `ProductSubcategoryID` | `ProductCategoryID` -> `Production.ProductCategory` | `Name` | Revenue and Loss, Cost, Dashboard | 37 |
| `Purchasing_PurchaseOrderDetail` | `Purchasing.PurchaseOrderDetail` | `PurchaseOrderID` + `PurchaseOrderDetailID` | `PurchaseOrderID` -> `Purchasing.PurchaseOrderHeader`; `ProductID` -> `Production.Product` | `OrderQty`, `UnitPrice`, `ReceivedQty`, `RejectedQty` | Cost | 8,845 |
| `Purchasing_PurchaseOrderHeader` | `Purchasing.PurchaseOrderHeader` | `PurchaseOrderID` | `VendorID` -> `Purchasing.Vendor` | `OrderDate`, `SubTotal`, `Freight`, `Status` | Cost | 4,012 |
| `Sales_SalesOrderDetail` | `Sales.SalesOrderDetail` | `SalesOrderID` + `SalesOrderDetailID` | `SalesOrderID` -> `Sales.SalesOrderHeader`; `ProductID` -> `Production.Product` | `OrderQty`, `UnitPrice`, `UnitPriceDiscount`, `LineTotal` | Sales, Revenue and Loss, Customer Profile, Dashboard | 121,317 |
| `Sales_SalesOrderHeader` | `Sales.SalesOrderHeader` | `SalesOrderID` | `CustomerID` -> `Sales.Customer`; `TerritoryID` -> `Sales.SalesTerritory`; `ShipToAddressID` -> `Person.Address` | `OrderDate`, `OnlineOrderFlag`, `SubTotal`, `TaxAmt`, `Freight`, `TotalDue` | Sales, Revenue and Loss, Customer Profile, Cost, Dashboard | 31,465 |
| `Sales_SalesTerritory` | `Sales.SalesTerritory` | `TerritoryID` | `CountryRegionCode` -> `Person.CountryRegion` | `Name`, `Group`, `SalesYTD` | Sales table browser, Customer Profile | 10 |
| `Production_ScrapReason` | `Production.ScrapReason` | `ScrapReasonID` | none | `Name` | Cost | 16 |
| `Person_StateProvince` | `Person.StateProvince` | `StateProvinceID` | `CountryRegionCode` -> `Person.CountryRegion` | `Name`, `StateProvinceCode` | Customer Profile | 181 |
| `Sales_Store` | `Sales.Store` | `BusinessEntityID` | none | `Name`, `Demographics` (`BusinessType`, `SquareFeet`) | Customer Profile | 701 |
| `Purchasing_Vendor` | `Purchasing.Vendor` | `BusinessEntityID` | none | `Name`, `CreditRating`, `PreferredVendorStatus`, `ActiveFlag` | Cost | 104 |
| `Production_WorkOrder` | `Production.WorkOrder` | `WorkOrderID` | `ProductID` -> `Production.Product`; `ScrapReasonID` -> `Production.ScrapReason` | `OrderQty`, `ScrappedQty`, `StartDate` | Cost | 72,591 |

The app also owns `core_report` (saved report snapshots), `core_auditlog` (edit/delete audit trail),
`auth_user` and the standard Django `auth_*`, `django_session`, `django_migrations`,
`django_admin_log` and `django_content_type` tables. `TabAccess` is `managed = False`; it exists only
to create the four tab permissions.

The app does not expose `Person.Password`, `Sales.CreditCard` or
`HumanResources.EmployeePayHistory`. It also does not use `SalesPerson` or `SpecialOffer`; revenue
comes from `LineTotal`, which already includes the discount.

### Data quality issues and limitations

| Finding | Impact and how we handle it |
|---|---|
| Sales data covers 2022-05-30 to 2025-06-29 only; 2022 and 2025 are partial years. | The default report is a rolling 12-month window ending in the last order month; custom ranges are labeled, so partial years are not silently compared. |
| 64 of 121,317 order lines (0.05%) have no matching cost-history period. | The app falls back to the product's current `StandardCost` (`COALESCE`). |
| 209 products have no subcategory. | Category donuts use inner joins and exclude them; product-level panels include them. The dashboard category filter lists only categorized products. |
| 71,862 of 72,591 work orders have no `ScrapReasonID`. | The scrap-reason panel uses the 729 work orders that have a reason; the scrap rate uses all scrapped quantities. Scrap cost is estimated from the standard cost effective on each work order's start date, falling back to the current standard cost when no cost-history row covers that date. |
| Operating expenses and returns are not in the data. | "Loss" here means sales below standard cost plus scrap cost, not a full profit and loss statement. |
| `TotalPurchaseYTD` is negative for 8,215 people. | Customer spend is calculated from actual orders, not that field. |
| Education and occupation fields are not used by the app's panels. | The Customer Profile report focuses on purchasing behavior, geography, store type and frequency. |

## 4. SQL evidence

These four queries are copied from the app's panel code, one per report. `%s` is the report window
the app binds; the results below use the full sample (`2022-05-30` to `2025-06-29`). The app's
default is the last 12 months. All amounts are in US dollars.

### Q1. Which products generate the most merchandise sales?

**Report:** Sales -> High-performing products (`core/services/sales.py:125`).

```sql
SELECT pr.Name, SUM(d.LineTotal) AS rev
FROM Sales_SalesOrderDetail d
JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
JOIN Production_Product pr ON pr.ProductID = d.ProductID
WHERE h.OrderDate >= %s AND h.OrderDate <= %s
GROUP BY pr.Name
ORDER BY rev DESC
OFFSET 0 ROWS FETCH NEXT 8 ROWS ONLY;
```

| Product | Merchandise sales |
|---|---:|
| Mountain-200 Black, 38 | 4,400,592.80 |
| Mountain-200 Black, 42 | 4,009,494.76 |
| Mountain-200 Silver, 38 | 3,693,678.03 |
| Mountain-200 Silver, 42 | 3,438,478.86 |
| Mountain-200 Silver, 46 | 3,434,256.94 |
| Mountain-200 Black, 46 | 3,309,673.22 |
| Road-250 Black, 44 | 2,516,857.31 |
| Road-250 Black, 48 | 2,347,655.95 |

`LineTotal` is quantity times unit price after discount. The panel returns the top eight products.

### Q2. Which ship-to countries generate the most merchandise revenue?

**Report:** Customer Profile -> Customer distribution (`core/services/customer_profile.py:187`).

This is the query behind the map and the "Revenue by country" list. It groups by the ship-to country,
not the customer's sales territory. The map hover shows revenue and orders; the list shows revenue only.
Neither shows customer counts.

```sql
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
```

| Country | Merchandise revenue | Orders (map hover) |
|---|---:|---:|
| United States | 62,997,590.71 | 12,041 |
| Canada | 16,355,770.45 | 4,067 |
| Australia | 10,655,335.96 | 6,843 |
| United Kingdom | 7,670,721.04 | 3,219 |
| France | 7,251,555.65 | 2,672 |
| Germany | 4,915,407.60 | 2,623 |

The map shows the same six countries as bubbles. The United States is the largest market by revenue.

### Q3. Which categories contribute the most merchandise revenue and gross margin?

**Report:** Revenue and Loss -> Revenue contribution by category
(`core/services/revenue_and_loss.py:298`).

```sql
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
```

| Category | Merchandise revenue | COGS | Gross profit | Margin |
|---|---:|---:|---:|---:|
| Bikes | 94,651,172.70 | 84,131,887.76 | 10,519,284.95 | 11.1% |
| Components | 11,802,593.29 | 10,768,475.71 | 1,034,117.57 | 8.8% |
| Clothing | 2,120,542.52 | 1,750,636.29 | 369,906.23 | 17.4% |
| Accessories | 1,272,072.88 | 637,601.04 | 634,471.85 | 49.9% |

Gross profit is revenue minus COGS; margin is gross profit divided by revenue. COGS uses the standard
cost in effect on the order date, falling back to the product's current standard cost when no
cost-history row covers that date. Bikes bring in most of the revenue at a modest margin; accessories
have the highest margin.

### Q4. Which vendors account for the most merchandise purchase-order spend?

**Report:** Cost -> Significant cost contributors: vendors (`core/services/cost.py:243`).

```sql
SELECT v.Name, SUM(po.SubTotal) AS spend, COUNT(*) AS orders, v.ActiveFlag
FROM Purchasing_PurchaseOrderHeader po
JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3
GROUP BY v.Name, v.ActiveFlag
ORDER BY spend DESC
OFFSET 0 ROWS FETCH NEXT 8 ROWS ONLY;
```

| Vendor | Merchandise PO spend | Orders | Active |
|---|---:|---:|---|
| Superior Bicycles | 3,826,953.90 | 42 | Yes |
| Chicago City Saddles | 2,718,119.25 | 44 | Yes |
| Professional Athletic Consultants | 2,672,843.25 | 44 | Yes |
| Jackson Authority | 2,190,209.18 | 44 | Yes |
| Vision Cycles, Inc. | 2,100,558.08 | 42 | Yes |
| Sport Fan Co. | 2,049,062.40 | 42 | Yes |
| Proseware, Inc. | 1,928,607.45 | 42 | No |
| Crowley Sport | 1,886,773.35 | 43 | Yes |

`Status <> 3` excludes rejected purchase orders; pending, approved, and complete POs are included.
`ActiveFlag` is 1 for active vendors and 0 for inactive ones. The panel returns the top eight vendors.

Other panel queries cover below-cost products, declining products, estimated scrap cost by reason,
standard-cost changes and the largest purchase orders; they live in `core/services/`.

## 5. Architecture

### Implemented architecture

```text
Browser
  |
  v
Cloud Run service: adventureworks
  +-- app container: Django 6.0.5 + gunicorn + WhiteNoise
  |     listens on 0.0.0.0:8080
  |     reads MSSQL_* and DJANGO_* environment variables
  |     reads secrets from Secret Manager
  |
  +-- cloud-sql-proxy sidecar
        listens on 127.0.0.1:1433
        connects to Cloud SQL over its public IP with IAM
        no VPC and no authorized-network rule required
              |
              v
        Cloud SQL SQL Server 2025 Express
        database: AdventureWorks2025
        restored from the current app backup
```

- The image is built with Cloud Build and stored in Artifact Registry.
- Cloud Run uses a dedicated service account with `roles/cloudsql.client` and access to the two
  secrets (`adventureworks-django-secret-key`, `adventureworks-mssql-password`).
- The app reads the 19 `dbo` views. It writes only to `core_report`, `core_auditlog`, the `auth_*`
  tables and Django's session/admin tables.
- The app has no VPC connector. The proxy sidecar handles the Cloud SQL connection.

## 6. Roles and RBAC matrix

- **Administrator** = a superuser (`admin@example.com`). It can open every tab and every table, and
  manage users, groups, the privacy notice and audit records. There is no Administrator group.
- **Department roles** are 12 Django groups: Manager, Supervisor and Employee for each of four
  departments. Each department gets exactly one tab:
  - Sales -> Sales
  - Marketing -> Customer Profile
  - Finance -> Revenue and Loss
  - Production -> Cost

| Capability | Administrator | Manager | Supervisor | Employee |
|---|---|---|---|---|
| Open a department tab (`access_<tab>`) | All four tabs | Own tab | Own tab | Own tab |
| View department source tables (`view_<table>`) | All 19 | Own department | Own department | No |
| View saved reports | All modules | Own module | Own module | Own module |
| Generate/regenerate a saved report (`change_report`) | Yes | Yes | No | No |
| Edit/delete a saved report (`change_report`, `delete_report`) | Yes | Yes | No | No |
| Edit/delete source-table rows (`change_<table>`, `delete_<table>`) | Yes | No | No | No |
| Open `/manage/` (users, groups, privacy, audit) | Yes | No | No | No |

| Department | Tab | Source tables for Manager/Supervisor |
|---|---|---|
| Sales | Sales | `SalesOrderHeader`, `SalesOrderDetail`, `SalesTerritory` |
| Marketing | Customer Profile | `SalesCustomer`, `Person`, `PersonBusinessEntity`, `PersonAddress`, `SalesStore`, `PersonStateProvince`, `PersonCountryRegion` |
| Finance | Revenue and Loss | `ProductionProduct`, `ProductionProductSubcategory`, `ProductionProductCategory` |
| Production | Cost | `PurchasingPurchaseOrderHeader`, `PurchasingPurchaseOrderDetail`, `PurchasingVendor`, `ProductionWorkOrder`, `ProductionProductCostHistory`, `ProductionScrapReason` |

No role can create source records through the UI. Report pages and saved-report lists are gated by
`access_<tab>`; table pages need `view_<table>`.

Apply the groups with:

```bash
python manage.py shell -c "from core.roles import ROLES, apply_roles; apply_roles(ROLES, prune=True)"
```

Demo logins use the email local part as the password: `sales.manager@example.com` /
`sales.manager`, `sales.supervisor@example.com` / `sales.supervisor`, and so on. Run
`python manage.py seed_users --reset --prune` to create or reset them. Change the demo passwords
before real use.


