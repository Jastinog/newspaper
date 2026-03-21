"""Replace PageView with Client → Session → Activity hierarchy."""

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0008_add_rss_content"),
        ("analytics", "0001_initial"),
    ]

    operations = [
        # Drop old model
        migrations.DeleteModel(name="PageView"),

        # Client
        migrations.CreateModel(
            name="Client",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_id", models.UUIDField(db_index=True, unique=True)),
                ("first_seen", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField(auto_now=True)),
                ("device_type", models.CharField(blank=True, default="", max_length=20)),
                ("browser", models.CharField(blank=True, default="", max_length=50)),
                ("os", models.CharField(blank=True, default="", max_length=50)),
                ("user_agent", models.CharField(blank=True, default="", max_length=500)),
                ("ip_hash", models.CharField(blank=True, default="", max_length=64)),
                ("country", models.CharField(blank=True, default="", max_length=2)),
                ("country_name", models.CharField(blank=True, default="", max_length=100)),
                ("city", models.CharField(blank=True, default="", max_length=200)),
                ("is_bot", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ["-last_seen"],
            },
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["-last_seen"], name="analytics_c_last_se_idx"),
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["is_bot", "-last_seen"], name="analytics_c_is_bot_idx"),
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["country", "-last_seen"], name="analytics_c_country_idx"),
        ),

        # Session
        migrations.CreateModel(
            name="Session",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_id", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("page_count", models.PositiveIntegerField(default=0)),
                ("active_time", models.PositiveIntegerField(default=0, help_text="Seconds of active time")),
                ("has_interaction", models.BooleanField(default=False)),
                ("referrer", models.URLField(blank=True, default="", max_length=2000)),
                ("referrer_domain", models.CharField(blank=True, default="", max_length=253)),
                ("is_human", models.BooleanField(default=False)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sessions", to="analytics.client")),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
        migrations.AddIndex(
            model_name="session",
            index=models.Index(fields=["-started_at"], name="analytics_s_started_idx"),
        ),
        migrations.AddIndex(
            model_name="session",
            index=models.Index(fields=["client", "-started_at"], name="analytics_s_client_idx"),
        ),
        migrations.AddIndex(
            model_name="session",
            index=models.Index(fields=["is_human", "-started_at"], name="analytics_s_is_huma_idx"),
        ),

        # Activity
        migrations.CreateModel(
            name="Activity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("page_view", "Page View"), ("scroll", "Scroll"), ("click", "Click"), ("heartbeat", "Heartbeat")], max_length=20)),
                ("path", models.CharField(max_length=2000)),
                ("view_name", models.CharField(blank=True, default="", max_length=100)),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("meta", models.JSONField(blank=True, default=dict)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="analytics.session")),
                ("article", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activities", to="news.article")),
                ("category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activities", to="news.category")),
            ],
            options={
                "ordering": ["-timestamp"],
            },
        ),
        migrations.AddIndex(
            model_name="activity",
            index=models.Index(fields=["session", "-timestamp"], name="analytics_a_session_idx"),
        ),
        migrations.AddIndex(
            model_name="activity",
            index=models.Index(fields=["type", "-timestamp"], name="analytics_a_type_idx"),
        ),
        migrations.AddIndex(
            model_name="activity",
            index=models.Index(fields=["article", "-timestamp"], name="analytics_a_article_idx"),
        ),
        migrations.AddIndex(
            model_name="activity",
            index=models.Index(fields=["path", "-timestamp"], name="analytics_a_path_idx"),
        ),
    ]
