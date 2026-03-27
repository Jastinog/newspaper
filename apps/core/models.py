from django.db import models


class Language(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @classmethod
    def default(cls):
        return cls.objects.filter(is_default=True).first()

    @classmethod
    def active_targets(cls):
        """Return active non-default languages for translation."""
        return cls.objects.filter(is_active=True).exclude(is_default=True)
