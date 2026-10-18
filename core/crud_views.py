from datetime import date, datetime, time

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.models import ProtectedError, Q, TextField
from django.db.models.functions import Cast
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from .tabs import LABELS, TAB_OF, TABS, visible_tables
from .widgets import FastSelect


def shown(model):
    """Fields worth showing in tables: skip blobs (all other columns are kept)."""
    return [f for f in model._meta.fields
            if f.get_internal_type() != "BinaryField"]


# the biggest dropdowns only load the columns their names are built from
LABEL_COLUMNS = {
    "SalesOrderHeader": ["sales_order_number"],
    "Person": ["first_name", "last_name"],
    "PersonAddress": ["address_line1", "city"],
}
_JOINS = {}


def name_needs_joins(model):
    """True if str(record) runs extra queries, so dropdowns must join the related tables."""
    if model not in _JOINS:
        obj, hits = model._default_manager.first(), []
        if obj is not None:
            with connection.execute_wrapper(lambda ex, sql, p, many, ctx: (hits.append(1), ex(sql, p, many, ctx))[1]):
                str(obj)
        _JOINS[model] = bool(hits)
    return _JOINS[model]


class TableMixin(PermissionRequiredMixin):
    perm = None  # "view", "change" or "delete"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.tab, name = kwargs["tab"], kwargs["model"]
        if name not in TABS.get(self.tab, []):
            raise Http404
        self.model = apps.get_model("core", name)

    def get_permission_required(self):
        return [f"core.access_{self.tab}", f"core.{self.perm}_{self.model._meta.model_name}"]

    def get_success_url(self):
        return reverse("table_list", args=[self.tab, self.model.__name__])

    def get_context_data(self, **kw):
        user, label = self.request.user, self.model._meta.model_name
        return super().get_context_data(
            tab=self.tab, tab_label=LABELS[self.tab], tables=visible_tables(user, self.tab),
            name=self.model.__name__, title=self.model._meta.verbose_name.capitalize(),
            can_change=user.has_perm(f"core.change_{label}"), can_delete=user.has_perm(f"core.delete_{label}"), **kw)


def cell(obj, f):
    """One table cell: its text, plus a link to the related record when it is a foreign key."""
    value = getattr(obj, f.name)
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat().replace("T", " ")
    if f.is_relation and value is not None and type(value).__name__ in TAB_OF:
        name = type(value).__name__
        return {"text": str(value), "url": reverse("table_detail", args=[TAB_OF[name], name, value.pk])}
    return {"text": "" if value is None else value, "url": None}


class TableList(TableMixin, ListView):
    perm, paginate_by, template_name = "view", 50, "core/list.html"

    def get_queryset(self):
        fks = [f.name for f in self.model._meta.fields if f.is_relation]
        qs = self.model._default_manager.select_related(*fks).order_by("pk")
        q, col = self.request.GET.get("q", "").strip(), self.request.GET.get("col", "")
        if q:
            castable = ("AutoField", "BigAutoField", "IntegerField", "BigIntegerField",
                        "SmallIntegerField", "PositiveIntegerField", "FloatField",
                        "DecimalField", "DateField", "DateTimeField", "TimeField", "UUIDField")
            fields = {f.name: f for f in self.model._meta.fields}
            targets = [fields[col]] if col in fields else list(fields.values())
            conds, ann = [], {}
            for f in targets:
                t = f.get_internal_type()
                if t in ("BinaryField", "BooleanField"):
                    continue
                if f.is_relation:
                    # also search the related record's label (first 2 CharFields)
                    rel = f.related_model
                    subs = [s for s in rel._meta.fields
                            if s.get_internal_type() == "CharField"][:2]
                    conds += [Q(**{f"{f.name}__{s.name}__icontains": q}) for s in subs]
                    # names often live one hop away, via a FK to Person (customer, employee, ...)
                    pf = next((r.name for r in rel._meta.fields
                               if r.is_relation and r.related_model.__name__ == "Person"), None)
                    if pf:
                        conds += [Q(**{f"{f.name}__{pf}__{n}__icontains": q})
                                  for n in ("first_name", "last_name")]
                elif t in castable:
                    # numbers, dates and uuids: cast to text first, LIKE does not match them raw
                    key = f"txt_{f.name}"
                    ann[key] = Cast(f.name, output_field=TextField())
                    # SQLite stores uuids as hex without dashes, so drop them from the needle
                    conds.append(Q(**{f"{key}__icontains": q.replace("-", "") if t == "UUIDField" else q}))
                    if t not in ("DateField", "DateTimeField", "TimeField", "UUIDField"):
                        # exact value too, so "201.0400" matches a stored 201.04
                        try:
                            conds.append(Q(**{f.name: float(q)}))
                        except ValueError:
                            pass
                else:
                    conds.append(Q(**{f"{f.name}__icontains": q}))
            qs = qs.annotate(**ann).filter(Q(*conds, _connector=Q.OR)) if conds else qs.none()
        sort = self.request.GET.get("sort", "")
        name = sort[1:] if sort.startswith("-") else sort
        try:
            sf = self.model._meta.get_field(name) if name else None
        except FieldDoesNotExist:
            sf = None
        if sf is not None:
            prefix = "-" if sort.startswith("-") else ""
            if sf.is_relation:
                # fk columns sort by the label you see (the related person, or first CharFields)
                rel = sf.related_model
                pf = next((r.name for r in rel._meta.fields
                           if r.is_relation and r.related_model.__name__ == "Person"), None)
                if pf:
                    subs = [f"{pf}__first_name", f"{pf}__last_name"]
                else:
                    subs = [s.name for s in rel._meta.fields
                            if s.get_internal_type() == "CharField"][:2]
                if subs:
                    qs = qs.order_by(*[f"{prefix}{sf.name}__{s}" for s in subs], "pk")
            else:
                qs = qs.order_by(f"{prefix}{sf.name}", "pk")
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        fields = shown(self.model)
        sort = self.request.GET.get("sort", "")
        ctx["headers"] = [(f.verbose_name, f.name) for f in fields]
        ctx["rows"] = [{"obj": o, "cells": [cell(o, f) for f in fields]} for o in ctx["object_list"]]
        ctx["columns"] = [(f.verbose_name, f.name) for f in self.model._meta.fields
                          if f.get_internal_type() not in ("BinaryField", "BooleanField")]
        ctx["col"] = self.request.GET.get("col", "")
        ctx["sort"], ctx["sort_desc"] = sort.lstrip("-"), sort.startswith("-")
        return ctx


class TableDetail(TableMixin, DetailView):
    perm, template_name = "view", "core/detail.html"

    def get_context_data(self, **kw):
        fields = [f for f in self.model._meta.fields if f.get_internal_type() != "BinaryField"]
        return super().get_context_data(
            fields=[(f.verbose_name, cell(self.object, f)) for f in fields], **kw)


class TableEdit(TableMixin, UpdateView):
    perm, template_name = "change", "core/form.html"

    def get_form_class(self):
        names = [f.name for f in self.model._meta.fields
                 if f.editable and not f.primary_key and f.name != "modified_date"]
        return forms.modelform_factory(self.model, fields=names)

    def get_form(self, *a, **kw):
        form = super().get_form(*a, **kw)
        for field in form.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                # dropdowns show each record's name; join what its name is built from in one query
                rel = field.queryset.model
                fks = [f.name for f in rel._meta.fields if f.is_relation] if name_needs_joins(rel) else []
                has_name = any(f.name == "name" for f in rel._meta.fields)
                field.widget = FastSelect(attrs=field.widget.attrs)
                field.widget.is_required = field.required
                qs = field.queryset.select_related(*fks).order_by("name" if has_name else "pk")
                if rel.__name__ in LABEL_COLUMNS:
                    qs = qs.only(*LABEL_COLUMNS[rel.__name__])
                field.queryset = qs
        return form

    def form_valid(self, form):
        if hasattr(form.instance, "modified_date"):
            form.instance.modified_date = timezone.now()
        messages.success(self.request, f"Saved {form.instance}.")
        return super().form_valid(form)


class TableDelete(TableMixin, DeleteView):
    perm, template_name = "delete", "core/confirm_delete.html"

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError as e:
            kinds = ", ".join(sorted({type(o).__name__ for o in e.protected_objects}))
            messages.error(request, f"Cannot delete: {len(e.protected_objects)} record(s) in {kinds} still point to it.")
            return redirect(request.path)
