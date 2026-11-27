# AdventureWorks Reporting System — Test Results

Generated: 2026-11-27 19:06 UTC
Command: `python -m pytest tests -q`
pytest exit status: 0
Summary: Pass: 12 · Fail: 0 · Skipped: 0 · Not run: 0
Status: generated from the last pytest run (2026-11-27 19:06 UTC).

## Scope

Covered in this phase:

- Dashboard and the four report modules: Sales, Customer profile, Revenue and loss, Cost.
- One combined-filter test case per page, exercising every filter control on that page.
- Invalid, malformed, and empty-range filter handling across all five pages.
- Unauthenticated and invalid-login behavior.
- RBAC demonstration for all 16 department roles plus the global Administrator.
- RBAC split by feature: report tabs, source tables, report generation/saved reports, department user/audit administration, global administration.

Not covered in this phase:

- CSV/PDF export.
- Creating, editing, or deleting saved reports.
- Creating, editing, or deactivating users.
- Editing group permissions.
- Account/password changes.
- Privacy-page content.
- Pure unit-level utilities (axis math, formatting, role counts). Report rendering covers the visible outcomes indirectly.

## Environment and prerequisites

- Application URL: temporary localhost server started by the Playwright suite (set `E2E_BASE_URL` to reuse an existing server).
- Django dev server started automatically on a free port; no manual `runserver` is required for the E2E suite.
- Database: `AdventureWorks2025`, reachable through the configured Django connection.
- Demo accounts and role groups seeded: `python manage.py seed_users` (`--reset` if passwords or group assignments have drifted; `seed_users --if-empty` skips role creation when any user already exists)
- Desktop viewport for layout assertions: 1440 x 900 (the two-column layouts collapse below 820 px).
- Date values use `YYYY-MM-DD`. "Default From/To" means the values already present in the page's date inputs on first load.
- "Reset" means opening the module path without a query string. For report modules, the Playwright harness appends `?report=` to force live data; when a saved report exists, the app otherwise auto-opens the first saved report on the bare path.
- Where a default row count is stated, it comes from `reporting/services/common.py::SHOW_DEFAULTS`.

## Test accounts

Passwords are the email local part, for example `sales.manager@example.com` / `sales.manager`.

| Department | Admin | Manager | Supervisor | Employee |
|---|---|---|---|---|
| Sales | sales.admin@example.com | sales.manager@example.com | sales.supervisor@example.com | sales.employee@example.com |
| Marketing | marketing.admin@example.com | marketing.manager@example.com | marketing.supervisor@example.com | marketing.employee@example.com |
| Finance | finance.admin@example.com | finance.manager@example.com | finance.supervisor@example.com | finance.employee@example.com |
| Production | production.admin@example.com | production.manager@example.com | production.supervisor@example.com | production.employee@example.com |
| Global | admin@example.com / `admin` | — | — | — |

The login page also exposes one demo button per account. The buttons carry `aria-label="Log in as <Department> <Kind>"`; the global button is labelled `Global Administrator`.

## Role expectations used below

| Capability | Department Admin | Department Manager | Department Supervisor | Department Employee | Global Administrator |
|---|---|---|---|---|---|
| Own report tab | Yes | Yes | Yes | Yes | All tabs |
| Own module source tables | View | View | View | None | View, edit, delete |
| Generate/edit/delete saved reports | Yes | Yes | No | No | Yes |
| View saved-report list | Yes | Yes | Yes | Yes | Yes |
| Manage department users | Yes, own department only | No | No | No | All users |
| Audit logs | Yes, own department only | No | No | No | All departments |
| Manage group permissions | No | No | No | No | Yes |

---

## Authentication

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-01 | 1. With no cookies, request `/dashboard/`, `/sales/`, `/customer-profile/`, `/revenue-and-loss/`, `/cost/`, `/users/`, `/users/audit/`, and `/users/groups/`.<br>2. Open `/login/`, enter `admin@example.com` with password `wrong`, and submit.<br>3. Reload `/login/`, click the `Global Administrator` demo button.<br>4. While authenticated, request `/login/`.<br>5. Click `Log out`, then request `/dashboard/` again. | 1. Each protected URL ends at `/login/?next=<original path>` and shows the login form; no 500.<br>2. Stays on `/login/`, shows `Wrong email or password.`, and no authenticated navigation appears.<br>3. Ends on `/dashboard/`; top navigation shows Dashboard, Sales, Customer profile, Revenue and loss, Cost, Manage users, Audit Logs, Manage Permissions, `admin@example.com (Administrator)`, and Log out.<br>4. Redirects away from the login form; the final URL is not `/login/`.<br>5. Logout ends on `/login/`; the subsequent `/dashboard/` request redirects back to `/login/?next=/dashboard/`. | Pass |

## Dashboard

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-02 | 1. Log in as the global Administrator and open `/dashboard/`.<br>2. Record the default From and To values. Assert the heading, KPI cards, trend panel, 12 trend bars, money-axis ticks, category donut/list, margin line chart, customer-mix split bars, and top-products table.<br>3. Combined filters: keep From, set To to one month before the default To, select the first non-empty category, and set `select[name="show_products"]` to 3. Each change auto-submits.<br>4. Assert the resulting heading, URL parameters, product row count, and that the trend still renders.<br>5. Click Reset. | 1. HTTP 200, heading `Business performance dashboard`.<br>2. `#dashboard-filters` contains From, To (`name="from"`, `name="to"`), a Category select containing `All categories` plus at least four categories, and a Reset link. At least one `.d-kpi`; the first trend panel contains 12 `.d-bar` elements and 5 non-empty `.d-y-axis span` ticks; a category donut or category list is present; a margin line chart is present; at least two customer-mix `.d-splitbar` elements are present; the top-products `.d-table` has at least one data row.<br>3. No 500; URL includes non-empty `from`, `to`, `category`, and `show_products=3`.<br>4. Heading `Top products in <category>` is visible, an `All categories` link is visible, the category panel shows 6 top products and the all-category table has 1–3 data rows, KPI cards remain, and the trend chart still has at least one bar and money-axis ticks.<br>5. The query is cleared (URL ends `/dashboard/` or `/dashboard/?`); category is `All categories`; From/To equal the original defaults; Show products is 10; the table has 1–10 data rows. | Pass |

## Sales

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-03 | 1. Log in as the global Administrator and open `/sales/`.<br>2. Assert the default page: heading, KPI cards, trend panel, 12 bars, money axis, subtitle, default row counts, and legends.<br>3. Combined filters: keep From, set To to one month before the default To; check only the `Bikes` product category; check only `United States` under Ship-to country; uncheck the `Key figures` and `Low-performing products` panels; set `select[name="show_products"]` to 3; set `select[name="sales_metric"]` to `Order count`.<br>4. Assert the filtered page and URL.<br>5. Set `sales_metric` back to `Sales dollars`.<br>6. Reset the page. | 1. HTTP 200, heading `Sales report`.<br>2. `#report-dimensions` and `#report-chart-filter` exist; the chart select offers `Sales dollars` and `Order count` and defaults to `Sales dollars`. At least one KPI card; heading `Total sales and sales trend`; 12 bars; 5 non-empty money-axis ticks; subtitle `Monthly merchandise sales`; 8 high-performing product rows; 6 low-performing product rows; both Selected period and Previous period legends.<br>3. Each change auto-submits without a 500.<br>4. URL includes non-empty `from`, `to`, `category`, `country`, `show_products=3`, and `sales_metric=orders`; only Bikes and United States are checked; the KPI section is absent; heading `Low-performing products` is absent; the high-performing list has exactly 3 rows; subtitle is `Monthly order count`; no `.d-y-axis` exists.<br>5. Subtitle returns to `Monthly merchandise sales`; 5 money-axis ticks are present; URL has `sales_metric=revenue`.<br>6. `/sales/` shows all category and country checkboxes checked, all panels visible, 8 high-performing rows, and 6 low-performing rows. | Pass |

## Customer profile

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-04 | 1. Log in as the global Administrator and open `/customer-profile/`.<br>2. Assert all eight default panels, the growth chart and count axis, the channel split bars, the map, and the bubble data.<br>3. Combined filters: keep From, set To to one month before the default To; check only `Bikes`; check only `United States`; uncheck the `Key figures`, `Purchase frequency`, and `Business type` panels; set `show_countries=3`, `show_cities=3`, and `show_biggest=3`.<br>4. Assert the filtered page and URL.<br>5. Reset the page. | 1. HTTP 200, heading `Customer profile report`.<br>2. Panels present: Key figures, `Purchasing patterns and trends`, `Who buys: segmentation and spending`, `Customer distribution`, `Customer distribution by city`, `Customer segmentation by business type`, `Purchase frequency`, `Top customers`. The growth panel has `.d-chart.has-count-axis`, 5 non-empty count-axis ticks, 12 bars, and Returning/New legends. `#cust-map` exists, `#cust-bubbles` contains a non-empty JSON array, and the channel split bars are present.<br>3. Each change auto-submits without a 500.<br>4. URL includes non-empty `from`, `to`, `category`, `country`, `show_countries=3`, `show_cities=3`, and `show_biggest=3`; only Bikes and United States are checked; the three unchecked panel headings are absent; the country and city lists have 1–3 rows each; the Top customers table has 1–3 data rows; the growth chart still has a count axis with ticks and at least one bar; the map container is visible and the bubble JSON remains non-empty.<br>5. `/customer-profile/` restores all eight panels, all category and country checkboxes checked, and default row counts 6 countries, 8 cities, 8 customers. | Pass |

## Revenue and loss

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-05 | 1. Log in as the global Administrator and open `/revenue-and-loss/`.<br>2. Assert the default panels, the two side-by-side equal-column groups, the revenue money axis, 12 bars, line-chart tick positions, and gross-profit/margin chart marks.<br>3. Combined filters: keep From, set To to one month before the default To; check only `Bikes`; check only `United States` under Ship-to country; uncheck the `Key figures`, `Below-cost shortfall`, and `Calculation notes` panels; set `show_declining=3`, `show_leaks=3`, and `show_products=3`.<br>4. Assert the filtered page, URL, and preserved layout.<br>5. Reset the page. | 1. HTTP 200, heading `Revenue and loss report`.<br>2. Exactly two `.d-cols.equal` groups. The first contains `Revenue trend by month` and `Revenue contribution by category`; the second contains `Gross profit · selected period` and `Gross margin by month`. At 1440 px, both panels in each pair share the same top Y (within 2 px), have different X positions, and have widths within 5 px of each other. Revenue trend has 5 non-empty money-axis ticks and 12 bars. Both line-chart SVGs contain month tspans at `y="252"` and year tspans at `y="270"` and contain no month/year tspans at `y="244"` or `y="264"`. The profit chart has at least one `.profitbar`; the margin chart has a `.cur` polyline.<br>3. Each change auto-submits without a 500.<br>4. URL includes non-empty `from`, `to`, `category`, `show_declining=3`, `show_leaks=3`, and `show_products=3`; only Bikes is checked; KPI, below-cost, and calculation-notes headings are absent; the declining list and product table have 1–3 rows each; the Ship-to country fieldset is present with only United States checked and no `#report-chart-filter` exists; the revenue money axis still has ticks; the two equal-column groups remain side-by-side.<br>5. `/revenue-and-loss/` restores all panels, all categories checked, and default rows 8 declining, 6 below-cost, 8 products. | Pass |

## Cost

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-06 | 1. Log in as the global Administrator and open `/cost/`.<br>2. Assert the default panels, cost money axis, trend bars, distribution donut, performance split bar, and default row counts.<br>3. Combined filters: keep From, set To to one month before the default To; check only `Bikes`; uncheck the `Key figures`, `Category distribution`, and `Repricing` panels; set `show_vendors=3`, `show_products=3`, `show_reasons=3`, and `show_biggest=3`; set `cost_metric` to `Gross margin`.<br>4. Assert the filtered page and URL.<br>5. Set `cost_metric` back to `Cost of goods`.<br>6. Reset the page. | 1. HTTP 200, heading `Cost report`.<br>2. Panels present: Key figures, `Cost trends and comparisons`, `Cost distribution by category`, `Costs and business performance`, `Significant cost contributors: vendors`, `Significant cost contributors: products`, `Significant cost contributors: scrap`, `Significant cost contributors: repricing`, `Biggest purchase orders`. The trend has 5 non-empty money-axis ticks and 12 bars; a donut, a `.d-splitbar`, and a purchase-order table are present. Default rows: 8 vendors, 8 products, 8 scrap reasons, 6 repricing rows, 8 purchase orders.<br>3. Each change auto-submits without a 500.<br>4. URL includes non-empty `from`, `to`, `category`, `show_vendors=3`, `show_products=3`, `show_reasons=3`, `show_biggest=3`, and `cost_metric=margin`; only Bikes is checked; KPI, category-distribution, and repricing headings are absent; vendor/product/scrap lists and the purchase-order table have 1–3 rows; heading is `Gross margin trend`; subtitle starts `Monthly gross margin`; no `.d-y-axis` exists; no Ship-to country fieldset exists.<br>5. Heading returns to `Cost trends and comparisons`; 5 money-axis ticks and both Selected/Previous legends are present; URL has `cost_metric=cost`.<br>6. `/cost/` restores all panels, all categories checked, and default row counts. | Pass |

## Invalid and empty filters

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-07 | 1. For each page — `/dashboard/`, `/sales/`, `/customer-profile/`, `/revenue-and-loss/`, `/cost/` — request `?from=2014-12-31&to=2014-01-01`.<br>2. For each page, request `?from=not-a-date&to=also-bad`.<br>3. Request `/dashboard/?category=999999&show_products=not-a-number`.<br>4. Request `/sales/?category=999999&category_filter=1`.<br>5. Request `/sales/?country=ZZZ&country_filter=1`.<br>6. Request `/sales/?panel=bogus&panel_filter=1`.<br>7. Request `/sales/?show_products=999&sales_metric=bogus`.<br>8. Request `/cost/?show_vendors=999&cost_metric=bogus`.<br>9. Request `/sales/?from=2030-01-01&to=2030-01-31` and `/dashboard/?from=2030-01-01&to=2030-01-31`. | 1. All five return HTTP 200 with no 500. Dashboard shows `No data is available for this report.` at least once and no KPI/trend figures. Each report page keeps its heading and filter forms, shows no KPI cards and no report data (empty panel shells may remain), and does not render an empty-data sentence (the report templates do not currently display `empty_message`).<br>2. All five return HTTP 200; malformed dates are ignored and the page falls back to the rolling default range; From/To inputs contain valid ISO dates and normal data returns.<br>3. 200; category select shows `All categories`; Show products falls back to 10; no 500.<br>4. 200; invalid category produces an empty report area (no KPI cards or data rows) while the filter controls remain; no 500.<br>5. 200; invalid country produces an empty report area while the filter controls remain; no 500.<br>6. 200; invalid panel value is ignored, so no report data is shown; filter controls remain; no 500.<br>7. 200; `sales_metric` falls back to `Sales dollars`; Show products falls back to 8; the money axis and 8 high-performing rows return; no 500.<br>8. 200; `cost_metric` falls back to `Cost of goods`; Show vendors falls back to 8; the money axis and 8 vendor rows return; no 500.<br>9. Both return 200; the future range yields the dashboard empty message and no report data on sales; no 500. | Pass |

## RBAC — report tabs

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-08 | For every department/role pair (16 pairs):<br>1. Log in with that demo account.<br>2. Assert the top navigation.<br>3. Open the department's report URL.<br>4. Request the other three report URLs. | 1. Login succeeds and lands on `/dashboard/`.<br>2. Top navigation shows Dashboard, exactly the department's own report tab, and the account email plus Log out. Marketing sees Customer profile; Finance sees Revenue and loss; Production sees Cost; Sales sees Sales. Department Admin additionally sees Manage users and Audit Logs. No department role sees Manage Permissions.<br>3. Own report returns HTTP 200 and the matching heading: Sales report, Customer profile report, Revenue and loss report, or Cost report.<br>4. Each other report URL returns HTTP 403; no 500. | Pass |

## RBAC — source tables

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-09 | For every department/role pair:<br>1. Log in and open the department's report.<br>2. Inspect the module sub-navigation.<br>3. Request every table-list URL declared for that module in `accounts/roles.py`.<br>4. Request one table-list URL from a different department.<br>5. Check the table rows for edit/delete actions. | 1. Login and own report succeed.<br>2. Department Admin, Manager, and Supervisor see every source-table link for their module. Employee sees no source-table links (an empty sub-navigation container may remain).<br>3. Admin, Manager, and Supervisor receive HTTP 200 for every own-module table. Employee receives HTTP 403 for every own-module table.<br>4. Every department role receives HTTP 403 for the other department's table.<br>5. No department role sees `edit` or `delete` links on table rows; only the global Administrator can mutate source rows. | Pass |

## RBAC — report generation and saved reports

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-10 | For every department/role pair:<br>1. Log in and open the department's report.<br>2. Inspect the Generate report control.<br>3. Open the module's saved-report list (`/<tab>/reports/`).<br>4. If the list has rows, inspect delete links. | 1. Login and own report succeed.<br>2. `#save-report-button` with text `Generate report` is visible for Department Admin and Manager; it is absent for Supervisor and Employee.<br>3. `Manage saved reports` is visible for every role; the saved-report list returns HTTP 200 with heading `Saved reports` and either a table or `No saved reports for this module. Generate one from the report page.`<br>4. Delete links appear only for Department Admin and Manager. Supervisors and Employees see no delete links. | Pass |

## RBAC — department users and audit

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-11 | For every department/role pair:<br>1. Log in.<br>2. Inspect the top navigation.<br>3. Request `/users/` and `/users/add/`.<br>4. Request `/users/audit/`.<br>5. Request `/users/groups/`. | 1. Login succeeds.<br>2. Only Department Admin sees Manage users and Audit Logs. Manager, Supervisor, and Employee see neither.<br>3. Department Admin receives HTTP 200; the heading is `<Department> users`; the list excludes other departments' users and excludes all department Administrators. The Add user form offers only `<Department> Manager`, `<Department> Supervisor`, and `<Department> Employee` roles. Manager, Supervisor, and Employee receive HTTP 403 for both URLs.<br>4. Department Admin receives HTTP 200 with heading `<Department> audit log`; other roles receive HTTP 403.<br>5. All four department roles receive HTTP 403. The page is restricted to the global Administrator. | Pass |

## RBAC — global Administrator

| Test Case No. | Steps | Expected Result | Actual Result |
|---|---|---|---|
| TC-12 | 1. Log in as `admin@example.com` / `admin`.<br>2. Inspect the top navigation.<br>3. Open all four report URLs and the dashboard.<br>4. Open `/users/`, `/users/add/`, `/users/audit/`, and `/users/groups/`; open one group-edit page.<br>5. Open one table list in each department and inspect row actions. | 1. Login succeeds.<br>2. Navigation shows Dashboard, all four report tabs, Manage users, Audit Logs, Manage Permissions, `admin@example.com (Administrator)`, and Log out.<br>3. Dashboard and all four report pages return HTTP 200 with their expected headings.<br>4. `/users/` returns 200 with heading `All users`; `/users/add/` returns 200 and the role select includes Administrator plus the 16 scoped roles; `/users/audit/` returns 200 with heading `All departments audit log`; `/users/groups/` returns 200 with heading `Manage Permissions` and the 16 scoped groups (no group named Administrator); the first group-edit page returns 200 with permission checkboxes and a Save permissions button.<br>5. Each department's first table list returns 200 with at least one data row, and the rows expose both `edit` and `delete` links. | Pass |

## Playwright mapping (planned)

| Test Case No. | Target test |
|---|---|
| TC-01 | `tests/test_auth.py::test_tc01_authentication` |
| TC-02 | `tests/test_dashboard.py::test_tc02_dashboard_default_and_filters` |
| TC-03 | `tests/test_sales.py::test_tc03_sales_default_and_filters` |
| TC-04 | `tests/test_customer_profile.py::test_tc04_customer_profile_default_and_filters` |
| TC-05 | `tests/test_revenue_loss.py::test_tc05_revenue_loss_default_and_filters` |
| TC-06 | `tests/test_cost.py::test_tc06_cost_default_and_filters` |
| TC-07 | `tests/test_invalid_filters.py::test_tc07_invalid_and_empty_filters` |
| TC-08 | `tests/test_rbac.py::test_tc08_report_tab_access` |
| TC-09 | `tests/test_rbac.py::test_tc09_source_table_access` |
| TC-10 | `tests/test_rbac.py::test_tc10_report_generation_and_saved_reports` |
| TC-11 | `tests/test_rbac.py::test_tc11_department_users_and_audit` |
| TC-12 | `tests/test_rbac.py::test_tc12_global_administrator` |

## Known issues and decisions to confirm while iterating

1. `accounts/tests.py` still expects a department Admin to manage group permissions (`test_department_admin_sees_only_own_groups` and `test_department_admin_cannot_grant_other_department_permission`), but current `accounts/views.py` and `accounts/roles.py` restrict that page to the global Administrator. This matrix follows the current application behavior: all department roles receive 403. If the intended behavior is department-scoped group administration, the code and matrix must change before Playwright is written.
2. Report templates do not display `empty_message`; only the dashboard does. The matrix records that behavior. If an empty-range message is desired on report pages, it is a separate UI change.
3. `Actual Result` is filled from the last pytest run.
4. The tests are read-only and use the live AdventureWorks database. CI currently runs `python manage.py test` against an empty MSSQL service; it should stay unchanged until a deterministic data seed exists for Playwright.
