from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.location.models import Country, Region

REGIONS = [
    {"name": "North America", "slug": "north-america", "order": 0},
    {"name": "Europe", "slug": "europe", "order": 1},
    {"name": "Eastern Europe", "slug": "eastern-europe", "order": 2},
    {"name": "Middle East", "slug": "middle-east", "order": 3},
    {"name": "Asia", "slug": "asia", "order": 4},
    {"name": "Oceania", "slug": "oceania", "order": 5},
    {"name": "Africa", "slug": "africa", "order": 6},
    {"name": "Latin America", "slug": "latin-america", "order": 7},
    {"name": "International", "slug": "international", "order": 8},
]

COUNTRIES = [
    # North America
    {"code": "US", "name": "United States", "region": "north-america"},
    {"code": "CA", "name": "Canada", "region": "north-america"},
    # Europe
    {"code": "GB", "name": "United Kingdom", "region": "europe"},
    {"code": "DE", "name": "Germany", "region": "europe"},
    {"code": "FR", "name": "France", "region": "europe"},
    {"code": "ES", "name": "Spain", "region": "europe"},
    {"code": "IT", "name": "Italy", "region": "europe"},
    {"code": "NL", "name": "Netherlands", "region": "europe"},
    {"code": "SE", "name": "Sweden", "region": "europe"},
    {"code": "NO", "name": "Norway", "region": "europe"},
    {"code": "FI", "name": "Finland", "region": "europe"},
    {"code": "CH", "name": "Switzerland", "region": "europe"},
    {"code": "PL", "name": "Poland", "region": "europe"},
    # Eastern Europe
    {"code": "UA", "name": "Ukraine", "region": "eastern-europe"},
    # Middle East
    {"code": "QA", "name": "Qatar", "region": "middle-east"},
    {"code": "IL", "name": "Israel", "region": "middle-east"},
    {"code": "TR", "name": "Turkey", "region": "middle-east"},
    {"code": "IR", "name": "Iran", "region": "middle-east"},
    # Asia
    {"code": "JP", "name": "Japan", "region": "asia"},
    {"code": "KR", "name": "South Korea", "region": "asia"},
    {"code": "HK", "name": "Hong Kong", "region": "asia"},
    {"code": "CN", "name": "China", "region": "asia"},
    {"code": "IN", "name": "India", "region": "asia"},
    {"code": "SG", "name": "Singapore", "region": "asia"},
    {"code": "TW", "name": "Taiwan", "region": "asia"},
    {"code": "TH", "name": "Thailand", "region": "asia"},
    # Oceania
    {"code": "AU", "name": "Australia", "region": "oceania"},
    {"code": "NZ", "name": "New Zealand", "region": "oceania"},
    # Africa
    {"code": "ZA", "name": "South Africa", "region": "africa"},
    {"code": "NG", "name": "Nigeria", "region": "africa"},
    {"code": "KE", "name": "Kenya", "region": "africa"},
    {"code": "EG", "name": "Egypt", "region": "africa"},
    # Latin America
    {"code": "BR", "name": "Brazil", "region": "latin-america"},
    {"code": "AR", "name": "Argentina", "region": "latin-america"},
    {"code": "MX", "name": "Mexico", "region": "latin-america"},
    # International
    {"code": "INT", "name": "International", "region": "international"},
]

LANGUAGES = [
    {"code": "en", "name": "English"},
    {"code": "de", "name": "German"},
    {"code": "fr", "name": "French"},
    {"code": "es", "name": "Spanish"},
    {"code": "it", "name": "Italian"},
    {"code": "nl", "name": "Dutch"},
    {"code": "sv", "name": "Swedish"},
    {"code": "no", "name": "Norwegian"},
    {"code": "fi", "name": "Finnish"},
    {"code": "pl", "name": "Polish"},
    {"code": "uk", "name": "Ukrainian"},
    {"code": "ja", "name": "Japanese"},
    {"code": "pt", "name": "Portuguese"},
    {"code": "ru", "name": "Russian"},
]


class Command(BaseCommand):
    help = "Seed regions, countries, and languages"

    def handle(self, *args, **options):
        # Regions
        region_map = {}
        created = 0
        for entry in REGIONS:
            region, is_new = Region.objects.get_or_create(
                slug=entry["slug"],
                defaults={"name": entry["name"], "order": entry["order"]},
            )
            region_map[entry["slug"]] = region
            if is_new:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Regions: {created} new ({len(REGIONS)} total)"))

        # Countries
        created = 0
        for entry in COUNTRIES:
            region = region_map[entry["region"]]
            _, is_new = Country.objects.get_or_create(
                code=entry["code"],
                defaults={"name": entry["name"], "region": region},
            )
            if is_new:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Countries: {created} new ({len(COUNTRIES)} total)"))

        # Languages
        created = 0
        for entry in LANGUAGES:
            _, is_new = Language.objects.get_or_create(
                code=entry["code"],
                defaults={"name": entry["name"]},
            )
            if is_new:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Languages: {created} new ({len(LANGUAGES)} total)"))
