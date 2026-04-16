"""
Fetch Trump approval rating averages and save to approval.json.

Sources tried in order:
  1. FiveThirtyEight / ABC News approval CSV
  2. Wikipedia API (parses the approval table from the Trump presidency article)

Run manually:  python scripts/fetch_approval.py
"""

import json
import os
import re
import sys
from datetime import datetime, date

import requests

START_DATE = "2025-04-01"
OUT_FILE   = os.path.join(os.path.dirname(__file__), "..", "approval.json")
HEADERS    = {"User-Agent": "TACO-indicator-bot/1.0 (github actions)"}


# ── SOURCE 1: FiveThirtyEight ────────────────────────────────────────────────

def fetch_538():
    """
    538 / ABC News publishes approval averages as a CSV.
    Multiple candidate URLs in case they change the path.
    """
    candidates = [
        "https://projects.fivethirtyeight.com/polls/data/approval_averages.csv",
        "https://cdn.projects.fte.app/polls/data/approval_averages.csv",
        "https://abcnews.go.com/sites/default/files/polls/data/approval_averages.csv",
    ]

    for url in candidates:
        try:
            print(f"  Trying 538: {url}")
            r = requests.get(url, timeout=20, headers=HEADERS)
            if r.status_code != 200:
                print(f"    → HTTP {r.status_code}")
                continue

            lines = [l for l in r.text.strip().splitlines() if l.strip()]
            if len(lines) < 2:
                continue

            raw_header = lines[0]
            # Handle quoted CSV
            header = [h.strip().strip('"').lower() for h in raw_header.split(",")]

            # Locate columns
            def col(names):
                for n in names:
                    for i, h in enumerate(header):
                        if n in h:
                            return i
                return None

            date_col    = col(["date"])
            approve_col = col(["approve_estimate", "approve", "approval"])
            name_col    = col(["politician", "name", "subject"])

            if date_col is None or approve_col is None:
                print(f"    → Unexpected columns: {header[:8]}")
                continue

            results = {}
            for line in lines[1:]:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) <= max(date_col, approve_col):
                    continue
                # Filter for Trump rows if a name column exists
                if name_col is not None and "trump" not in parts[name_col].lower():
                    continue
                try:
                    d = parts[date_col][:10]
                    if d < START_DATE:
                        continue
                    v = float(parts[approve_col])
                    if 20 <= v <= 80:   # sanity range
                        results[d] = round(v, 1)
                except (ValueError, IndexError):
                    continue

            if len(results) >= 5:
                print(f"    → ✓ {len(results)} data points")
                return results, "FiveThirtyEight / ABC News"

        except Exception as e:
            print(f"    → Error: {e}")

    return None, None


# ── SOURCE 2: Wikipedia approval table ──────────────────────────────────────

def fetch_wikipedia():
    """
    Parse the Trump presidency Wikipedia article for the approval rating table.
    Looks for rows containing dates and percentage values.
    """
    page_titles = [
        "Presidency of Donald Trump (2025–2029)",
        "Donald Trump",
    ]

    for title in page_titles:
        try:
            print(f"  Trying Wikipedia: {title}")
            api = "https://en.wikipedia.org/w/api.php"
            r = requests.get(api, params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
                "section": 0,   # intro only — approval usually in a section
            }, timeout=20, headers=HEADERS)

            if r.status_code != 200:
                continue

            j = r.json()
            wikitext = j.get("parse", {}).get("wikitext", {}).get("*", "")
            if not wikitext:
                continue

            # Look for lines like: | 2025-06-01 || 44.2 || 51.3
            results = {}
            date_pat    = re.compile(r'(\d{4}-\d{2}-\d{2})')
            percent_pat = re.compile(r'\b(\d{2,3}(?:\.\d)?)\b')

            for line in wikitext.splitlines():
                dates = date_pat.findall(line)
                if not dates:
                    continue
                d = dates[0]
                if d < START_DATE:
                    continue
                nums = [float(n) for n in percent_pat.findall(line) if 20 <= float(n) <= 80]
                if nums:
                    results[d] = round(nums[0], 1)

            if len(results) >= 3:
                print(f"    → ✓ {len(results)} data points")
                return results, "Wikipedia"

        except Exception as e:
            print(f"    → Error: {e}")

    return None, None


# ── MERGE WITH EXISTING ──────────────────────────────────────────────────────

def load_existing():
    try:
        with open(OUT_FILE) as f:
            existing = json.load(f)
        return {e["d"]: e["v"] for e in existing.get("data", [])}
    except Exception:
        return {}


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("Fetching Trump approval data...")
    print("=" * 50)

    new_data, source = fetch_538()

    if not new_data:
        new_data, source = fetch_wikipedia()

    if not new_data:
        print("\n⚠ All sources failed — keeping existing data unchanged.")
        sys.exit(0)

    # Merge: new data wins over old, but keep any old dates not in new data
    merged = {**load_existing(), **new_data}

    # Build sorted list
    entries = [{"d": k, "v": v} for k, v in sorted(merged.items()) if k >= START_DATE]

    output = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "data": entries,
    }

    with open(OUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Saved {len(entries)} data points to approval.json  (source: {source})")
    print(f"  Date range: {entries[0]['d']} → {entries[-1]['d']}")


if __name__ == "__main__":
    main()
