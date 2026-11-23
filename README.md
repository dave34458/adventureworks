# AdventureWorks

## Local

1. Install SQL Server 2025 and ODBC Driver 18.
2. Restore `AdventureWorks2025.bak` as `AdventureWorks2025` in SQL Server.
3. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

4. Create tables and permissions:

   ```
   py manage.py migrate
   ```

5. Create roles and demo users:

   ```
   py manage.py seed_users --if-empty
   ```

6. Start the app:

   ```
   py manage.py runserver
   ```

7. Log in with `admin@example.com` / `admin`.

## Live Cloud Run

1. Import the `.bak` into Cloud SQL as `AdventureWorks2025`.
2. Wait for the import operation to finish.
3. Open Cloud Run > `adventureworks` > **Redeploy**.
4. Wait for the revision to become healthy.
5. Check logs for migration and seeding completion.
6. Open the Cloud Run URL and log in.

## End-to-end tests

The browser suite covers the dashboard, four report modules, combined filters, invalid inputs and RBAC.

```
pip install -r requirements.txt
python -m playwright install chromium
python -m pytest tests -q
```

The suite reuses a healthy server at `http://127.0.0.1:8000` or starts one temporarily. Each run overwrites `docs/test-case-results.md` with the populated test-case table and actual pass/fail results.

To watch the browser while it runs, set `E2E_HEADLESS=0` (PowerShell: `$env:E2E_HEADLESS = "0"; python -m pytest tests -q`).
