"""Generic table-browser helpers."""
from datetime import date, datetime, time
from functools import cache

from django.db import connection
from django.urls import reverse


def shown(model):
    """Fields worth showing in tables: skip blobs (all other columns are kept)."""
    return [f for f in model._meta.fields
            if f.get_internal_type() != "BinaryField"]


@cache
def name_needs_joins(model):
    """True if str(record) runs extra queries, so dropdowns must join the related tables."""
    obj = model._default_manager.first()
    if obj is None:
        return False
    hits = []

    def count_query(execute, sql, params, many, context):
        hits.append(1)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(count_query):
        str(obj)
    return bool(hits)


def cell(obj, f, tab):
    """One table cell: its text, plus a link to the related record when it is a foreign key."""
    value = getattr(obj, f.name)
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat().replace("T", " ")
    if f.is_relation and value is not None:
        name = type(value).__name__
        return {"text": str(value), "url": reverse("table_detail", args=[tab, name, value.pk])}
    return {"text": "" if value is None else value, "url": None}
