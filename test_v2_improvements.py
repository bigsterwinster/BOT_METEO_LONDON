"""Quick test for all V2 improvements."""

print("=" * 60)
print("TEST 1: Ensemble API")
print("=" * 60)
try:
    from weather.ensemble import get_ensemble_forecasts, build_probability_from_ensemble
    data = get_ensemble_forecasts(51.5053, 0.0553, days=3)
    if data:
        for d, temps in data.items():
            print(f"  {d}: {len(temps)} members, min={min(temps):.1f}, max={max(temps):.1f}, mean={sum(temps)/len(temps):.1f}")
            probs = build_probability_from_ensemble(temps, ["5-", "6", "7", "8", "9", "10", "11+"])
            print(f"    Distribution: {probs}")
        print("  ✅ Ensemble API OK")
    else:
        print("  ❌ Ensemble API returned None")
except Exception as e:
    print(f"  ❌ Ensemble API error: {e}")

print()
print("=" * 60)
print("TEST 2: Kelly Criterion + Dynamic Edge")
print("=" * 60)
try:
    from strategy.edge_calculator import calculate_bet_size, get_min_edge_for_horizon
    
    tests = [
        (0.45, 0.20, 50.0, 10.0, "Fort edge, haute proba"),
        (0.30, 0.05, 50.0, 10.0, "Fort edge, basse proba"),
        (0.40, 0.35, 50.0, 10.0, "Petit edge, haute proba"),
        (0.20, 0.25, 50.0, 10.0, "Pas d'edge"),
    ]
    for prob, price, bank, maxb, label in tests:
        size = calculate_bet_size(prob, price, bank, maxb)
        print(f"  {label}: prob={prob:.0%} prix={price:.2f} -> mise={size:.2f}$")
    
    for d in [0, 1, 2, 3]:
        print(f"  J+{d}: min edge = {get_min_edge_for_horizon(d):.0%}")
    
    print("  ✅ Kelly + Edge OK")
except Exception as e:
    print(f"  ❌ Kelly/Edge error: {e}")

print()
print("=" * 60)
print("TEST 3: Timing optimal")
print("=" * 60)
try:
    from main import should_bet_on_market
    from datetime import date, timedelta
    
    today = date.today()
    for d in range(4):
        target = today + timedelta(days=d)
        ok, reason = should_bet_on_market(target.isoformat())
        print(f"  {target} (J+{d}): should_bet={ok}, reason={reason}")
    
    print("  ✅ Timing OK")
except Exception as e:
    print(f"  ❌ Timing error: {e}")

print()
print("=" * 60)
print("TEST 4: Analyzer — get_probability_distribution (ensemble + fallback)")
print("=" * 60)
try:
    from weather.analyzer import get_probability_distribution, build_probability_distribution_gaussian
    from datetime import date, timedelta
    
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tranches = ["5-", "6", "7", "8", "9", "10", "11+"]
    
    probs, source_info = get_probability_distribution(tomorrow, tranches, days_ahead=1, forecast_temp=8.0)
    print(f"  Method: {source_info['method']}")
    print(f"  Source info: {source_info}")
    print(f"  Distribution: {probs}")
    print(f"  Sum: {sum(probs.values()):.4f}")

    nyc_tranches = ["34-", "35", "36-37", "38-39", "40-41", "42+"]
    nyc_probs = build_probability_distribution_gaussian(
        forecast_temp=8.0,  # °C input, internally converted to °F
        sigma=1.0,
        tranches=nyc_tranches,
        unit="fahrenheit",
    )
    print(f"  NYC (°F) Distribution: {nyc_probs}")
    print(f"  NYC (°F) Sum: {sum(nyc_probs.values()):.4f}")

    print("  ✅ Analyzer OK")
except Exception as e:
    print(f"  ❌ Analyzer error: {e}")

print()
print("=" * 60)
print("TEST 5: Config values")
print("=" * 60)
try:
    from config import CHECK_INTERVAL_HOURS, BANKROLL, KELLY_FRACTION, MAX_BET_USDC
    print(f"  CHECK_INTERVAL_HOURS = {CHECK_INTERVAL_HOURS}")
    print(f"  BANKROLL = {BANKROLL}")
    print(f"  KELLY_FRACTION = {KELLY_FRACTION}")
    print(f"  MAX_BET_USDC = {MAX_BET_USDC}")
    assert CHECK_INTERVAL_HOURS == 2, f"Expected 2, got {CHECK_INTERVAL_HOURS}"
    assert BANKROLL == 50, f"Expected 50, got {BANKROLL}"
    assert KELLY_FRACTION == 0.25, f"Expected 0.25, got {KELLY_FRACTION}"
    print("  ✅ Config OK")
except Exception as e:
    print(f"  ❌ Config error: {e}")

print()
print("🏁 All tests complete!")
