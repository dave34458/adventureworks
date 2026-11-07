"""Account and login views."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AccountForm, DepartmentUserForm, EmailAuthenticationForm
from .models import User
from .roles import DEPARTMENT_TABS
from reporting.models import AuditLog


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


def _department_scope(request):
    groups = set(request.user.groups.values_list("name", flat=True))
    department = next((name for name in DEPARTMENT_TABS if f"{name} Admin" in groups), None)
    if not department:
        raise PermissionDenied
    roles = [f"{department} {kind}" for kind in ("Manager", "Supervisor", "Employee")]
    users = User.objects.filter(groups__name__in=roles, is_superuser=False).exclude(
        groups__name__in=[f"{name} Admin" for name in DEPARTMENT_TABS]).distinct()
    return department, users


@login_required
def department_users(request):
    department, users = _department_scope(request)
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
        "department": department,
        "page_obj": page_obj, "columns": columns, "col": col,
        "sort": sort, "sort_desc": sort_desc,
        "title": f"{department} users",
    })


@login_required
def department_user_form(request, pk=None):
    department, users = _department_scope(request)
    instance = get_object_or_404(users, pk=pk) if pk is not None else User()
    if request.method == "POST":
        form = DepartmentUserForm(request.POST, instance=instance, department=department)
        if form.is_valid():
            created = instance.pk is None
            before = {
                "email": instance.email, "first_name": instance.first_name,
                "last_name": instance.last_name, "is_active": instance.is_active,
                "role": instance.groups.values_list("name", flat=True).first(),
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
        form = DepartmentUserForm(instance=instance, department=department)
    return render(request, "accounts/user_form.html", {
        "department": department, "form": form,
        "title": "Add user" if pk is None else "Edit user",
    })


@login_required
@require_POST
def department_user_deactivate(request, pk):
    department, users = _department_scope(request)
    user = get_object_or_404(users, pk=pk)
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
    department, users = _department_scope(request)
    audit_roles = [f"{department} {kind}" for kind in ("Manager", "Supervisor", "Employee", "Admin")]
    logs = AuditLog.objects.filter(user__groups__name__in=audit_roles).select_related(
        "user").distinct()
    return render(request, "accounts/audit.html", {
        "department": department, "logs": logs[:200],
        "title": f"{department} audit log",
    })


class EmailLogin(LoginView):
    """Email and password login."""

    template_name = "registration/login.html"
    form_class = EmailAuthenticationForm
    redirect_authenticated_user = True
