"""Fetch usage and cost data from OpenAI's Organization API.

Requires an admin API key (sk-admin-...).
Set OPENAI_ADMIN_KEY in your environment, or pass --key.

Usage:
    python manage.py openai_usage                  # last 7 days
    python manage.py openai_usage --days 30        # last 30 days
    python manage.py openai_usage --compare        # compare with local APIUsage
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests
from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.billing.models import APIUsage

API_BASE = "https://api.openai.com/v1/organization"


class Command(BaseCommand):
    help = "Fetch usage and cost data from OpenAI Organization API"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7, help="Number of days to fetch (default: 7)")
        parser.add_argument("--key", type=str, default="", help="Admin API key (or set OPENAI_ADMIN_KEY env var)")
        parser.add_argument("--compare", action="store_true", help="Compare OpenAI costs with local APIUsage records")

    def handle(self, **options):
        api_key = options["key"] or os.environ.get("OPENAI_ADMIN_KEY", "")
        if not api_key:
            self.stderr.write(self.style.ERROR(
                "No admin key. Set OPENAI_ADMIN_KEY env var or pass --key sk-admin-..."
            ))
            return

        days = options["days"]
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        start_ts = int(start.timestamp())
        end_ts = int(now.timestamp())

        headers = {"Authorization": f"Bearer {api_key}"}

        # 1. Fetch costs
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nOpenAI costs (last {days} days)"))
        costs = self._fetch_costs(headers, start_ts, end_ts)
        if costs is None:
            return

        # 2. Fetch completions usage
        self.stdout.write(self.style.MIGRATE_HEADING("\nCompletions usage"))
        completions = self._fetch_usage(headers, start_ts, end_ts, "completions")

        # 3. Fetch embeddings usage
        self.stdout.write(self.style.MIGRATE_HEADING("\nEmbeddings usage"))
        embeddings = self._fetch_usage(headers, start_ts, end_ts, "embeddings")

        # 4. Compare with local
        if options["compare"]:
            self._compare_local(start, now, costs)

    def _fetch_costs(self, headers, start_ts, end_ts):
        """Fetch /v1/organization/costs."""
        params = {
            "start_time": start_ts,
            "end_time": end_ts,
            "bucket_width": "1d",
        }
        try:
            resp = requests.get(f"{API_BASE}/costs", headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Request failed: {e}"))
            return None

        if not resp.ok:
            self.stderr.write(self.style.ERROR(f"API error {resp.status_code}: {resp.text[:500]}"))
            return None

        data = resp.json()
        buckets = data.get("data", [])

        total_cost = 0.0
        model_costs = {}

        for bucket in buckets:
            day = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc).strftime("%Y-%m-%d")
            for result in bucket.get("results", []):
                amount = result.get("amount", {}).get("value", 0)
                line_item = result.get("line_item", "unknown")
                total_cost += amount
                model_costs.setdefault(line_item, 0.0)
                model_costs[line_item] += amount

        if not model_costs:
            self.stdout.write("  No cost data found for this period.")
            return {"total": 0, "by_model": {}}

        for model, cost in sorted(model_costs.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  {model:<40} ${cost:.6f}")

        self.stdout.write(self.style.SUCCESS(f"\n  Total: ${total_cost:.6f}"))
        return {"total": total_cost, "by_model": model_costs}

    def _fetch_usage(self, headers, start_ts, end_ts, endpoint):
        """Fetch /v1/organization/usage/{completions,embeddings}."""
        params = {
            "start_time": start_ts,
            "end_time": end_ts,
            "bucket_width": "1d",
        }
        try:
            resp = requests.get(f"{API_BASE}/usage/{endpoint}", headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Request failed: {e}"))
            return None

        if not resp.ok:
            self.stderr.write(self.style.ERROR(f"API error {resp.status_code}: {resp.text[:500]}"))
            return None

        data = resp.json()
        buckets = data.get("data", [])

        total_input = 0
        total_output = 0
        model_tokens = {}

        for bucket in buckets:
            for result in bucket.get("results", []):
                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                model = result.get("model", "unknown")
                total_input += input_tokens
                total_output += output_tokens
                entry = model_tokens.setdefault(model, {"input": 0, "output": 0})
                entry["input"] += input_tokens
                entry["output"] += output_tokens

        if not model_tokens:
            self.stdout.write("  No usage data found for this period.")
            return

        for model, tokens in sorted(model_tokens.items()):
            total = tokens["input"] + tokens["output"]
            self.stdout.write(
                f"  {model:<40} {total:>12,} tokens "
                f"(in: {tokens['input']:,}, out: {tokens['output']:,})"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\n  Total: {total_input + total_output:,} tokens "
            f"(in: {total_input:,}, out: {total_output:,})"
        ))

    def _compare_local(self, start, end, openai_costs):
        """Compare OpenAI reported costs with local APIUsage records."""
        self.stdout.write(self.style.MIGRATE_HEADING("\nComparison: OpenAI vs local"))

        local = APIUsage.objects.filter(
            created_at__gte=start, created_at__lte=end,
        ).aggregate(
            cost=Sum("cost_usd"),
            tokens=Sum("total_tokens"),
            prompt=Sum("prompt_tokens"),
            completion=Sum("completion_tokens"),
        )

        local_cost = float(local["cost"] or 0)
        local_tokens = local["tokens"] or 0
        openai_cost = openai_costs.get("total", 0)

        self.stdout.write(f"  {'OpenAI reported cost:':<30} ${openai_cost:.6f}")
        self.stdout.write(f"  {'Local tracked cost:':<30} ${local_cost:.6f}")

        diff = openai_cost - local_cost
        pct = (diff / openai_cost * 100) if openai_cost else 0
        style = self.style.SUCCESS if abs(pct) < 5 else self.style.WARNING
        self.stdout.write(style(f"  {'Difference:':<30} ${diff:+.6f} ({pct:+.1f}%)"))

        self.stdout.write(f"\n  {'Local tokens:':<30} {local_tokens:,}")
        self.stdout.write(f"  {'Local prompt tokens:':<30} {local['prompt'] or 0:,}")
        self.stdout.write(f"  {'Local completion tokens:':<30} {local['completion'] or 0:,}")
