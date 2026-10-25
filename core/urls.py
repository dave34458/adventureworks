from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("privacy/", views.privacy, name="privacy"),
    path("login/", login_not_required(views.EmailLogin.as_view()), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("sales/", views.sales, name="sales"),
    path("customer-profile/", views.customer_profile, name="customer-profile"),
    path("revenue-and-loss/", views.revenue_and_loss, name="revenue-and-loss"),
    path("cost/", views.cost, name="cost"),
    path("<slug:tab>/report/generate/", views.report_generate, name="report_generate"),
    path("<slug:tab>/reports/", views.SnapshotList.as_view(), name="snapshot_list"),
    path("<slug:tab>/reports/<int:pk>/edit/", views.SnapshotEdit.as_view(), name="snapshot_edit"),
    path("<slug:tab>/reports/<int:pk>/delete/", views.SnapshotDelete.as_view(), name="snapshot_delete"),
    path("<slug:tab>/data/<str:model>/", views.TableList.as_view(), name="table_list"),
    path("<slug:tab>/data/<str:model>/autocomplete/<str:field>/", views.TableAutocomplete.as_view(), name="table_autocomplete"),
    path("<slug:tab>/data/<str:model>/<str:pk>/", views.TableDetail.as_view(), name="table_detail"),
    path("<slug:tab>/data/<str:model>/<str:pk>/edit/", views.TableEdit.as_view(), name="table_edit"),
    path("<slug:tab>/data/<str:model>/<str:pk>/delete/", views.TableDelete.as_view(), name="table_delete"),
]
