from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import crud_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", login_not_required(LoginView.as_view(template_name="registration/login.html")), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("<slug:tab>/", views.Dashboard.as_view(), name="dashboard"),
    path("<slug:tab>/data/<str:model>/", crud_views.TableList.as_view(), name="table_list"),
    path("<slug:tab>/data/<str:model>/autocomplete/<str:field>/", crud_views.TableAutocomplete.as_view(), name="table_autocomplete"),
    path("<slug:tab>/data/<str:model>/<str:pk>/", crud_views.TableDetail.as_view(), name="table_detail"),
    path("<slug:tab>/data/<str:model>/<str:pk>/edit/", crud_views.TableEdit.as_view(), name="table_edit"),
    path("<slug:tab>/data/<str:model>/<str:pk>/delete/", crud_views.TableDelete.as_view(), name="table_delete"),
]
