# AdventureWorks

## Local

1. Install SQL Server 2025 and ODBC Driver 18.
2. Restore `AdventureWorks2025.bak` as `AdventureWorks2025` in SQL Server.
3. Install dependencies:

   ```powershell
   py -3.12 -m pip install -r requirements.txt
   ```

4. Create tables and permissions:

   ```powershell
   py -3.12 manage.py migrate
   ```

5. Create roles and demo users:

   ```powershell
   py -3.12 manage.py seed_users --if-empty
   ```

6. Start the app:

   ```powershell
   py -3.12 manage.py runserver
   ```

7. Log in with `admin@example.com` / `admin`.

## Live Cloud Run

1. Import the `.bak` into Cloud SQL as `AdventureWorks2025`.
2. Wait for the import operation to finish.
3. Open Cloud Run > `adventureworks` > **Redeploy**.
4. Wait for the revision to become healthy.
5. Check logs for migration and seeding completion.
6. Open the Cloud Run URL and log in.
