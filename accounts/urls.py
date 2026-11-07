from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", login_not_required(views.EmailLogin.as_view()), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("users/", views.department_users, name="department_users"),
    path("users/add/", views.department_user_form, name="department_user_add"),
    path("users/<int:pk>/", views.department_user_form, name="department_user_edit"),
    path("users/<int:pk>/deactivate/", views.department_user_deactivate,
         name="department_user_deactivate"),
    path("users/audit/", views.department_audit, name="department_audit"),
]
