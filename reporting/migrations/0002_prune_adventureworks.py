from django.db import migrations


def prune(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    sql = r"""
    IF EXISTS (SELECT 1 FROM sys.triggers WHERE name='ddlDatabaseTriggerLog' AND parent_class_desc='DATABASE')
        DISABLE TRIGGER ddlDatabaseTriggerLog ON DATABASE;
    DECLARE @keep TABLE (schema_name sysname, table_name sysname);
    INSERT INTO @keep VALUES
    ('Person','Address'),('Person','BusinessEntity'),('Person','CountryRegion'),('Person','Person'),('Person','StateProvince'),
    ('Sales','Customer'),('Sales','SalesOrderDetail'),('Sales','SalesOrderHeader'),('Sales','SalesTerritory'),('Sales','Store'),
    ('Production','Product'),('Production','ProductCategory'),('Production','ProductCostHistory'),('Production','ProductSubcategory'),('Production','ScrapReason'),('Production','WorkOrder'),
    ('Purchasing','PurchaseOrderDetail'),('Purchasing','PurchaseOrderHeader'),('Purchasing','Vendor'),
    ('dbo','auth_group'),('dbo','auth_group_permissions'),('dbo','auth_permission'),('dbo','auth_user'),('dbo','auth_user_groups'),('dbo','auth_user_user_permissions'),
    ('dbo','django_admin_log'),('dbo','django_content_type'),('dbo','django_migrations'),('dbo','django_session'),('dbo','audit_log'),('dbo','reports');
    DECLARE @sql nvarchar(max)=N'';
    SELECT @sql += N'DROP VIEW '+QUOTENAME(s.name)+N'.'+QUOTENAME(v.name)+N';'
    FROM sys.views v JOIN sys.schemas s ON s.schema_id=v.schema_id;
    IF @sql<>N'' EXEC sys.sp_executesql @sql;
    SET @sql=N'';
    SELECT @sql += N'ALTER TABLE '+QUOTENAME(SCHEMA_NAME(pt.schema_id))+N'.'+QUOTENAME(pt.name)+N' DROP CONSTRAINT '+QUOTENAME(fk.name)+N';'
    FROM sys.foreign_keys fk JOIN sys.tables pt ON pt.object_id=fk.parent_object_id JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id
    WHERE NOT EXISTS (SELECT 1 FROM @keep k WHERE k.schema_name=SCHEMA_NAME(pt.schema_id) AND k.table_name=pt.name)
       OR NOT EXISTS (SELECT 1 FROM @keep k WHERE k.schema_name=SCHEMA_NAME(rt.schema_id) AND k.table_name=rt.name);
    IF @sql<>N'' EXEC sys.sp_executesql @sql;
    SET @sql=N'';
    SELECT @sql += N'DROP TABLE '+QUOTENAME(s.name)+N'.'+QUOTENAME(t.name)+N';'
    FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
    WHERE NOT EXISTS (SELECT 1 FROM @keep k WHERE k.schema_name=s.name AND k.table_name=t.name);
    IF @sql<>N'' EXEC sys.sp_executesql @sql;
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("reporting", "0001_initial"),
    ]

    operations = [migrations.RunPython(prune, migrations.RunPython.noop)]
