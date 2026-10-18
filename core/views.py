"""All views for the app: home, the four dashboards, and the generic table browser
(list / detail / edit / delete / autocomplete) used by every table."""
from datetime import date, datetime, time

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.models import Count, ProtectedError, Q, Sum, TextField
from django.db.models.functions import Cast, TruncMonth
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from .models import SalesOrderDetail, SalesOrderHeader
from .utils import delta, money, rank, rolling_window
from .widgets import SearchSelect


# ---------------------------------------------------------------------------
# Pages: home, the four dashboards (below), and the generic table browser further down.
# Each dashboard is one view: it builds its own data and renders its own template.

def home(request):
    """Send the user to the first tab they may open, or explain that they have none."""
    for slug in ("sales", "customers", "costs", "finance"):
        if request.user.has_perm(f"core.access_{slug}"):
            return redirect(slug)
    return render(request, "core/no_access.html")


@permission_required("core.access_sales", raise_exception=True)
def sales(request):
    """Sales report dashboard: one aggregate query per panel, all windows anchored to the
    data's own last order date (the sample data is historical, so "today" would be empty)."""
    w = rolling_window(SalesOrderHeader)
    if w is None:
        return render(request, "core/sales/dashboard.html",
                      {"tab": "sales", "title": "Sales report"})

    cur, prev, trend_start = w.cur, w.prev, w.trend_start

    totals = SalesOrderHeader.objects.filter(order_date__gte=w.window_start).aggregate(
        rev=Sum("sub_total", filter=cur),
        rev_prev=Sum("sub_total", filter=prev),
        orders=Count("sales_order_id", filter=cur),
        orders_prev=Count("sales_order_id", filter=prev),
        customers=Count("customer", filter=cur, distinct=True),
        customers_prev=Count("customer", filter=prev, distinct=True),
        online_rev=Sum("sub_total", filter=cur & Q(online_order_flag=True)),
        online_orders=Count("sales_order_id", filter=cur & Q(online_order_flag=True)),
    )

    rev = totals["rev"] or 0
    orders = totals["orders"] or 0
    online_rev = totals["online_rev"] or 0
    online_orders = totals["online_orders"] or 0
    aov = (rev / orders) if orders else None
    aov_prev = (totals["rev_prev"] / totals["orders_prev"]) if totals["orders_prev"] else None
    share = round(float(online_rev) / float(rev) * 100) if rev else 0

    kpis = []
    for label, value, change, cap in (
        ("Revenue", money(rev), delta(rev, totals["rev_prev"]), "merchandise, excl. tax & freight"),
        ("Orders", f"{orders:,}", delta(orders, totals["orders_prev"]), "sales orders placed"),
        ("Avg order value", money(aov), delta(aov, aov_prev), "revenue per order"),
        ("Customers", f"{totals['customers'] or 0:,}", delta(totals["customers"], totals["customers_prev"]), "distinct buyers"),
        ("Online share", f"{share}%", (None, None), f"{money(online_rev)} · {online_orders:,} orders"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    months = list(
        SalesOrderHeader.objects.filter(cur)
        .annotate(month=TruncMonth("order_date"))
        .values("month")
        .annotate(rev=Sum("sub_total"), orders=Count("sales_order_id"))
        .order_by("month")
    )
    top = max((float(m["rev"] or 0) for m in months), default=0)
    trend = [
        {
            "label": m["month"].strftime("%b"),
            "full": m["month"].strftime("%b %Y"),
            "money": money(m["rev"]),
            "orders": f"{m['orders']:,}",
            "height": max(round(float(m["rev"] or 0) / top * 100), 2) if top else 0,
        }
        for m in months
    ]

    channels = [
        {"name": "Online", "pct": share, "money": money(online_rev), "orders": f"{online_orders:,}",
         "aov": money((online_rev / online_orders) if online_orders else None), "cls": "online"},
        {"name": "Assisted", "pct": 100 - share, "money": money(rev - online_rev), "orders": f"{orders - online_orders:,}",
         "aov": money(((rev - online_rev) / (orders - online_orders)) if orders - online_orders else None), "cls": "store"},
    ]

    territories = rank(
        SalesOrderHeader.objects.filter(cur)
        .values("territory__name").annotate(rev=Sum("sub_total")).order_by("-rev")[:8],
        "territory__name", "rev", money,
    )
    salespeople = rank(
        [
            {
                "name": " ".join(x for x in (
                    s["sales_person__business_entity__business_entity__first_name"],
                    s["sales_person__business_entity__business_entity__last_name"],
                ) if x),
                "rev": s["rev"],
            }
            for s in SalesOrderHeader.objects.filter(cur, sales_person__isnull=False)
            .values(
                "sales_person__business_entity__business_entity__first_name",
                "sales_person__business_entity__business_entity__last_name",
            )
            .annotate(rev=Sum("sub_total")).order_by("-rev")[:8]
        ],
        "name", "rev", money,
    )
    products = rank(
        SalesOrderDetail.objects.filter(sales_order__order_date__gte=trend_start)
        .values("product__name").annotate(rev=Sum("line_total")).order_by("-rev")[:8],
        "product__name", "rev", money,
    )
    offers = rank(
        SalesOrderDetail.objects.filter(sales_order__order_date__gte=trend_start)
        .exclude(special_offer__description="No Discount")
        .values("special_offer__description").annotate(rev=Sum("line_total")).order_by("-rev")[:6],
        "special_offer__description", "rev", money,
    )

    biggest = [
        {
            "id": r["sales_order_id"],
            "number": r["sales_order_number"],
            "date": r["order_date"],
            "territory": r["territory__name"] or "—",
            "who": " ".join(x for x in (
                r["sales_person__business_entity__business_entity__first_name"],
                r["sales_person__business_entity__business_entity__last_name"],
            ) if x) or "—",
            "total": money(r["sub_total"]),
            "online": r["online_order_flag"],
        }
        for r in SalesOrderHeader.objects.filter(cur).order_by("-sub_total")
        .values(
            "sales_order_id", "sales_order_number", "order_date", "territory__name", "sub_total",
            "online_order_flag",
            "sales_person__business_entity__business_entity__first_name",
            "sales_person__business_entity__business_entity__last_name",
        )[:8]
    ]

    return render(request, "core/sales/dashboard.html", {
        "tab": "sales",
        "title": "Sales report",
        "kpis": kpis,
        "trend": trend,
        "channels": channels,
        "territories": territories,
        "salespeople": salespeople,
        "products": products,
        "offers": offers,
        "biggest": biggest,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
    })


@permission_required("core.access_customers", raise_exception=True)
def customers(request):
    """Customer profile dashboard. Bare for now: the KPIs, infographic and chart data
    will be built here."""
    return render(request, "core/customers/dashboard.html",
                  {"tab": "customers", "title": "Customer profile"})


@permission_required("core.access_costs", raise_exception=True)
def costs(request):
    """Cost report dashboard. Bare for now: the KPIs, infographic and chart data
    will be built here."""
    return render(request, "core/costs/dashboard.html",
                  {"tab": "costs", "title": "Cost report"})


@permission_required("core.access_finance", raise_exception=True)
def finance(request):
    """Revenue and loss dashboard. Bare for now: the KPIs, infographic and chart data
    will be built here."""
    return render(request, "core/finance/dashboard.html",
                  {"tab": "finance", "title": "Revenue and loss"})


# ---------------------------------------------------------------------------
# The generic table browser: one set of views drives every table in every tab.

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
        try:
            self.model = apps.get_model("core", name)
        except LookupError:
            raise Http404

    def get_permission_required(self):
        return [f"core.access_{self.tab}", f"core.{self.perm}_{self.model._meta.model_name}"]

    def get_success_url(self):
        return reverse("table_list", args=[self.tab, self.model.__name__])

    def get_context_data(self, **kw):
        user, label = self.request.user, self.model._meta.model_name
        return super().get_context_data(
            tab=self.tab, name=self.model.__name__, title=self.model._meta.verbose_name.capitalize(),
            can_change=user.has_perm(f"core.change_{label}"), can_delete=user.has_perm(f"core.delete_{label}"), **kw)


def cell(obj, f, tab):
    """One table cell: its text, plus a link to the related record when it is a foreign key."""
    value = getattr(obj, f.name)
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat().replace("T", " ")
    if f.is_relation and value is not None:
        name = type(value).__name__
        return {"text": str(value), "url": reverse("table_detail", args=[tab, name, value.pk])}
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
        ctx["rows"] = [{"obj": o, "cells": [cell(o, f, self.tab) for f in fields]} for o in ctx["object_list"]]
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
            fields=[(f.verbose_name, cell(self.object, f, self.tab)) for f in fields], **kw)


class TableEdit(TableMixin, UpdateView):
    perm, template_name = "change", "core/form.html"

    def get_form_class(self):
        names = [f.name for f in self.model._meta.fields
                 if f.editable and not f.primary_key and f.name != "modified_date"]
        return forms.modelform_factory(self.model, fields=names)

    def get_form(self, *a, **kw):
        form = super().get_form(*a, **kw)
        for name, field in form.fields.items():
            if isinstance(field, forms.ModelChoiceField):
                # dropdowns show each record's name; join what its name is built from in one query
                rel = field.queryset.model
                fks = [f.name for f in rel._meta.fields if f.is_relation] if name_needs_joins(rel) else []
                qs = field.queryset.select_related(*fks)
                if rel.__name__ in LABEL_COLUMNS:
                    qs = qs.only(*LABEL_COLUMNS[rel.__name__])
                widget = SearchSelect(attrs=field.widget.attrs)
                widget.is_required = field.required
                widget.queryset = qs
                widget.url = reverse("table_autocomplete", args=[self.tab, self.model.__name__, name])
                field.widget = widget
                field.queryset = qs
        return form

    def form_valid(self, form):
        if hasattr(form.instance, "modified_date"):
            form.instance.modified_date = timezone.now()
        messages.success(self.request, f"Saved {form.instance}.")
        return super().form_valid(form)


class TableAutocomplete(TableMixin, View):
    """JSON search for one foreign-key field: the name fields of the target record (plus the
    person behind it, and the pk for labels like "PersonBusinessEntity 42"), 20 rows at most.
    Works for every table because it is driven by the model metadata."""
    perm = "view"

    def get(self, request, *args, **kwargs):
        try:
            f = self.model._meta.get_field(kwargs["field"])
        except FieldDoesNotExist:
            raise Http404
        if not f.is_relation or not f.editable:
            raise Http404
        rel, q = f.related_model, request.GET.get("q", "").strip()
        qs = rel._default_manager.all()
        if q:
            conds = [Q(**{c.name + "__icontains": q}) for c in rel._meta.fields
                     if c.get_internal_type() == "CharField"]
            if rel._meta.pk.get_internal_type() in ("AutoField", "BigAutoField", "SmallAutoField", "CharField"):
                # labels like "PersonBusinessEntity 42" only hold the pk (skipped when the pk is a relation)
                conds.append(Q(pk__icontains=q))
            pf = next((r.name for r in rel._meta.fields
                       if r.is_relation and r.related_model.__name__ == "Person"), None)
            if pf:
                conds += [Q(**{f"{pf}__{n}__icontains": q}) for n in ("first_name", "last_name")]
            qs = qs.filter(Q(*conds, _connector=Q.OR))
        if name_needs_joins(rel):
            qs = qs.select_related(*[fk.name for fk in rel._meta.fields if fk.is_relation])
        if rel.__name__ in LABEL_COLUMNS:
            qs = qs.only(*LABEL_COLUMNS[rel.__name__])
        return JsonResponse({"results": [{"id": o.pk, "text": str(o)} for o in qs.order_by("pk")[:20]]})


class TableDelete(TableMixin, DeleteView):
    perm, template_name = "delete", "core/confirm_delete.html"

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError as e:
            kinds = ", ".join(sorted({type(o).__name__ for o in e.protected_objects}))
            messages.error(request, f"Cannot delete: {len(e.protected_objects)} record(s) in {kinds} still point to it.")
            return redirect(request.path)
