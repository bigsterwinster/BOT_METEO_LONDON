import requests
import json

print("=== Test A: Slug pattern search (exact slug) ===")
# Try finding events with slug containing "london"
for offset in [0, 100, 200]:
    r = requests.get("https://gamma-api.polymarket.com/events", 
                     params={"closed": "false", "limit": 100, "offset": offset})
    events = r.json()
    if not events:
        print(f"  Offset {offset}: no more events")
        break
    print(f"  Offset {offset}: {len(events)} events")
    for e in events:
        title = e.get("title", "")
        slug = e.get("slug", "")
        if "london" in title.lower() or "london" in slug.lower():
            print(f"    FOUND: {title}")
            print(f"    Slug: {slug}")
            print(f"    ID: {e.get('id')}")
            print(f"    Markets: {len(e.get('markets', []))}")
            for m in e.get("markets", []):
                print(f"      - {m.get('question', 'N/A')[:60]} | tokens: {str(m.get('clobTokenIds', 'N/A'))[:60]}")
            print()

print("\n=== Test B: Search via slug_contains ===")
r = requests.get("https://gamma-api.polymarket.com/events",
                 params={"closed": "false", "limit": 20, "slug": "london"})
print(f"  slug=london: {len(r.json())} results")
for e in r.json()[:5]:
    print(f"    {e.get('title', 'N/A')}")

print("\n=== Test C: Try slug_contains / title_contains patterns ===")
for param_name in ["slug_contains", "title_contains", "q", "search", "query", "text"]:
    try:
        r = requests.get("https://gamma-api.polymarket.com/events",
                         params={"closed": "false", param_name: "london temperature"})
        if r.status_code == 200 and r.json():
            print(f"  {param_name}='london temperature': {len(r.json())} results ✅")
            for e in r.json()[:3]:
                print(f"    {e.get('title', 'N/A')}")
        else:
            print(f"  {param_name}: {r.status_code}, {len(r.json())} results")
    except:
        print(f"  {param_name}: failed")

print("\n=== Test D: Markets endpoint with London search ===")
for offset in [0, 100, 200]:
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"closed": "false", "limit": 100, "offset": offset})
    markets = r.json()
    if not markets:
        print(f"  Offset {offset}: no more markets")
        break
    found = [m for m in markets if "london" in m.get("question", "").lower()]
    print(f"  Offset {offset}: {len(markets)} markets, {len(found)} London-related")
    for m in found:
        print(f"    FOUND: {m.get('question', 'N/A')}")
        print(f"    Token IDs: {str(m.get('clobTokenIds', 'N/A'))[:80]}")
        print(f"    Slug: {m.get('slug', 'N/A')}")
        print()

print("\n=== Test E: Events with tag Weather + broader search ===")
for offset in [0, 100]:
    r = requests.get("https://gamma-api.polymarket.com/events",
                     params={"tag": "Weather", "closed": "false", "limit": 100, "offset": offset})
    events = r.json()
    if not events:
        print(f"  Offset {offset}: no more events")
        break
    print(f"  Offset {offset}: {len(events)} weather events")
    for e in events:
        title = e.get("title", "")
        if "london" in title.lower():
            print(f"    FOUND: {title}")
            print(f"    Slug: {e.get('slug')}")
            print(f"    Markets: {len(e.get('markets', []))}")
            for m in e.get("markets", []):
                print(f"      - {m.get('question', 'N/A')[:60]}")
            print()
