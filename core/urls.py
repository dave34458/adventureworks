from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", login_not_required(LoginView.as_view(template_name="registration/login.html")), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("sales/", views.sales, name="sales"),
    path("customers/", views.customers, name="customers"),
    path("costs/", views.costs, name="costs"),
    path("finance/", views.finance, name="finance"),
    path("<slug:tab>/data/<str:model>/", views.TableList.as_view(), name="table_list"),
    path("<slug:tab>/data/<str:model>/autocomplete/<str:field>/", views.TableAutocomplete.as_view(), name="table_autocomplete"),
    path("<slug:tab>/data/<str:model>/<str:pk>/", views.TableDetail.as_view(), name="table_detail"),
    path("<slug:tab>/data/<str:model>/<str:pk>/edit/", views.TableEdit.as_view(), name="table_edit"),
    path("<slug:tab>/data/<str:model>/<str:pk>/delete/", views.TableDelete.as_view(), name="table_delete"),
]
