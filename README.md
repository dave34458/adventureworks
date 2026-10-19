# AdventureWorks (2025 build): Django + SQLite, four tabs, role-based access, RA 10173 privacy governance

Source data: Microsoft's `AdventureWorks-oltp-install-script.zip`
https://github.com/Microsoft/sql-server-samples/releases/tag/adventureworks

## Run it (prebuilt database)
1. `pip install "Django>=5.2,<5.3"`
2. `git clone` the repo (`adventureworks.sqlite3`, ~78 MB, is a plain file in git; no Git LFS needed)
3. `python manage.py runserver`
4. Open http://127.0.0.1:8000/ and log in.

The shipped database already has all the logins (see Roles below): superuser `admin` / `admin`
plus the 17 demo role users. The first sign-in asks you to acknowledge the Data Privacy Notice
(see Data privacy below). Change the passwords on /manage/ before real use.

## Layout
    aw_project/         settings.py, urls.py (project configuration, not an app)
    core/               the one app
      models.py         the 71 AdventureWorks models (generated; do not edit by hand)
                        + TabAccess, one permission per tab (access_sales, access_customer_profile, ...)
                        + PrivacyAcknowledgment and PRIVACY_NOTICE_VERSION (data privacy governance)
      views.py          all views: home, one dashboard view per tab (sales, customer_profile,
                        revenue_and_loss, cost) and the shared list / detail / edit / delete pages
                        every table uses, plus the JSON autocomplete they call
      roles.py          ROLES (the 17 department roles) and apply_roles; see core/tests.py
      forms.py          the login form: credentials + the required privacy acknowledgment
      tests.py          RBAC + privacy tests: the department matrix, applied and checked over HTTP
      admin.py          read-only privacy acknowledgment records (visible at /manage/)
      management/       commands/seed_users.py: one demo login per role (username = password)
      widgets.py        SearchSelect, the on-demand foreign-key box for the edit pages
      static/core/      autocomplete.js, the tiny script behind the edit page's foreign-key boxes
      templates/        base, list, detail, form, confirm_delete, no_access, privacy notice,
                        per-tab dashboards, login, 403

## Pages
    /login/                                  login (public; requires acknowledging the privacy notice)
    /privacy/                                data privacy notice (public, RA 10173)
    /                                        goes to the first tab the user may open
    /sales/ /customer-profile/ /revenue-and-loss/ /cost/    dashboard page per tab
    /<tab>/data/<Table>/                     list (search with ?q=)
    /<tab>/data/<Table>/<id>/                detail
    /<tab>/data/<Table>/<id>/edit/           edit
    /<tab>/data/<Table>/<id>/delete/         delete
    /manage/                                 Users, roles and privacy records (superadmin only)

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
* Exports obey the same role gates as the pages, and no role can create records.

## Notes
* Tables with pages: 32. The second nav bar in `base.html` hardcodes one link per table; add a link there to add a table.
* Composite-key tables use their identity column or a new `id` as primary key; the old key columns remain
  a unique constraint. All foreign keys use `on_delete=PROTECT`.
* `LineTotal`, `TotalDue`, `StockedQty` are database-generated columns. `SubTotal` is a normal column:
  recalculate it in your order edit page.
* 85 of 88 CHECK constraints are enforced (not translated: Employee BirthDate/HireDate, ProductInventory Shelf).
* `SalesOrderDetail.clean()` enforces SQL Server's composite FK to SpecialOfferProduct.
* Order dates run 2022-05-30 to 2025-06-29: do not default date filters to "today".
* Keep `PersonPassword` and `SalesCreditCard` out of your pages (they are not registered).
* Before deploying anywhere public: set DJANGO_SECRET_KEY, DJANGO_DEBUG=0 and DJANGO_ALLOWED_HOSTS.
