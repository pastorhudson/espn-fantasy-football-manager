import os

os.environ.setdefault("SECRET_KEY", "test-only-key")
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECURE_SSL_REDIRECT"] = "false"

from .settings import *  # noqa: E402,F403

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Static assets are covered by the separate collectstatic validation.
MIDDLEWARE = [item for item in MIDDLEWARE if item != "whitenoise.middleware.WhiteNoiseMiddleware"]  # noqa: F405

# Individual feed tests enable this with mocked HTTP; the test suite stays offline.
FREE_DATA_ENABLED = False
