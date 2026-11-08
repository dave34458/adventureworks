import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
IS_DEPLOYMENT = bool(os.environ.get("K_SERVICE"))

if IS_DEPLOYMENT:
    SECRET_KEY = "9ca33ce9700a4e3eb8db7dbf66c78002e8c078ada0404bbc8da0db7ae4030de3"
    DEBUG = False
    ALLOWED_HOSTS = [".run.app"]
    CSRF_TRUSTED_ORIGINS = ["https://adventureworks-4cfcg3oqqq-uc.a.run.app"]
    DATABASES = {"default": {
        "ENGINE": "aw_project.db_backend",
        "NAME": "AdventureWorks2025",
        "HOST": "127.0.0.1",
        "PORT": "1433",
        "USER": "sqlserver",
        "PASSWORD": "Nov2019136027!",
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "extra_params": "TrustServerCertificate=yes",
        },
    }}
else:
    SECRET_KEY = "dev-only-change-me"
    DEBUG = True
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
    CSRF_TRUSTED_ORIGINS = []
    DATABASES = {"default": {
        "ENGINE": "aw_project.db_backend",
        "NAME": "AdventureWorks2025",
        "HOST": "localhost",
        "PORT": "",
        "USER": "",
        "PASSWORD": "",
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "extra_params": "TrustServerCertificate=yes;Trusted_Connection=yes",
        },
    }}

INSTALLED_APPS = [
    "django.contrib.admin",  # used only for the superadmin's Users and Groups pages
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "reporting",
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
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = False  # AdventureWorks dates are naive local times
TIME_ZONE = "UTC"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic output; served by whitenoise

# Cloud Run terminates TLS and forwards X-Forwarded-Proto. Trust it so Django
# knows the request is HTTPS, which the login CSRF origin check needs.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:  # production behind the TLS proxy: cookies only over HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.auth_backends.EmailBackend"]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
