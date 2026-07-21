import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class NonStrictManifestStaticFilesStorage(ManifestStaticFilesStorage):
    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name

    def url(self, name, force=False):
        """In production the URL is already hashed by the manifest. In DEBUG the
        manifest is bypassed, so append `?v=<mtime>` to bust the browser cache
        whenever a static file changes — every `{% static %}` gets this for
        free, no per-template tag needed."""
        url = super().url(name, force)
        if settings.DEBUG:
            abs_path = finders.find(name)
            if abs_path:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}v={int(os.path.getmtime(abs_path))}"
        return url
