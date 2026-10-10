import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-change-before-deploy")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
CSRF_TRUSTED_ORIGINS = [s for s in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if s]
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "garage"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware", "garage.middleware.GarageMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60, conn_health_checks=True)}
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}, {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT = SESSION_COOKIE_SECURE
SECURE_REDIRECT_EXEMPT = [r"^health/(live|ready)$"]
SECURE_HSTS_SECONDS = 3600 if SESSION_COOKIE_SECURE else 0
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_BUDGET = int(os.getenv("YOUTUBE_SEARCH_BUDGET", "80"))
LOGGING = {"version": 1, "disable_existing_loggers": False, "formatters": {"json": {"()": "garage.logging.JsonFormatter"}}, "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}}, "root": {"handlers": ["console"], "level": "INFO"}}
# HTTPX logs complete request URLs at INFO; YouTube's API key is a query parameter.
LOGGING["loggers"] = {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}}

# Google is the only account provider. Legacy access is a temporary rollout switch;
# it never grants access to a garage that already has an owner.
GOOGLE_AUTH_REQUIRED = os.getenv("GOOGLE_AUTH_REQUIRED", "true").lower() == "true"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
INSTALLED_APPS += ["allauth", "allauth.account", "allauth.socialaccount", "allauth.socialaccount.providers.google"]
MIDDLEWARE.insert(MIDDLEWARE.index("garage.middleware.GarageMiddleware"), "allauth.account.middleware.AccountMiddleware")
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]
SOCIALACCOUNT_ONLY = True
SOCIALACCOUNT_ADAPTER = "garage.accounts.GoogleAccountAdapter"
ACCOUNT_ADAPTER = "garage.accounts.AccountAdapter"
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_REQUESTS_TIMEOUT = 10
ACCOUNT_EMAIL_VERIFICATION = "none"  # Verified Google email is enforced by our adapter.
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_EMAIL_NOTIFICATIONS = False
ACCOUNT_RATE_LIMITS = {}  # Public entrypoints use our shared PostgreSQL limiter.
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/accounts/welcome/"
SOCIALACCOUNT_PROVIDERS = {"google": {
    "APP": {"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET, "key": ""},
    "SCOPE": ["openid", "email", "profile"],
    "AUTH_PARAMS": {"prompt": "select_account"},
    "OAUTH_PKCE_ENABLED": True,
}}
LOGGING["loggers"]["allauth"] = {"level": "WARNING"}
