from pathlib import Path
import os
from datetime import timedelta


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "docmaster-dev-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "documents",
    "audit",
    "integrations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "config.middleware.DesktopRefererMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("MYSQL_DATABASE"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("MYSQL_DATABASE"),
            "USER": os.getenv("MYSQL_USER", "root"),
            "PASSWORD": os.getenv("MYSQL_PASSWORD", ""),
            "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.getenv("TZ", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.SingleSessionJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SIMPLE_JWT = {
    "AUTH_HEADER_TYPES": ("Bearer",),
    # Short access token + refresh token for web portal.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "7"))),
}

CORS_ALLOWED_ORIGINS = [
    origin
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin
]
CORS_ALLOW_CREDENTIALS = False

DOCMASTER_STORAGE_ROOT = Path(os.getenv("DOCMASTER_STORAGE_ROOT", BASE_DIR / "runtime"))
DOCMASTER_LOCAL_TRASH_ROOT = DOCMASTER_STORAGE_ROOT / "local_trash"
DOCMASTER_SHARED_ROOT = DOCMASTER_STORAGE_ROOT / "shared"
DOCMASTER_EXPORT_ROOT = DOCMASTER_STORAGE_ROOT / "exports"
DOCMASTER_PERSONAL_SESSION_ROOT = DOCMASTER_STORAGE_ROOT / "personal_sessions"
DOCMASTER_ONLYOFFICE_URL = os.getenv("DOCMASTER_ONLYOFFICE_URL", "")
DOCMASTER_ONLYOFFICE_JWT_SECRET = os.getenv("DOCMASTER_ONLYOFFICE_JWT_SECRET", "")
DOCMASTER_ONLYOFFICE_VERIFY_SSL = os.getenv("DOCMASTER_ONLYOFFICE_VERIFY_SSL", "1") == "1"
DOCMASTER_COS_BUCKET = os.getenv("DOCMASTER_COS_BUCKET", "")
DOCMASTER_COS_REGION = os.getenv("DOCMASTER_COS_REGION", "")
DOCMASTER_COS_ENABLED = all(
    [
        DOCMASTER_COS_BUCKET,
        DOCMASTER_COS_REGION,
        os.getenv("TENCENT_SECRET_ID", ""),
        os.getenv("TENCENT_SECRET_KEY", ""),
    ]
)
DOCMASTER_TENCENT_SECRET_ID = os.getenv("TENCENT_SECRET_ID", "")
DOCMASTER_TENCENT_SECRET_KEY = os.getenv("TENCENT_SECRET_KEY", "")
DOCMASTER_DESKTOP_ALLOWED_ORIGIN = os.getenv("DOCMASTER_DESKTOP_ALLOWED_ORIGIN", "").strip()
DOCMASTER_DEFAULT_ADMIN_PASSWORD = os.getenv("DOCMASTER_DEFAULT_ADMIN_PASSWORD", "Docmstr1")

for path in (
    DOCMASTER_STORAGE_ROOT,
    DOCMASTER_LOCAL_TRASH_ROOT,
    DOCMASTER_SHARED_ROOT,
    DOCMASTER_EXPORT_ROOT,
    DOCMASTER_PERSONAL_SESSION_ROOT,
):
    path.mkdir(parents=True, exist_ok=True)
