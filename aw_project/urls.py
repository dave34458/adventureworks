from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Users, roles and privacy"
admin.site.site_title = "Users, roles and privacy"
admin.site.index_title = "Manage logins, groups and privacy records (superadmin only)"

urlpatterns = [
    path("manage/", admin.site.urls),  # only User and Group are registered here
    path("", include("core.urls")),
]
