from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Users and roles"
admin.site.site_title = "Users and roles"
admin.site.index_title = "Manage logins and groups (superadmin only)"

urlpatterns = [
    path("manage/", admin.site.urls),  # only User and Group are registered here
    path("", include("core.urls")),
]
