"""HTTP views for the dashboard, reports, saved-report editor, table browser, and account."""
from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import (
    login_not_required,
    login_required,
    permission_required,
)
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import FieldDoesNotExist
from django.db.models import ProtectedError, Q, TextField
from django.db.models.functions import Cast
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from . import services
from .constants import LABEL_COLUMNS
from .forms import AccountForm, EmailAuthenticationForm, ReportEditForm
from .models import PRIVACY_NOTICE_VERSION, AuditLog, Report
from .services import REPORT_VIEWS, cell, name_needs_joins, shown
from .utils import metric
from .widgets import SearchSelect


def _respond(request, result):
    if result.redirect_to:
        return redirect(result.redirect_to)
    return render(request, result.template, result.context)


def home(request):
    """Open the central dashboard, or explain that the user has no report access."""
    if any(request.user.has_perm(f"core.access_{slug.replace('-', '_')}")
           for slug in REPORT_VIEWS):
        return redirect("dashboard")
    return render(request, "core/no_access.html")


@login_not_required
def privacy(request):
    """The public data privacy notice (RA 10173), linked from the footer and the login form."""
    return render(request, "core/privacy.html",
                  {"title": "Data privacy notice", "version": PRIVACY_NOTICE_VERSION})


@login_required
def account(request):
    """Let a signed-in user edit their own name and password."""
    if request.method == "POST":
        form = AccountForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Account updated.")
            return redirect("account")
    else:
        form = AccountForm(instance=request.user)
    return render(request, "core/account.html", {"form": form, "title": "Account"})


class EmailLogin(LoginView):
    """Email and password login."""

    template_name = "registration/login.html"
    form_class = EmailAuthenticationForm


@login_required
def dashboard(request):
    return _respond(request, services.dashboard(request))


@permission_required("core.access_sales", raise_exception=True)
def sales(request):
    return _respond(request, services.sales(request))


@permission_required("core.access_customer_profile", raise_exception=True)
def customer_profile(request):
    return _respond(request, services.customer_profile(request))


@permission_required("core.access_revenue_and_loss", raise_exception=True)
def revenue_and_loss(request):
    return _respond(request, services.revenue_and_loss(request))


@permission_required("core.access_cost", raise_exception=True)
def cost(request):
    return _respond(request, services.cost(request))


@require_POST
def report_generate(request, tab):
    return _respond(request, services.report_generate(request, tab))


class SnapshotMixin(PermissionRequiredMixin):
    perm = None
    page_title = "Saved reports"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.tab = kwargs["tab"]
        if self.tab not in REPORT_VIEWS:
            raise Http404
        self.model = Report

    def get_permission_required(self):
        required = [f"core.access_{self.tab.replace('-', '_')}"]
        if self.perm:
            required.append(f"core.{self.perm}_report")
        return required

    def get_success_url(self):
        return reverse("snapshot_list", args=[self.tab])

    def get_context_data(self, **kw):
        user = self.request.user
        return super().get_context_data(
            tab=self.tab, title=self.page_title,
            can_change=user.has_perm("core.change_report"),
            can_delete=user.has_perm("core.delete_report"), **kw)


class SnapshotList(SnapshotMixin, ListView):
    page_title = "Saved reports"
    template_name = "core/snapshot_list.html"
    context_object_name = "snapshots"
    paginate_by = 50

    def get_queryset(self):
        return self.model._default_manager.filter(module=self.tab)

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        rows, headers = [], []
        for snapshot in ctx["object_list"]:
            kpis = (snapshot.payload or {}).get("kpis", [])
            if not headers:
                headers = [kpi.get("label", "") for kpi in kpis]
            rows.append({
                "snapshot": snapshot,
                "cells": [metric(kpi.get("value"), kpi.get("value_kind", "count"))
                          for kpi in kpis],
            })
        ctx["rows"] = rows
        ctx["kpi_headers"] = headers
        return ctx


class SnapshotEdit(SnapshotMixin, UpdateView):
    perm = "change"
    page_title = "Edit saved report"
    template_name = "core/snapshot_form.html"
    context_object_name = "snapshot"

    def get_form_class(self):
        return ReportEditForm

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["editor_sections"] = services.editor_sections(
            self.tab, self.object.payload or {})
        return ctx

    def form_valid(self, form):
        old = self.model._default_manager.filter(pk=self.object.pk).first()
        payload, errors = services.apply_editor(
            self.tab, self.object.payload or {}, self.request.POST)
        if errors:
            for message in dict.fromkeys(errors):
                form.add_error(None, message)
            return self.form_invalid(form)

        changes = {}
        if old is not None:
            for field in form.changed_data:
                before = getattr(old, field)
                after = form.cleaned_data.get(field)
                changes[field] = [
                    str(before) if before is not None else None,
                    str(after) if after is not None else None,
                ]
            if payload != old.payload:
                changes["payload"] = ["edited", "edited"]

        form.instance.payload = payload
        messages.success(self.request, f"Saved {form.instance}.")
        response = super().form_valid(form)
        if changes:
            AuditLog.objects.create(
                user=self.request.user, username=self.request.user.get_username(),
                action="update", model=self.model.__name__,
                object_pk=str(form.instance.pk), object_repr=str(form.instance)[:255],
                changes=changes, ip_address=self.request.META.get("REMOTE_ADDR"))
        return response


class SnapshotDelete(SnapshotMixin, DeleteView):
    perm = "delete"
    page_title = "Delete saved report"
    template_name = "core/snapshot_confirm_delete.html"
    context_object_name = "snapshot"

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        audit = {
            f.name: str(getattr(obj, f.name)) if getattr(obj, f.name) is not None else None
            for f in shown(self.model) if f.name != "payload"
        }
        pk, repr_ = str(obj.pk), str(obj)[:255]
        response = super().post(request, *args, **kwargs)
        AuditLog.objects.create(
            user=request.user, username=request.user.get_username(), action="delete",
            model=self.model.__name__, object_pk=pk, object_repr=repr_, changes=audit,
            ip_address=request.META.get("REMOTE_ADDR"))
        return response


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
        return [f"core.access_{self.tab.replace('-', '_')}", f"core.{self.perm}_{self.model._meta.model_name}"]

    def get_success_url(self):
        return reverse("table_list", args=[self.tab, self.model.__name__])

    def get_context_data(self, **kw):
        user, label = self.request.user, self.model._meta.model_name
        return super().get_context_data(
            tab=self.tab, name=self.model.__name__, title=self.model._meta.verbose_name.capitalize(),
            can_change=user.has_perm(f"core.change_{label}"), can_delete=user.has_perm(f"core.delete_{label}"), **kw)


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
        name = sort.removeprefix("-")
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
        ctx["columns"] = [(f.verbose_name, f.name) for f in fields
                          if f.get_internal_type() != "BooleanField"]
        ctx["col"] = self.request.GET.get("col", "")
        ctx["sort"], ctx["sort_desc"] = sort.lstrip("-"), sort.startswith("-")
        return ctx


class TableDetail(TableMixin, DetailView):
    perm, template_name = "view", "core/detail.html"

    def get_context_data(self, **kw):
        return super().get_context_data(
            fields=[(f.verbose_name, cell(self.object, f, self.tab))
                    for f in shown(self.model)], **kw)


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
                widget.queryset = qs
                widget.url = reverse("table_autocomplete", args=[self.tab, self.model.__name__, name])
                field.widget = widget
                field.queryset = qs
        return form

    def form_valid(self, form):
        old = self.model._default_manager.filter(pk=form.instance.pk).first()  # the row as stored
        changes = {}
        for f in (self.model._meta.fields if old is not None else []):
            if not f.editable or f.primary_key or f.name == "modified_date":
                continue
            before, after = getattr(old, f.name), form.cleaned_data[f.name]
            if getattr(before, "pk", before) != getattr(after, "pk", after):
                changes[f.name] = [str(before) if before is not None else None,
                                   str(after) if after is not None else None]
        if hasattr(form.instance, "modified_date"):
            form.instance.modified_date = timezone.now()
        messages.success(self.request, f"Saved {form.instance}.")
        response = super().form_valid(form)
        if changes:  # audit trail: only a save that really changed something is recorded
            AuditLog.objects.create(
                user=self.request.user, username=self.request.user.get_username(),
                action="update", model=self.model.__name__, object_pk=str(form.instance.pk),
                object_repr=str(form.instance)[:255], changes=changes,
                ip_address=self.request.META.get("REMOTE_ADDR"))
        return response


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
        obj = self.get_object()
        snapshot = {f.name: str(getattr(obj, f.name)) if getattr(obj, f.name) is not None else None
                    for f in shown(self.model)}
        pk, repr_ = str(obj.pk), str(obj)[:255]
        try:
            response = super().post(request, *args, **kwargs)
        except ProtectedError as e:
            kinds = ", ".join(sorted({type(o).__name__ for o in e.protected_objects}))
            messages.error(request, f"Cannot delete: {len(e.protected_objects)} record(s) in {kinds} still point to it.")
            return redirect(request.path)
        AuditLog.objects.create(  # audit trail: the row is gone, so the snapshot is the evidence
            user=request.user, username=request.user.get_username(), action="delete",
            model=self.model.__name__, object_pk=pk, object_repr=repr_, changes=snapshot,
            ip_address=request.META.get("REMOTE_ADDR"))
        return response
