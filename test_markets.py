"""Quick test: verify multi-city market discovery works correctly."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cities import CITIES
from polymarket.markets import find_temperature_markets

for city_id in ("london", "nyc"):
    city_config = {"id": city_id, **CITIES[city_id]}
    markets = find_temperature_markets(city_config)

    print(f"\n{'='*60}")
    print(f"Found {len(markets)} {city_config['name']} temperature market(s)")
    print(f"{'='*60}")

    for m in markets:
        print(f"\n📅 {m['date']} — {m['title']}")
        print(f"   City: {m['city_name']} ({m['city_id']})")
        print(f"   Event ID: {m['event_id']}")
        print(f"   Tranches ({len(m['tranches'])}):")
        for t in m['tranches']:
            print(f"     {t['label']:>6s} | {t['question'][:60]}")
            print(f"           YES token: {t['token_id_yes'][:30]}...")
