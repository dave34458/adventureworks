import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")


def _env_list(name, default=""):
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
RAILWAY_PRIVATE_DOMAIN = os.environ.get("RAILWAY_PRIVATE_DOMAIN", "").strip()
ON_RAILWAY = bool(RAILWAY_PUBLIC_DOMAIN or os.environ.get("RAILWAY_ENVIRONMENT"))
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_RAILWAY else "1") == "1"
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
for _host in (RAILWAY_PUBLIC_DOMAIN, RAILWAY_PRIVATE_DOMAIN):
    if _host and _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

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
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.environ.get("AW_DB_PATH", BASE_DIR / "adventureworks.sqlite3"),
}}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = False  # AdventureWorks dates are naive local times
TIME_ZONE = "UTC"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic output; served by whitenoise

# Behind a hosting proxy that terminates TLS (e.g. Railway): trust its header so
# Django knows the request is HTTPS. Needed for CSRF origin checks on login.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if RAILWAY_PUBLIC_DOMAIN:
    _origin = f"https://{RAILWAY_PUBLIC_DOMAIN}"
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

if not DEBUG:  # production behind the TLS proxy: cookies only over HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["core.auth_backends.EmailBackend"]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
