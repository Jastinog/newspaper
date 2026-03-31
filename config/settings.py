import os
from datetime import timedelta
from pathlib import Path

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the repo root
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-me-in-production-abc123xyz",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.postgres",
    "rest_framework",
    "apps.core",
    "apps.location",
    "apps.feed",
    "apps.digest",
    "apps.research",
    "apps.billing",
    "apps.harvester",
    "apps.analytics",
    "apps.websocket",
    "apps.account",
    "apps.telegram",
]

AUTH_USER_MODEL = "account.User"

ASGI_APPLICATION = "config.asgi.application"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.feed.middleware.GeoLanguageMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.analytics.middleware.BotTrackingMiddleware",
    "apps.feed.middleware.Redirect404Middleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "newspaper"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "IWHsdBhB0eee0LZMU7BU"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("ru", "Русский"),
    ("uk", "Українська"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "config.storage.NonStrictManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Image download settings
IMAGE_MAX_WIDTH = 400
IMAGE_QUALITY = 85

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("CACHE_REDIS_URL", "redis://127.0.0.1:6379/2"),
        "TIMEOUT": 3600,
    }
}

# Analytics — path to MaxMind GeoLite2-City.mmdb (optional)
GEOIP_DATABASE_PATH = os.environ.get("GEOIP_DATABASE_PATH", str(BASE_DIR / "data" / "GeoLite2-City.mmdb"))

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")

# Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Europe/Kyiv"
CELERY_BEAT_SCHEDULE = {
    "telegram-publish-next": {
        "task": "telegram.publish_next",
        "schedule": timedelta(minutes=15),
    },
}

UNFOLD = {
    "SITE_TITLE": "Newspaper",
    "SITE_HEADER": "Newspaper",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "BORDER_RADIUS": "6px",
    "DASHBOARD_CALLBACK": "apps.billing.dashboard.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "oklch(97.5% .008 75)",
            "100": "oklch(94% .02 75)",
            "200": "oklch(88% .04 70)",
            "300": "oklch(80% .07 65)",
            "400": "oklch(72% .11 55)",
            "500": "oklch(62% .14 50)",
            "600": "oklch(53% .13 45)",
            "700": "oklch(45% .11 42)",
            "800": "oklch(38% .08 40)",
            "900": "oklch(30% .06 40)",
            "950": "oklch(22% .04 40)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Main"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                ],
            },
            {
                "title": _("Content"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Feeds"),
                        "icon": "rss_feed",
                        "link": reverse_lazy("admin:feed_feed_changelist"),
                    },
                    {
                        "title": _("Categories"),
                        "icon": "category",
                        "link": reverse_lazy("admin:feed_category_changelist"),
                    },
                    {
                        "title": _("Articles"),
                        "icon": "article",
                        "link": reverse_lazy("admin:feed_article_changelist"),
                    },
                    {
                        "title": _("Article chunks"),
                        "icon": "segment",
                        "link": reverse_lazy("admin:feed_articlechunk_changelist"),
                    },
                    {
                        "title": _("Article images"),
                        "icon": "image",
                        "link": reverse_lazy("admin:feed_articleimage_changelist"),
                    },
                    {
                        "title": _("Image sources"),
                        "icon": "source",
                        "link": reverse_lazy("admin:feed_articleimagesource_changelist"),
                    },
                ],
            },
            {
                "title": _("Digests"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Digests"),
                        "icon": "auto_stories",
                        "link": reverse_lazy("admin:digest_digest_changelist"),
                    },
                    {
                        "title": _("Sections"),
                        "icon": "view_list",
                        "link": reverse_lazy("admin:digest_digestsection_changelist"),
                    },
                    {
                        "title": _("Config"),
                        "icon": "tune",
                        "link": reverse_lazy("admin:digest_digestconfig_changelist"),
                    },
                ],
            },
            {
                "title": _("Research"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Researches"),
                        "icon": "science",
                        "link": reverse_lazy("admin:research_research_changelist"),
                    },
                ],
            },
            {
                "title": _("Telegram"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Channels"),
                        "icon": "send",
                        "link": reverse_lazy("admin:telegram_telegramchannel_changelist"),
                    },
                    {
                        "title": _("Post log"),
                        "icon": "history",
                        "link": reverse_lazy("admin:telegram_telegrampost_changelist"),
                    },
                ],
            },
            {
                "title": _("Harvester"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "monitoring",
                        "link": reverse_lazy("harvester_dashboard"),
                    },
                    {
                        "title": _("Pipeline settings"),
                        "icon": "tune",
                        "link": reverse_lazy("admin:harvester_pipelinesettings_changelist"),
                    },
                    {
                        "title": _("Feed fetches"),
                        "icon": "rss_feed",
                        "link": reverse_lazy("admin:harvester_harvesterfeed_changelist"),
                    },
                    {
                        "title": _("Content extracts"),
                        "icon": "article",
                        "link": reverse_lazy("admin:harvester_harvestercontent_changelist"),
                    },
                    {
                        "title": _("Image downloads"),
                        "icon": "download",
                        "link": reverse_lazy("admin:harvester_harvesterimage_changelist"),
                    },
                    {
                        "title": _("Embeds"),
                        "icon": "hub",
                        "link": reverse_lazy("admin:harvester_harvesterembedding_changelist"),
                    },
                ],
            },
            {
                "title": _("Analytics"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "monitoring",
                        "link": reverse_lazy("analytics_dashboard"),
                    },
                    {
                        "title": _("Clients"),
                        "icon": "devices",
                        "link": reverse_lazy("admin:analytics_client_changelist"),
                    },
                    {
                        "title": _("Sessions"),
                        "icon": "timer",
                        "link": reverse_lazy("admin:analytics_session_changelist"),
                    },
                    {
                        "title": _("Activities"),
                        "icon": "touch_app",
                        "link": reverse_lazy("admin:analytics_activity_changelist"),
                    },
                ],
            },
            {
                "title": _("System"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:account_user_changelist"),
                    },
                    {
                        "title": _("Languages"),
                        "icon": "translate",
                        "link": reverse_lazy("admin:core_language_changelist"),
                    },
                    {
                        "title": _("Regions"),
                        "icon": "public",
                        "link": reverse_lazy("admin:location_region_changelist"),
                    },
                    {
                        "title": _("Countries"),
                        "icon": "flag",
                        "link": reverse_lazy("admin:location_country_changelist"),
                    },
                    {
                        "title": _("API usage"),
                        "icon": "data_usage",
                        "link": reverse_lazy("admin:billing_apiusage_changelist"),
                    },
                ],
            },
        ],
    },
}

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 30,
}
