from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Users, roles, privacy and audit"
admin.site.site_title = "Users, roles, privacy and audit"
admin.site.index_title = "Manage logins, groups, privacy and audit records (Administrator only)"

urlpatterns = [
    path("manage/", admin.site.urls),  # users, groups, privacy and audit
    path("", include("core.urls")),
]
