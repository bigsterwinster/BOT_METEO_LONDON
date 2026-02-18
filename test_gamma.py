import requests
import json

# Approche 1 : recherche par texte via l'endpoint events
print("=== Test 1: Events API avec tag Weather ===")
r = requests.get("https://gamma-api.polymarket.com/events", 
                 params={"tag": "Weather", "closed": "false", "limit": 50})
events = r.json()
print(f"Nombre d'events: {len(events)}")
for e in events:
    title = e.get("title", "")
    if "london" in title.lower():
        print(f"  FOUND: {title}")
        print(f"  Slug: {e.get('slug', 'N/A')}")
        print(f"  Markets: {len(e.get('markets', []))}")
        for m in e.get("markets", []):
            print(f"    - {m.get('question', 'N/A')} | tokens: {m.get('clobTokenIds', 'N/A')}")
        print()

# Approche 2 : recherche directe dans markets
print("\n=== Test 2: Markets API avec recherche London ===")
r = requests.get("https://gamma-api.polymarket.com/markets",
                 params={"closed": "false", "limit": 100})
markets = r.json()
print(f"Nombre de markets: {len(markets)}")
for m in markets:
    q = m.get("question", "")
    if "london" in q.lower() and "temperature" in q.lower():
        print(f"  FOUND: {q}")
        print(f"  Token IDs: {m.get('clobTokenIds', 'N/A')}")
        print(f"  Outcomes: {m.get('outcomes', 'N/A')}")
        print()

# Approche 3 : recherche textuelle
print("\n=== Test 3: Search endpoint ===")
r = requests.get("https://gamma-api.polymarket.com/events",
                 params={"title": "Highest temperature in London", "closed": "false"})
print(f"Status: {r.status_code}")
print(f"Results: {json.dumps(r.json()[:3], indent=2) if r.json() else 'empty'}")

# Approche 4 : slug-based
print("\n=== Test 4: Slug-based search ===")
for slug_pattern in ["highest-temperature-in-london", "temperature-london"]:
    r = requests.get("https://gamma-api.polymarket.com/events",
                     params={"slug": slug_pattern, "closed": "false"})
    print(f"  Slug '{slug_pattern}': {len(r.json())} results")
    for e in r.json()[:3]:
        print(f"    -> {e.get('title', 'N/A')}")

# Approche 5 : text_query / search param
print("\n=== Test 5: text_query param ===")
r = requests.get("https://gamma-api.polymarket.com/events",
                 params={"closed": "false", "limit": 100, "order": "startDate", "ascending": "false"})
events = r.json()
print(f"Total events (recent first): {len(events)}")
for e in events:
    title = e.get("title", "")
    if "london" in title.lower() or "temperature" in title.lower():
        print(f"  FOUND: {title}")
        print(f"  ID: {e.get('id', 'N/A')}")
        print(f"  Slug: {e.get('slug', 'N/A')}")
        print(f"  Markets count: {len(e.get('markets', []))}")
        print()
