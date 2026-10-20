from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Users, roles, privacy and audit"
admin.site.site_title = "Users, roles, privacy and audit"
admin.site.index_title = "Manage logins, groups, privacy and audit records (superadmin only)"

urlpatterns = [
    path("manage/", admin.site.urls),  # only User and Group are registered here
    path("", include("core.urls")),
]
