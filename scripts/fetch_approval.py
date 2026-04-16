"""
Fetch Trump approval rating averages and commit approval.json
directly via the GitHub API (no git push needed).

Sources tried in order:
  1. FiveThirtyEight / ABC News approval CSV
  2. Wikipedia API

Environment variables (set automatically by GitHub Actions):
  GITHUB_TOKEN       — repo token with contents:write
  GITHUB_REPOSITORY  — e.g. "username/repo-name"
"""

import base64
import json
import os
import re
import sys
from datetime import datetime

import requests

START_DATE = "2025-04-01"
HEADERS    = {"User-Agent": "TACO-indicator-bot/1.0"}


# ── SOURCE 1: FiveThirtyEight ─────────────────────────────────────

def fetch_538():
    candidates = [
        "https://projects.fivethirtyeight.com/polls/data/approval_averages.csv",
        "https://cdn.projects.fte.app/polls/data/approval_averages.csv",
    ]
    for url in candidates:
        try:
            print(f"  Trying: {url}")
            r = requests.get(url, timeout=20, headers=HEADERS)
            if r.status_code != 200:
                print(f"    HTTP {r.status_code}")
                continue

            lines = [l for l in r.text.strip().splitlines() if l.strip()]
            if len(lines) < 2:
                continue

            header = [h.strip().strip('"').lower() for h in lines[0].split(",")]

            def col(*names):
                for n in names:
                    for i, h in enumerate(header):
                        if n in h:
                            return i
                return None

            date_col    = col("date")
            approve_col = col("approve_estimate", "approve", "approval")
            name_col    = col("politician", "name", "subject")

            if date_col is None or approve_col is None:
                print(f"    Unexpected columns: {header[:8]}")
                continue

            results = {}
            for line in lines[1:]:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) <= max(date_col, approve_col):
                    continue
                if name_col is not None and "trump" not in parts[name_col].lower():
                    continue
                try:
                    d = parts[date_col][:10]
                    if d < START_DATE:
                        continue
                    v = float(parts[approve_col])
                    if 20 <= v <= 80:
                        results[d] = round(v, 1)
                except (ValueError, IndexError):
                    continue

            if len(results) >= 5:
                print(f"    ✓ {len(results)} data points")
                return results, "FiveThirtyEight / ABC News"

        except Exception as e:
            print(f"    Error: {e}")

    return None, None


# ── SOURCE 2: Wikipedia ───────────────────────────────────────────

def fetch_wikipedia():
    api = "https://en.wikipedia.org/w/api.php"
    pages = [
        "Presidency of Donald Trump (2025–2029)",
        "Donald Trump",
    ]
    for page in pages:
        try:
            print(f"  Trying Wikipedia: {page}")
            r = requests.get(api, params={
                "action": "parse", "page": page,
                "prop": "wikitext", "format": "json",
            }, timeout=20, headers=HEADERS)
            if r.status_code != 200:
                continue

            wikitext = r.json().get("parse", {}).get("wikitext", {}).get("*", "")
            results = {}
            date_pat = re.compile(r'(\d{4}-\d{2}-\d{2})')
            num_pat  = re.compile(r'\b(\d{2,3}(?:\.\d)?)\b')

            for line in wikitext.splitlines():
                dates = date_pat.findall(line)
                if not dates or dates[0] < START_DATE:
                    continue
                nums = [float(n) for n in num_pat.findall(line) if 20 <= float(n) <= 80]
                if nums:
                    results[dates[0]] = round(nums[0], 1)

            if len(results) >= 3:
                print(f"    ✓ {len(results)} data points")
                return results, "Wikipedia"

        except Exception as e:
            print(f"    Error: {e}")

    return None, None


# ── GITHUB API COMMIT ─────────────────────────────────────────────

def commit_to_github(content_str, token, repo):
    """Commit approval.json via GitHub API — no git needed."""
    api_base = f"https://api.github.com/repos/{repo}/contents/approval.json"
    auth     = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    # Get existing file SHA (needed for updates)
    sha = None
    r = requests.get(api_base, headers=auth, timeout=15)
    if r.status_code == 200:
        sha = r.json().get("sha")

    body = {
        "message": f"chore: update approval data {datetime.utcnow().strftime('%Y-%m-%d')}",
        "content": base64.b64encode(content_str.encode()).decode(),
    }
    if sha:
        body["sha"] = sha

    r = requests.put(api_base, headers=auth, json=body, timeout=15)
    if r.status_code in (200, 201):
        print(f"✓ approval.json committed to {repo}")
        return True
    else:
        print(f"✗ GitHub API error {r.status_code}: {r.text[:200]}")
        return False


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        print("Missing GITHUB_TOKEN or GITHUB_REPOSITORY — running locally, saving file only.")

    print("=" * 50)
    print("Fetching Trump approval data...")
    print("=" * 50)

    data, source = fetch_538()
    if not data:
        data, source = fetch_wikipedia()

    if not data:
        print("\n⚠ All sources failed — approval.json not updated.")
        sys.exit(0)

    entries = [{"d": k, "v": v} for k, v in sorted(data.items()) if k >= START_DATE]
    output  = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":  source,
        "data":    entries,
    }
    content_str = json.dumps(output, indent=2)

    print(f"\n{len(entries)} data points  ({entries[0]['d']} → {entries[-1]['d']})")
    print(f"Source: {source}")

    if token and repo:
        commit_to_github(content_str, token, repo)
    else:
        # Local run — just write the file
        out = os.path.join(os.path.dirname(__file__), "..", "approval.json")
        with open(out, "w") as f:
            f.write(content_str)
        print(f"Saved locally to approval.json")


if __name__ == "__main__":
    main()
