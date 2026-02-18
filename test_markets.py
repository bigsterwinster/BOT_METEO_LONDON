"""Quick test: verify that find_london_temperature_markets works correctly."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from polymarket.markets import find_london_temperature_markets

markets = find_london_temperature_markets()
print(f"\n{'='*60}")
print(f"Found {len(markets)} London temperature market(s)")
print(f"{'='*60}")

for m in markets:
    print(f"\n📅 {m['date']} — {m['title']}")
    print(f"   Event ID: {m['event_id']}")
    print(f"   Tranches ({len(m['tranches'])}):")
    for t in m['tranches']:
        print(f"     {t['label']:>4s} | {t['question'][:60]}")
        print(f"          YES token: {t['token_id_yes'][:30]}...")
