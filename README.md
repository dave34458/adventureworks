# AdventureWorks (2025 build): Django + SQLite, four tabs, role-based access

Source data: Microsoft's `AdventureWorks-oltp-install-script.zip`
https://github.com/Microsoft/sql-server-samples/releases/tag/adventureworks

## Run it (prebuilt database)
1. `pip install "Django>=5.2,<5.3"`
2. `git clone` the repo (`adventureworks.sqlite3`, ~78 MB, is a plain file in git; no Git LFS needed)
3. `python manage.py runserver`
4. Open http://127.0.0.1:8000/ and log in.

The shipped database already has all the logins (see Roles below): superuser `admin` / `admin`
plus the 17 demo role users. Change the passwords on /manage/ before real use.

## Layout
    aw_project/         settings.py, urls.py (project configuration, not an app)
    core/               the one app
      models.py         the 71 AdventureWorks models (generated; do not edit by hand)
                        + TabAccess, one permission per tab (access_sales, access_customer_profile, ...)
      views.py          all views: home, one dashboard view per tab (sales, customer_profile,
                        revenue_and_loss, cost) and the shared list / detail / edit / delete pages
                        every table uses, plus the JSON autocomplete they call
      roles.py          ROLES (the 17 department roles) and apply_roles; see core/tests.py
      tests.py          RBAC tests: the department matrix, applied and checked over HTTP
      management/       commands/seed_users.py: one demo login per role (username = password)
      widgets.py        SearchSelect, the on-demand foreign-key box for the edit pages
      static/core/      autocomplete.js, the tiny script behind the edit page's foreign-key boxes
      templates/        base, list, detail, form, confirm_delete, no_access, per-tab dashboards,
                        login, 403

## Pages
    /login/                                  login (the only public page)
    /                                        goes to the first tab the user may open
    /sales/ /customer-profile/ /revenue-and-loss/ /cost/    dashboard page per tab
    /<tab>/data/<Table>/                     list (search with ?q=)
    /<tab>/data/<Table>/<id>/                detail
    /<tab>/data/<Table>/<id>/edit/           edit
    /<tab>/data/<Table>/<id>/delete/         delete
    /manage/                                 Users and Groups (superadmin only)

## Roles (RBAC)
* **Superadmin** = a Django superuser (`createsuperuser`). It can open every tab and every table.
* **Other roles** are 17 Django groups defined in `core/roles.py`, one per department (the same
  matrix lives in `core/tests.py`). Apply them with
  `python manage.py shell -c "from core.roles import ROLES, apply_roles; apply_roles(ROLES)"`,
  and add users to the group at /manage/ -> Groups / Users. Applying is safe to repeat.
* **Demo logins**: one user per role, username = password — `executive`, `finance.manager`,
  `finance.staff`, `sales.manager`, `sales.staff`, `marketing`, `purchasing.manager`,
  `purchasing.staff`, `shipping.receiving`, `production.manager`, `production.staff`,
  `production.control`, `quality.assurance`, `engineering.manager`, `engineering.staff`,
  `research.development`, `tool.design`. `python manage.py seed_users` creates or resets them
  (`--reset` also resets passwords); safe to repeat.
* A user sees a tab only with its `access_<tab>` permission, and a table only with `view_<table>`.
  The edit and delete links appear only with `change_<table>` / `delete_<table>`. Nobody can create records.

## Notes
* Tables with pages: 32 (each dashboard hardcodes its own links). Add a link there to add a table.
* Composite-key tables use their identity column or a new `id` as primary key; the old key columns remain
  a unique constraint. All foreign keys use `on_delete=PROTECT`.
* `LineTotal`, `TotalDue`, `StockedQty` are database-generated columns. `SubTotal` is a normal column:
  recalculate it in your order edit page.
* 85 of 88 CHECK constraints are enforced (not translated: Employee BirthDate/HireDate, ProductInventory Shelf).
* `SalesOrderDetail.clean()` enforces SQL Server's composite FK to SpecialOfferProduct.
* Order dates run 2022-05-30 to 2025-06-29: do not default date filters to "today".
* Keep `PersonPassword` and `SalesCreditCard` out of your pages (they are not registered).
* Before deploying anywhere public: set DJANGO_SECRET_KEY, DJANGO_DEBUG=0 and DJANGO_ALLOWED_HOSTS.
