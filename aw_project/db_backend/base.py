from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper
from mssql.features import DatabaseFeatures as MSSQLDatabaseFeatures


class DatabaseFeatures(MSSQLDatabaseFeatures):
    has_native_uuid_field = True


class DatabaseWrapper(MSSQLDatabaseWrapper):
    features_class = DatabaseFeatures
    data_types = {**MSSQLDatabaseWrapper.data_types, "UUIDField": "uniqueidentifier"}
