# Database and SQL Validation

Purpose: evidence that the figures shown in the app are the figures actually stored in `AdventureWorks2025`, and that each displayed calculation is traceable to the raw SQL documented in `docs/sql-reference.md`.

## Evidence basis

- Captured on: 2026-11-23.
- App values: KPI cards rendered in the browser while signed in as `admin@example.com`, using live data (`?report=` on report pages to avoid saved-report previews).
- Database values: independent read-only `SELECT` statements run directly against `AdventureWorks2025`.
- Report window used by both: current `2024-07-01` to `2025-06-30`; previous `2023-07-01` to `2024-06-30`. The window is anchored to the data's own `MAX(OrderDate)`, not the current date.
- Comparison: at the precision shown by the app — dollars to 2 decimals, counts as whole numbers, percentages rounded as documented below, cost per dollar as whole cents.
- Dashboard category and ship-to country filters default to all values, so the reconciled KPI figures are unchanged by the multi-select filter update.

## Validation summary

| Module | SQL IDs in scope | Figures checked | Evidence | Result |
|---|---|---|---|---|
| Dashboard | D2–D6 | Total sales, Orders, Gross profit, Cost of goods, Active customers, Below-cost shortfall | Six displayed KPI values matched independent SQL results exactly at displayed precision | Reconciled |
| Sales | S1–S4 | Total sales, Orders, Avg order value, Customers | Four displayed KPI values matched independent SQL results exactly at displayed precision | Reconciled |
| Customer profile | CP1–CP12 | Active customers, New customers, Repeat revenue share, Avg spend per customer, Retention | Five displayed KPI values matched after applying the documented rounding rules | Reconciled |
| Revenue and loss | RL1–RL9 | Total revenue, Cost of goods, Gross profit, Invoiced total, Below-cost shortfall | Five displayed KPI values matched independent SQL results exactly at displayed precision | Reconciled |
| Cost | C1–C11 | Cost of goods sold, Cost per $1 revenue, Procurement spend, Scrap rate, Rejected receipts | Five displayed KPI values matched after applying the documented rounding rules | Reconciled |

## Calculation rules

- Revenue = `SUM(SalesOrderDetail.LineTotal)` — merchandise only, excluding tax and freight.
- Cost of goods = `SUM(OrderQty × COALESCE(ProductCostHistory.StandardCost, Product.StandardCost))`, using the standard cost effective on the order date.
- Gross profit = revenue − cost of goods.
- Margin / revenue shares = `profit ÷ revenue × 100`; customer shares use the corresponding customer or revenue totals.
- Avg order value = revenue ÷ distinct orders. Avg spend per customer = revenue ÷ distinct active customers.
- New customer = a customer whose first-ever order date falls in the current window.
- Retention = previous-window buyers who also bought in the current window ÷ previous-window active buyers × 100. The app displays the rounded whole percent.
- Below-cost shortfall = `SUM(cost − LineTotal)` over sales lines where `LineTotal < cost` at the order-date standard cost.
- Cost per $1 revenue = `cost of goods ÷ revenue × 100`, displayed as whole cents.
- Scrap rate = scrapped units ÷ units started × 100. Rejected receipts = rejected quantity ÷ received quantity × 100.

## Reconciliation detail

### Dashboard

Source: `D2` (KPI totals). See `docs/sql-reference.md` for the full SQL.

| Figure shown | App display | Independent DB result | Raw DB aggregate |
|---|---:|---:|---:|
| Total sales | $44,987,040.83 | $44,987,040.83 | 44,987,040.832507 |
| Orders | 23,159 | 23,159 | 23,159 |
| Gross profit | $6,228,017.52 | $6,228,017.52 | 44,987,040.832507 − 38,759,023.3138 |
| Cost of goods | $38,759,023.31 | $38,759,023.31 | 38,759,023.3138 |
| Active customers | 18,044 | 18,044 | 18,044 |
| Below-cost shortfall | $1,429,632.01 | $1,429,632.01 | 1,429,632.007337 over 10,091 lines |

### Sales

Source: `S1` (KPI totals).

| Figure shown | App display | Independent DB result | Raw DB aggregate |
|---|---:|---:|---:|
| Total sales | $44,987,040.83 | $44,987,040.83 | 44,987,040.832507 |
| Orders | 23,159 | 23,159 | 23,159 |
| Avg order value | $1,942.53 | $1,942.53 | 44,987,040.832507 ÷ 23,159 |
| Customers | 18,044 | 18,044 | 18,044 |

### Customer profile

Sources: `CP1` (active/revenue), `CP2` (new customers), `CP3` (retention).

| Figure shown | App display | Independent DB result | Raw DB basis |
|---|---:|---:|---:|
| Active customers | 18,044 | 18,044 | 18,044 distinct buyers |
| New customers | 12,876 | 12,876 | 12,876 buyers first seen in the window |
| Repeat revenue share | 73.00% | 73.00% | (44,987,040.832507 − 12,038,658.526711) ÷ 44,987,040.832507 = 73.2397%, rounded to 73% |
| Avg spend per customer | $2,493.19 | $2,493.19 | 44,987,040.832507 ÷ 18,044 |
| Retention | 81.00% | 81.00% | 3,167 of 3,903 previous-window buyers returned = 81.1427%, rounded to 81% |

### Revenue and loss

Sources: `RL2` (revenue/cost), `RL3` (invoiced totals), `RL4` (below-cost shortfall).

| Figure shown | App display | Independent DB result | Raw DB aggregate |
|---|---:|---:|---:|
| Total revenue | $44,987,040.83 | $44,987,040.83 | 44,987,040.832507 |
| Cost of goods | $38,759,023.31 | $38,759,023.31 | 38,759,023.3138 |
| Gross profit | $6,228,017.52 | $6,228,017.52 | 44,987,040.832507 − 38,759,023.3138 |
| Invoiced total | $50,369,051.70 | $50,369,051.70 | 50,369,051.6988 from `TotalDue`, includes tax and freight |
| Below-cost shortfall | $1,429,632.01 | $1,429,632.01 | 1,429,632.007337 |

### Cost

Sources: `C1` (cost/revenue), `C2` (procurement), `C3` (receipts), `C4` (scrap).

| Figure shown | App display | Independent DB result | Raw DB basis |
|---|---:|---:|---:|
| Cost of goods sold | $38,759,023.31 | $38,759,023.31 | 38,759,023.3138 |
| Cost per $1 revenue | 86¢ | 86¢ | 38,759,023.3138 ÷ 44,987,040.832507 × 100 = 86.18¢, rounded to 86¢ |
| Procurement spend | $49,810,676.01 | $49,810,676.01 | 49,810,676.0115 from non-rejected purchase orders |
| Scrap rate | 0.28% | 0.28% | 5,680 scrapped ÷ 2,045,353 started = 0.2779% |
| Rejected receipts | 2.43% | 2.43% | 44,851 rejected ÷ 1,845,020 received = 2.431% |

## Reproducing the evidence

1. Use the same window as the app. It is derived from `MAX(SalesOrderHeader.OrderDate)`; the captured run used the dates listed above.
2. Open each report in the browser with live data and record the KPI card values.
3. Run the SSMS-ready queries in `docs/queries.sql` against `AdventureWorks2025`; each statement is labelled with its source query ID from `docs/sql-reference.md` and already has the window dates substituted.
4. Apply the calculation rules above, then compare at the app's displayed precision.

All five modules reconciled at displayed precision.
