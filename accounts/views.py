"""Account and login views."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .forms import AccountForm, EmailAuthenticationForm


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
    return render(request, "accounts/account.html", {"form": form, "title": "Account"})


class EmailLogin(LoginView):
    """Email and password login."""

    template_name = "registration/login.html"
    form_class = EmailAuthenticationForm
