import django.db.models.deletion
from django.db import migrations, models


def set_default_language(apps, schema_editor):
    """Set existing researches to the default (English) language."""
    Research = apps.get_model("research", "Research")
    Language = apps.get_model("core", "Language")
    en = Language.objects.filter(code="en").first()
    if en:
        Research.objects.filter(language__isnull=True).update(language=en)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("research", "0001_initial"),
    ]

    operations = [
        # 1. Add nullable FK
        migrations.AddField(
            model_name="research",
            name="language",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="researches",
                to="core.language",
            ),
        ),
        # 2. Populate existing rows
        migrations.RunPython(set_default_language, migrations.RunPython.noop),
        # 3. Make non-nullable
        migrations.AlterField(
            model_name="research",
            name="language",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="researches",
                to="core.language",
            ),
        ),
        # 4. Add unique constraint
        migrations.AlterUniqueTogether(
            name="research",
            unique_together={("item", "language")},
        ),
    ]
