# AdventureWorks (2025 build): Django + SQLite, dashboard and four reports, role-based access, RA 10173 privacy governance

Source data: Microsoft's `AdventureWorks-oltp-install-script.zip`
https://github.com/Microsoft/sql-server-samples/releases/tag/adventureworks

## Run it (prebuilt database)
1. `pip install -r requirements.txt` (Django 6.0.5, gunicorn, whitenoise)
2. `git clone` the repo (`adventureworks.sqlite3`, ~78 MB, is a plain file in git; no Git LFS needed)
3. `python manage.py migrate`
4. `python manage.py seed_reports` (optional; fills missing default report snapshots)
5. `python manage.py runserver`
6. Open http://127.0.0.1:8000/ and log in.

The shipped database already has all the logins (see Roles below): the single Administrator
(superuser `admin` / `admin`) plus 12 demo department users. The first sign-in asks you to
acknowledge the Data Privacy Notice (see Data privacy below). Change the passwords on /manage/
before real use.

## Layout
    aw_project/         settings.py, urls.py (project configuration, not an app)
    core/               the one app
      models.py         the 19 AdventureWorks models still used by the report SQL, plus:
                        + TabAccess, one permission per tab (access_sales, access_customer_profile, ...)
                        + PrivacyAcknowledgment and PRIVACY_NOTICE_VERSION (data privacy governance)
                        + AuditLog, the append-only record of every table edit and deletion
                        + Report, the single saved-report table (all four modules)
      services/         report SQL and context builders (sales, customer_profile,
                        revenue_and_loss, cost), dashboard, shared snapshot helpers,
                        payload validation, saved-report editor, table helpers, registry
      views.py          thin HTTP views: home, report pages, saved-report CRUD, and the
                        shared list / detail / edit / delete table pages plus autocomplete
      utils.py          number formatting and date-window helpers
      constants.py      report labels, editor metadata, and table column hints
      roles.py          ROLES (the 12 department roles) and apply_roles; see core/tests.py
      forms.py          the login form: credentials + the required privacy acknowledgment
      tests.py          fast RBAC, table-browser, privacy and report-semantics tests
      admin.py          read-only privacy and audit records (visible at /manage/)
      management/       commands/seed_users.py: one demo login per role (username = password)
                        commands/seed_reports.py: default rolling 12-month snapshots per module
      widgets.py        SearchSelect, the on-demand foreign-key box for the edit pages
      static/core/      autocomplete.js, the tiny script behind the edit page's foreign-key boxes
      templates/        base, dashboard, list, detail, form, confirm_delete, no_access,
                        privacy notice, report pages, login, 403

## Pages
    /login/                                  login (public; requires acknowledging the privacy notice)
    /privacy/                                data privacy notice (public, RA 10173)
    /                                        goes to the dashboard (or no-access page)
    /dashboard/                              consolidated KPIs, charts, filters and report links;
                                             shows only the modules the user may open
    /sales/ /customer-profile/ /revenue-and-loss/ /cost/    report page per module
    /<tab>/report/generate/                  POST: save or replace a snapshot (manager)
    /<tab>/reports/                          saved reports for the module
    /<tab>/reports/<id>/edit/                edit a saved report
    /<tab>/reports/<id>/delete/              delete a saved report
    /<tab>/data/<Table>/                     list (search with ?q=)
    /<tab>/data/<Table>/<id>/                detail
    /<tab>/data/<Table>/<id>/edit/           edit
    /<tab>/data/<Table>/<id>/delete/         delete
    /manage/                                 Users, roles, privacy and audit records (Administrator only)

## Saved reports
There is one table, `Report`. One row is one saved report for a module and effective date range.
All panel data lives in `payload` JSON, including the KPI numbers, monthly trends,
product/customer/vendor rows, chart geometry and recommendations. This keeps the schema simple:
there are no per-module KPI columns.

Opening a report tab with no query parameters loads the latest saved row for that module.
`?report=<id>` opens a specific snapshot; an empty `?report=` or a custom `?from=&to=` range runs
live SQL and shows the "Live data" banner. If a module has no saved row yet, it also falls back to
live SQL. Managers can press **Generate report** to save the current range or **Regenerate report**
to recalculate it. Saved rows are edited at `/<tab>/reports/`: the title and the structured payload
sections, including the KPI values, are editable. Chart geometry is read-only.

`python manage.py seed_reports` creates the default rolling 12-month snapshot for every module and
skips ranges that already exist; add `--force` to replace them. The Railway start command runs it on
every boot, so a fresh volume gets fast default reports without overwriting edited snapshots.

## Roles (RBAC)
* **Administrator** = the single Django superuser (`admin`; `createsuperuser`). It can open every
  tab and every table. There is no Administrator group.
* **Department roles** are 12 Django groups in `core/roles.py`: Manager, Supervisor and Employee
  for each of four departments. Each department gets exactly one tab:
  * Sales -> Sales
  * Marketing -> Customer Profile
  * Finance -> Revenue and Loss
  * Production -> Cost
  Apply them with
  `python manage.py shell -c "from core.roles import ROLES, apply_roles; apply_roles(ROLES, prune=True)"`;
  `prune=True` removes old groups. Add users at /manage/ -> Groups / Users. Applying is safe to repeat.
* **Permissions**:
  * Manager: opens the department tab, views its source tables and saved report, and
    edits/deletes/generates the saved report.
  * Supervisor: opens the tab and views its source tables and saved report; read-only.
  * Employee: opens the tab and views its saved report only; no source tables, no edits.
  * Source tables are read-only for every non-Administrator role. Nobody can create source records.
* **Demo logins**: one per role, username = password — `sales.manager`, `sales.supervisor`,
  `sales.employee`, `marketing.manager`, `marketing.supervisor`, `marketing.employee`,
  `finance.manager`, `finance.supervisor`, `finance.employee`, `production.manager`,
  `production.supervisor`, `production.employee`. Run
  `python manage.py seed_users --reset --prune` to create/reset them and remove the old 17 demo
  users. Safe to repeat.
* A user sees a tab only with its `access_<tab>` permission, and a table only with `view_<table>`.
  Managers and Supervisors get read-only table access; only the Administrator can edit/delete
  source-table rows. Managers can edit/delete their saved report. A saved report is created by
  **Generate report**, not by a blank create form.

### RBAC matrix

`Manager`, `Supervisor`, and `Employee` are scoped to the department named in their group.
The Administrator is the single superuser; there is no Administrator group.

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

No role can create source records through the UI. Report pages and saved-report lists are
gated by `access_<tab>`; table pages need `view_<table>`.

## Data privacy and governance (RA 10173)
* `/privacy/` is the published, versioned **Data Privacy Notice**: data inventory, legal bases
  (DPA Sections 12 and 13), least-privilege access, protection, retention and disposal, the data
  subject rights, 15-working-day request handling, breach notification (NPC Circular No. 16-03) and
  the DPO contact. It is public and linked in the footer of every page.
* **Logging in requires acknowledging the notice**: the checkbox on the login form is validated on
  the server, so an unchecked box cannot log anyone in.
* Every successful login **records the acknowledgment** — `PrivacyAcknowledgment` stores the user,
  the notice version and the timestamp (audit evidence). Bump `PRIVACY_NOTICE_VERSION` in
  `core/models.py` when the notice changes; users then re-acknowledge at their next login, which
  refreshes the record. The records are visible read-only at `/manage/`.
* Every page obeys the same role gates, and no role can create records.
* Every edit or deletion made through the table pages is written to the **audit trail** (`AuditLog`):
  the account, time, record, changed values (old and new), and IP address. Records are kept twelve
  months per the notice, cannot be changed or deleted from the UI, and are visible read-only at `/manage/`.

## Deploy (Railway)
The repo is deploy-ready: `requirements.txt` (Django 6.0.5, gunicorn, whitenoise), `.python-version`
(3.12) and `railway.json` — build runs `collectstatic`; the start command copies the shipped database
onto the volume on first boot, migrates, seeds any missing default report snapshots, then serves with
gunicorn on `$PORT`. Whitenoise serves
`/static/`, and `SECURE_PROXY_SSL_HEADER` lets Django trust Railway's HTTPS proxy (needed for the login
CSRF check). Set these service variables:
* `DJANGO_SECRET_KEY` — a long random value
* `DJANGO_DEBUG=0`
* `DJANGO_ALLOWED_HOSTS=.up.railway.app`
* `AW_DB_PATH=/data/adventureworks.sqlite3` — mount a volume at `/data` so logins survive redeploys
* `DJANGO_CSRF_TRUSTED_ORIGINS=https://<domain>` — after `railway domain`

Then `railway up`.

## Notes
* Tables with pages: 32. The second nav bar in `base.html` hardcodes one link per table; add a link there to add a table.
* Composite-key tables use their identity column or a new `id` as primary key; the old key columns remain
  a unique constraint. All foreign keys use `on_delete=PROTECT`.
* `LineTotal`, `TotalDue`, `StockedQty` are database-generated columns. `SubTotal` is a normal column:
  recalculate it in your order edit page.
* 85 of 88 CHECK constraints are enforced (not translated: Employee BirthDate/HireDate, ProductInventory Shelf).
* `SalesOrderDetail.clean()` enforces SQL Server's composite FK to SpecialOfferProduct.
* Order dates run 2022-05-30 to 2025-06-29: do not default date filters to "today".
* Report money is USD. AdventureWorks stores sales line totals and header tax/freight/total due
  in USD; `CurrencyRateID` records the order's currency but is not applied to those amounts.
  Sales revenue uses `SalesOrderDetail.LineTotal`, not the header `SubTotal`.
* Cost of goods is quantity sold × `ProductCostHistory.StandardCost` effective on the order date,
  falling back to `Product.StandardCost` when no history row covers that date.
* Procurement spend, vendor rankings and biggest purchase orders use purchase-order `SubTotal`
  (merchandise only) and exclude `Status=3` rejected orders. Receipt rejection includes every PO
  status: a rejected PO is a fully rejected receipt, so excluding it would hide the quality problem.
* The default report window ends at the end of the month containing the last sales order. A custom
  `from`/`to` range is honored exactly, even when it extends past the last sale or purchase order;
  empty months are zero. Purchase orders after the default sales period are future commitments,
  not period spend.
* Previous-period comparisons use the period immediately before the selected window. Custom
  ranges use the same number of days; the default uses the preceding 12 calendar months. A custom
  window that starts near the first order date has only a partial prior period, so its percentage
  changes can be extreme. Gross margin is shown in its own chart, like the dashboard, with the
  selected period solid and the previous period dashed.
* Customer geography is grouped by the order's ship-to address; city rows include state/province
  and country so same-named cities are not merged. Store-network revenue and active counts use only
  stores with sales in the selected window; store totals remain all stores.
* High-value customers are shown as the top 6 stores and top 3 individuals, ranked separately.
* Keep `PersonPassword` and `SalesCreditCard` out of your pages (they are not registered).
* Before deploying anywhere public: set DJANGO_SECRET_KEY, DJANGO_DEBUG=0 and DJANGO_ALLOWED_HOSTS.
