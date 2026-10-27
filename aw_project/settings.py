import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")


def _env_list(name, default=""):
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


CLOUD_RUN_SERVICE = os.environ.get("K_SERVICE", "").strip()
ON_CLOUD_RUN = bool(CLOUD_RUN_SERVICE)
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_CLOUD_RUN else "1") == "1"
ALLOWED_HOSTS = _env_list(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,.run.app")

INSTALLED_APPS = [
    "django.contrib.admin",  # used only for the superadmin's Users and Groups pages
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves collectstatic files in production
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",  # every page needs a login except the login page
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "aw_project.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "aw_project.wsgi.application"
_mssql_port = os.environ.get("MSSQL_PORT", "none").strip()
if _mssql_port.lower() in ("", "none", "0"):
    _mssql_port = ""
DATABASES = {"default": {
    "ENGINE": "mssql",
    "NAME": os.environ.get("MSSQL_DATABASE", "AdventureWorks2025"),
    "HOST": os.environ.get("MSSQL_HOST", "localhost"),
    "PORT": _mssql_port,
    "USER": os.environ.get("MSSQL_USER", ""),
    "PASSWORD": os.environ.get("MSSQL_PASSWORD", ""),
    "OPTIONS": {
        "driver": os.environ.get("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server"),
        "extra_params": "TrustServerCertificate=yes",
    },
}}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = False  # AdventureWorks dates are naive local times
TIME_ZONE = "UTC"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic output; served by whitenoise

# Cloud Run terminates TLS and forwards X-Forwarded-Proto. Trust it so Django
# knows the request is HTTPS, which the login CSRF origin check needs.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if not DEBUG:  # production behind the TLS proxy: cookies only over HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["core.auth_backends.EmailBackend"]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
