"""Test the source_info flow through analyzer -> main -> telegram."""
from weather.analyzer import get_probability_distribution
from datetime import date, timedelta

tomorrow = (date.today() + timedelta(days=1)).isoformat()
tranches = ["5-", "6", "7", "8", "9", "10", "11+"]

probs, source_info = get_probability_distribution(tomorrow, tranches, days_ahead=1, forecast_temp=8.0)
method = source_info["method"]

if method == "ensemble":
    source_summary = (
        f"Ensemble ({source_info['members']} membres, "
        f"spread {source_info['spread_min']}-{source_info['spread_max']}\u00b0C)"
    )
else:
    source_summary = f"Gaussienne (\u03c3={source_info['sigma']})"

print(f"Method: {method}")
print(f"Source info: {source_info}")
print(f"Source summary: {source_summary}")
print(f"Distribution: {probs}")

# Simulate the notification message
forecast_str = f"{source_info['mean_temp']}\u00b0C" if source_info["mean_temp"] else "N/A"
best_tranche = max(probs, key=probs.get)
print()
print("=== Example Telegram notification ===")
print(
    f"\ud83d\udcca Source: {source_summary} | Pr\u00e9vision: {forecast_str} | "
    f"Pari: {best_tranche}\u00b0C @ 0.35 (Kelly: 4.20$)"
)
print()
print("\u2705 Source info test OK")
