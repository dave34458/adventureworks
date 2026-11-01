from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", login_not_required(views.EmailLogin.as_view()), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
]
