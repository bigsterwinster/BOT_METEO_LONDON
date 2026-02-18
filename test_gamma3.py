import requests
import json
from datetime import datetime, timedelta

today = datetime.now()
print(f"Today: {today.strftime('%Y-%m-%d')}\n")

# Approach 1: Try direct event slug lookup (known slug pattern from spec)
print("=== Test F: Direct slug lookup ===")
for days_ahead in range(3):
    d = today + timedelta(days=days_ahead)
    month = d.strftime("%B").lower()  # e.g. "february"
    day = d.day
    year = d.year
    slug = f"highest-temperature-in-london-on-{month}-{day}-{year}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    r = requests.get(url)
    events = r.json()
    print(f"  Slug: {slug}")
    print(f"  Results: {len(events)}")
    for e in events:
        print(f"    Title: {e.get('title')}")
        print(f"    ID: {e.get('id')}")
        for m in e.get("markets", []):
            q = m.get("question", "")
            tokens = m.get("clobTokenIds", "N/A")
            print(f"      Market: {q}")
            print(f"      Tokens: {str(tokens)[:100]}")
        print()

# Approach 2: Try with zero-padded day
print("\n=== Test G: Slug with zero-padded day ===")
for days_ahead in range(3):
    d = today + timedelta(days=days_ahead)
    month = d.strftime("%B").lower()
    slug = f"highest-temperature-in-london-on-{month}-{d.day:02d}-{d.year}"
    r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}")
    print(f"  Slug: {slug} -> {len(r.json())} results")

# Approach 3: Try polymarket.com search API
print("\n=== Test H: Polymarket search/lookup ===")
r = requests.get("https://gamma-api.polymarket.com/events",
                 params={"slug_contains": "london", "closed": "false"})
print(f"  slug_contains=london: {r.status_code}, {len(r.json())} results")

# Approach 4: Try strapi-like filtering (Gamma uses Strapi under the hood)
print("\n=== Test I: Strapi-style filtering ===")
for param in [
    {"slug_contains": "london"},
    {"title_contains": "london"},
    {"_where[slug_contains]": "london"},
    {"_where[0][title_contains]": "london"},
    {"slug_like": "%london%"},
]:
    r = requests.get("https://gamma-api.polymarket.com/events", params={**param, "closed": "false", "limit": 5})
    key = list(param.keys())[0]
    results = r.json()
    london_found = [e for e in results if "london" in e.get("title", "").lower()]
    print(f"  {key}={param[key]}: {r.status_code}, {len(results)} total, {len(london_found)} london")

# Approach 5: Try with tag=Weather and large offset
print("\n=== Test J: Weather tag with large offsets ===")
for offset in range(0, 800, 100):
    r = requests.get("https://gamma-api.polymarket.com/events",
                     params={"tag": "Weather", "closed": "false", "limit": 100, "offset": offset})
    events = r.json()
    if not events:
        print(f"  Offset {offset}: no more events — total Weather events exhausted")
        break
    london = [e for e in events if "london" in e.get("title", "").lower()]
    print(f"  Offset {offset}: {len(events)} events, {len(london)} London")
    for e in london:
        print(f"    FOUND: {e.get('title')}")
        print(f"    Slug: {e.get('slug')}")
        for m in e.get("markets", []):
            print(f"      - {m.get('question', 'N/A')[:60]}")
        print()
