#!/usr/bin/env python3
"""
RSS Feed Validator
Run locally: pip install feedparser requests && python validate_feeds.py

Reads rss_database.json, checks each feed URL,
and outputs rss_database_validated.json with only working feeds.
"""

import json
import feedparser
import requests
import concurrent.futures
import time
import sys
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RSSValidator/1.0)"}
TIMEOUT = 15
MAX_WORKERS = 10


def validate_feed(feed):
    """Check if a single RSS feed URL is alive and returns valid XML."""
    url = feed["url"]
    result = {**feed, "_valid": False, "_status": "unknown", "_items": 0}

    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        result["_http"] = resp.status_code

        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            if parsed.feed and (parsed.feed.get("title") or len(parsed.entries) > 0):
                result["_valid"] = True
                result["_status"] = "active"
                result["_items"] = len(parsed.entries)
                result["_feed_title"] = parsed.feed.get("title", "")
            else:
                result["_status"] = "no_valid_entries"
        elif resp.status_code == 403:
            result["_status"] = "forbidden"
        elif resp.status_code == 404:
            result["_status"] = "not_found"
        elif resp.status_code == 301 or resp.status_code == 302:
            result["_status"] = f"redirect_{resp.status_code}"
        else:
            result["_status"] = f"http_{resp.status_code}"
    except requests.exceptions.Timeout:
        result["_status"] = "timeout"
    except requests.exceptions.ConnectionError:
        result["_status"] = "connection_error"
    except Exception as e:
        result["_status"] = f"error: {str(e)[:100]}"

    return result


def main():
    db_path = Path(__file__).parent / "rss_database.json"
    if not db_path.exists():
        print(f"Error: {db_path} not found")
        sys.exit(1)

    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)

    feeds = db["feeds"]
    total = len(feeds)
    print(f"\n{'='*60}")
    print(f"  RSS Feed Validator — checking {total} feeds")
    print(f"{'='*60}\n")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(validate_feed, feed): feed for feed in feeds}
        for i, future in enumerate(concurrent.futures.as_completed(future_map), 1):
            r = future.result()
            results.append(r)
            icon = "\033[92m✓\033[0m" if r["_valid"] else "\033[91m✗\033[0m"
            extra = f" ({r['_items']} items)" if r["_valid"] else ""
            print(f"  [{i:3d}/{total}] {icon} {r['name']:<35} {r['_status']}{extra}")

    valid = [r for r in results if r["_valid"]]
    invalid = [r for r in results if not r["_valid"]]

    # Strip internal fields from valid feeds
    clean_feeds = []
    for r in sorted(valid, key=lambda x: (x["region"], x["country"], x["name"])):
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        clean["verified"] = True
        clean["verified_date"] = time.strftime("%Y-%m-%d")
        clean_feeds.append(clean)

    # Write validated JSON
    output = {
        **{k: v for k, v in db.items() if k != "feeds"},
        "total_feeds": len(clean_feeds),
        "validated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "feeds": clean_feeds
    }

    out_path = Path(__file__).parent / "rss_database_validated.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS: {len(valid)} valid / {len(invalid)} invalid / {total} total")
    print(f"  Countries: {len(set(f['country'] for f in clean_feeds))}")
    print(f"  Saved to: {out_path.name}")
    print(f"{'='*60}")

    if invalid:
        print(f"\n  FAILED FEEDS ({len(invalid)}):")
        for r in sorted(invalid, key=lambda x: x["name"]):
            print(f"    ✗ {r['name']:<35} [{r['country']}] — {r['_status']}")

    print()


if __name__ == "__main__":
    main()
