"""Account and login views."""
import json

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from reporting.models import AuditLog

from .forms import AccountForm, DepartmentUserForm, EmailAuthenticationForm
from .models import User
from .roles import ADMIN_ROLE, DEPARTMENT_TABS, ROLE_CHOICES, ROLE_KINDS


@login_required
def account(request):
    """Let a signed-in user edit their own name and password."""
    if request.method == "POST":
        before = {"first_name": request.user.first_name, "last_name": request.user.last_name}
        form = AccountForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
            changes = {key: [old, getattr(user, key)] for key, old in before.items()
                       if old != getattr(user, key)}
            if form.cleaned_data["new_password1"]:
                changes["password"] = ["unchanged", "changed"]
            if changes:
                AuditLog.objects.create(
                    user=request.user, username=request.user.get_username(), action="update",
                    model="User", object_pk=str(user.pk), object_repr=user.email,
                    changes=changes, ip_address=request.META.get("REMOTE_ADDR"))
            update_session_auth_hash(request, user)
            messages.success(request, "Account updated.")
            return redirect("account")
    else:
        form = AccountForm(instance=request.user)
    return render(request, "accounts/account.html", {"form": form, "title": "Account"})


@login_required
def department_users(request):
    global_view = request.user.is_superuser
    if global_view:
        department, users = "All departments", User.objects.all()
    else:
        group_names = set(request.user.groups.values_list("name", flat=True))
        department = next(
            (name for name in DEPARTMENT_TABS if f"{name} Admin" in group_names), None)
        if not department:
            raise PermissionDenied
        roles = [f"{department} {kind}" for kind in ("Manager", "Supervisor", "Employee")]
        users = User.objects.filter(groups__name__in=roles, is_superuser=False).exclude(
            groups__name__in=[f"{name} Admin" for name in DEPARTMENT_TABS]).distinct()
    columns = [("Email", "email"), ("First name", "first_name"),
               ("Last name", "last_name"), ("Role", "role"), ("Status", "status")]
    q, col = request.GET.get("q", "").strip(), request.GET.get("col", "")
    if q:
        fields = {"email": Q(email__icontains=q), "first_name": Q(first_name__icontains=q),
                  "last_name": Q(last_name__icontains=q), "role": Q(groups__name__icontains=q)}
        if col in fields:
            users = users.filter(fields[col])
        elif col == "status":
            if q.lower() in ("active", "inactive"):
                users = users.filter(is_active=(q.lower() == "active"))
            else:
                users = users.none()
        else:
            condition = fields["email"] | fields["first_name"] | fields["last_name"] | fields["role"]
            if q.lower() in ("active", "inactive"):
                condition |= Q(is_active=(q.lower() == "active"))
            users = users.filter(condition)
    sort = request.GET.get("sort", "")
    sort_desc = sort.startswith("-")
    sort = sort.removeprefix("-")
    sort_fields = {"email": "email", "first_name": "first_name", "last_name": "last_name",
                   "role": "groups__name", "status": "is_active"}
    if sort not in sort_fields:
        sort, sort_desc = "", False
    sort_field = sort_fields.get(sort, "email")
    page_obj = Paginator(users.order_by(("-" if sort_desc else "") + sort_field, "pk").distinct(), 50).get_page(
        request.GET.get("page"))
    return render(request, "accounts/users.html", {
        "department": department, "global_view": global_view,
        "page_obj": page_obj, "columns": columns, "col": col,
        "sort": sort, "sort_desc": sort_desc,
        "title": "All users" if global_view else f"{department} users",
    })


@login_required
def department_user_form(request, pk=None):
    if request.user.is_superuser:
        department, roles = "All departments", ROLE_CHOICES
        instance = get_object_or_404(User, pk=pk) if pk is not None else User()
    else:
        group_names = set(request.user.groups.values_list("name", flat=True))
        department = next(
            (name for name in DEPARTMENT_TABS if f"{name} Admin" in group_names), None)
        if not department:
            raise PermissionDenied
        roles = [(f"{department} {kind}", kind)
                 for kind in ("Manager", "Supervisor", "Employee")]
        users = User.objects.filter(
            groups__name__in=[role for role, _ in roles], is_superuser=False).exclude(
                groups__name__in=[f"{name} Admin" for name in DEPARTMENT_TABS]).distinct()
        instance = get_object_or_404(users, pk=pk) if pk is not None else User()
    if request.method == "POST":
        form = DepartmentUserForm(
            request.POST, instance=instance, department=department, roles=roles)
        if form.is_valid():
            created = instance.pk is None
            before = {
                "email": instance.email, "first_name": instance.first_name,
                "last_name": instance.last_name, "is_active": instance.is_active,
                "role": (ADMIN_ROLE if instance.is_superuser else
                         instance.groups.values_list("name", flat=True).first()),
            } if not created else {}
            user = form.save()
            after = {
                "email": user.email, "first_name": user.first_name,
                "last_name": user.last_name, "is_active": user.is_active,
                "role": form.cleaned_data["role"],
            }
            changes = ({key: [before.get(key), value] for key, value in after.items()}
                       if created else {
                           key: [before[key], value] for key, value in after.items()
                           if before[key] != value
                       })
            if form.cleaned_data["password"]:
                changes["password"] = ["not set", "set"] if created else ["unchanged", "changed"]
            AuditLog.objects.create(
                user=request.user, username=request.user.get_username(),
                action="create" if created else "update", model="User",
                object_pk=str(user.pk), object_repr=user.email, changes=changes,
                ip_address=request.META.get("REMOTE_ADDR"))
            messages.success(request, f"Saved {user.email}.")
            return redirect("department_users")
    else:
        form = DepartmentUserForm(instance=instance, department=department, roles=roles)
    return render(request, "accounts/user_form.html", {
        "department": department, "form": form,
        "title": "Add user" if pk is None else "Edit user",
    })


@login_required
def department_user_deactivate(request, pk):
    if request.user.is_superuser:
        user = get_object_or_404(User, pk=pk)
    else:
        group_names = set(request.user.groups.values_list("name", flat=True))
        department = next(
            (name for name in DEPARTMENT_TABS if f"{name} Admin" in group_names), None)
        if not department:
            raise PermissionDenied
        roles = [f"{department} {kind}" for kind in ("Manager", "Supervisor", "Employee")]
        users = User.objects.filter(groups__name__in=roles, is_superuser=False).exclude(
            groups__name__in=[f"{name} Admin" for name in DEPARTMENT_TABS]).distinct()
        user = get_object_or_404(users, pk=pk)
    if request.method == "GET":
        return render(request, "accounts/user_deactivate_confirm.html", {
            "account": user, "title": "Deactivate user",
        })
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    if user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])
        AuditLog.objects.create(
            user=request.user, username=request.user.get_username(), action="update",
            model="User", object_pk=str(user.pk), object_repr=user.email,
            changes={"is_active": [True, False]},
            ip_address=request.META.get("REMOTE_ADDR"))
    messages.success(request, f"Deactivated {user.email}.")
    return redirect("department_users")


@login_required
def department_audit(request):
    if request.user.is_superuser:
        department, logs = "All departments", AuditLog.objects.select_related("user")
    else:
        group_names = set(request.user.groups.values_list("name", flat=True))
        department = next(
            (name for name in DEPARTMENT_TABS if f"{name} Admin" in group_names), None)
        if not department:
            raise PermissionDenied
        audit_roles = [f"{department} {kind}" for kind in
                       ("Manager", "Supervisor", "Employee", "Admin")]
        logs = AuditLog.objects.filter(
            user__groups__name__in=audit_roles).select_related("user").distinct()
    columns = [("When", "created_at"), ("User", "username"), ("Action", "action"),
               ("Record", "object_repr"), ("Changes", "changes")]
    query, col = request.GET.get("q", "").strip(), request.GET.get("col", "")
    if query:
        fields = {
            "created_at": Q(created_at__icontains=query),
            "username": Q(username__icontains=query),
            "action": Q(action__icontains=query),
            "object_repr": (Q(model__icontains=query) | Q(object_pk__icontains=query)
                            | Q(object_repr__icontains=query)),
            "changes": Q(changes__icontains=query),
        }
        logs = logs.filter(fields[col]) if col in fields else logs.filter(
            Q(*fields.values(), _connector=Q.OR))
    sort = request.GET.get("sort", "-created_at")
    if sort not in {"created_at", "-created_at", "username", "-username",
                    "action", "-action", "object_repr", "-object_repr"}:
        sort = "-created_at"
    logs = logs.order_by(sort, "-created_at")
    page_obj = Paginator(logs, 50).get_page(request.GET.get("page"))
    for log in page_obj:
        log.changes_pretty = json.dumps(log.changes, indent=2, ensure_ascii=False, default=str)
    return render(request, "accounts/audit.html", {
        "department": department, "page_obj": page_obj, "columns": columns,
        "query": query, "col": col, "sort": sort,
        "title": f"{department} audit log",
    })


@login_required
def department_audit_detail(request, pk):
    if request.user.is_superuser:
        log = get_object_or_404(AuditLog, pk=pk)
    else:
        group_names = set(request.user.groups.values_list("name", flat=True))
        department = next(
            (name for name in DEPARTMENT_TABS if f"{name} Admin" in group_names), None)
        if not department:
            raise PermissionDenied
        audit_roles = [f"{department} {kind}" for kind in
                       ("Manager", "Supervisor", "Employee", "Admin")]
        log = get_object_or_404(
            AuditLog.objects.filter(user__groups__name__in=audit_roles).distinct(), pk=pk)
    return render(request, "accounts/audit_detail.html", {
        "log": log,
        "changes_pretty": json.dumps(log.changes, indent=2, ensure_ascii=False, default=str),
        "title": "Audit record",
    })


@login_required
def group_permissions(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    groups = Group.objects.all().annotate(
        permission_count=Count("permissions")).order_by("name")
    return render(request, "accounts/group_permissions.html", {
        "groups": groups, "title": "Manage Permissions",
    })


@login_required
def group_permission_edit(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    permissions = Permission.objects.filter(
        content_type__app_label__in=("core", "reporting")).select_related(
            "content_type").order_by(
                "content_type__app_label", "content_type__model", "codename")
    group = get_object_or_404(Group, pk=pk)

    editable_ids = set(permissions.values_list("pk", flat=True))
    if request.method == "POST":
        selected_ids = {
            int(value) for value in request.POST.getlist("permissions") if value.isdigit()
        } & editable_ids
        unmanaged_ids = set(group.permissions.exclude(pk__in=editable_ids).values_list(
            "pk", flat=True))
        before = {
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in group.permissions.filter(
                pk__in=editable_ids).select_related("content_type")
        }
        group.permissions.set(unmanaged_ids | selected_ids)
        after = {
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in group.permissions.filter(
                pk__in=editable_ids).select_related("content_type")
        }
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            AuditLog.objects.create(
                user=request.user, username=request.user.get_username(), action="update",
                model="Group", object_pk=str(group.pk), object_repr=group.name,
                changes={"permissions": {"added": added, "removed": removed}},
                ip_address=request.META.get("REMOTE_ADDR"))
        messages.success(request, f"Saved permissions for {group.name}.")
        return redirect("group_permission_edit", pk=group.pk)

    selected = set(group.permissions.values_list("pk", flat=True))
    permission_groups = []
    for permission in permissions:
        key = (permission.content_type.app_label, permission.content_type.model)
        if not permission_groups or permission_groups[-1]["key"] != key:
            permission_groups.append({
                "key": key,
                "label": f"{permission.content_type.app_label} · {permission.content_type.name}",
                "permissions": [],
                "selected_count": 0,
            })
        is_selected = permission.pk in selected
        permission_groups[-1]["permissions"].append({
            "permission": permission, "selected": is_selected,
        })
        if is_selected:
            permission_groups[-1]["selected_count"] += 1
    locked = group.permissions.exclude(pk__in=editable_ids).values_list("name", flat=True)
    return render(request, "accounts/group_permission_form.html", {
        "group": group, "permission_groups": permission_groups,
        "locked_permissions": locked, "title": f"{group.name} permissions",
    })


class EmailLogin(LoginView):
    """Email and password login."""

    template_name = "registration/login.html"
    form_class = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        demo_emails = {"admin@example.com"}
        role_emails = {}
        for department in DEPARTMENT_TABS:
            for kind in ROLE_KINDS:
                role = f"{department} {kind}"
                email = f"{role.lower().replace(' and ', ' ').replace(' ', '.')}@example.com"
                demo_emails.add(email)
                role_emails[(department, kind)] = email

        users = {
            user.email.lower(): user
            for user in User.objects.filter(email__in=demo_emails, is_active=True)
        }
        demo_levels = ("Admin", *(kind for kind in ROLE_KINDS if kind != "Admin"))
        context["demo_admin"] = users.get("admin@example.com")
        context["role_kinds"] = demo_levels
        context["demo_matrix"] = [
            {
                "department": department,
                "roles": [
                    {
                        "kind": kind,
                        "user": users.get(role_emails[(department, kind)]),
                        "email": role_emails[(department, kind)],
                        "password": role_emails[(department, kind)].split("@")[0],
                    }
                    for kind in demo_levels
                ],
            }
            for department in DEPARTMENT_TABS
        ]
        return context
