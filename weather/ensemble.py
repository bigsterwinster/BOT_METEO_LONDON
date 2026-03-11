"""
Ensemble weather forecasts from Open-Meteo (ECMWF IFS 51 members).

Provides a REAL probability distribution based on 51 model runs instead
of an artificial Gaussian approximation.
"""

import math
import requests
from utils.logger import log

ENSEMBLE_API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


def _round_half_up(temp: float) -> int:
    """Round to nearest integer with .5 rounded away from zero."""
    if temp >= 0:
        return int(math.floor(temp + 0.5))
    return int(math.ceil(temp - 0.5))


def _celsius_to_fahrenheit(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def _temp_matches_tranche(rounded_temp: int, tranche: str) -> bool:
    """Return True when rounded_temp belongs to the tranche label."""
    label = tranche.strip()

    try:
        if label.endswith("-"):
            threshold = int(label[:-1])
            return rounded_temp <= threshold

        if label.endswith("+"):
            threshold = int(label[:-1])
            return rounded_temp >= threshold

        # US style range, e.g. "38-39"
        if "-" in label:
            low_str, high_str = label.split("-", 1)
            if low_str and high_str:
                low = int(low_str)
                high = int(high_str)
                return low <= rounded_temp <= high

        return rounded_temp == int(label)
    except ValueError:
        return False


def get_ensemble_forecasts(
    lat: float,
    lon: float,
    timezone: str = "Europe/London",
    days: int = 3,
) -> dict[str, list[float]] | None:
    """
    Fetch max-temperature forecasts from 51 ECMWF IFS ensemble members.

    Returns:
        {
            "2026-02-17": [6.2, 6.5, 7.1, ...],   # 51 values
            "2026-02-18": [5.8, 6.0, 6.3, ...],
            ...
        }
        or None on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "ecmwf_ifs025",
        "forecast_days": days,
        "timezone": timezone,
    }

    try:
        response = requests.get(ENSEMBLE_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])

        if not dates:
            log("Ensemble API: réponse vide (pas de dates)", "warning")
            return None

        results: dict[str, list[float]] = {}

        for i, date_str in enumerate(dates):
            member_temps = []
            for m in range(51):
                key = f"temperature_2m_max_member{m:02d}"
                if key in daily and i < len(daily[key]):
                    val = daily[key][i]
                    if val is not None:
                        member_temps.append(val)

            if member_temps:
                results[date_str] = member_temps

        total_members = len(next(iter(results.values()), []))
        log(f"Ensemble API: {len(results)} jours, {total_members} membres par jour")
        return results

    except requests.RequestException as e:
        log(f"Ensemble API: erreur requête — {e}", "warning")
        return None
    except (KeyError, ValueError, IndexError) as e:
        log(f"Ensemble API: erreur parsing — {e}", "warning")
        return None


def build_probability_from_ensemble(
    member_temps: list[float], tranches: list[str], unit: str = "celsius",
    city_id: str | None = None,
) -> dict[str, float]:
    """
    Build probability distribution directly from ensemble members.

    NO Gaussian — we simply count how many of the 51 members fall into each
    temperature tranche.  Example: 20/51 members predict 12°C → P = 39%.
    """
    # Bias correction for London (ECMWF cold bias on max temp: +1°C)
    if city_id == "london":
        member_temps = [t + 1.0 for t in member_temps]
        log("Bias correction London: +1°C appliquée sur ensemble")

    import statistics
    total = len(member_temps)
    if total == 0:
        return {t: 0.0 for t in tranches}

    mean_raw = statistics.mean(member_temps)
    spread = max(member_temps) - min(member_temps)
    log(
        f"🌡️ Ensemble membres: {total} | "
        f"moyenne={mean_raw:.1f}°C | "
        f"min={min(member_temps):.1f}°C | "
        f"max={max(member_temps):.1f}°C | "
        f"spread={spread:.1f}°C"
    )


    probabilities: dict[str, float] = {}
    use_fahrenheit = unit.lower() == "fahrenheit"

    rounded_temps = []
    for temp in member_temps:
        value = _celsius_to_fahrenheit(temp) if use_fahrenheit else temp
        rounded_temps.append(_round_half_up(value))

    for tranche in tranches:
        count = sum(1 for rounded in rounded_temps if _temp_matches_tranche(rounded, tranche))

        probabilities[tranche] = round(count / total, 4)

    # Log distribution complète pour analyse agent IA
    dist_str = " | ".join([f"{t}:{p:.0%}" for t, p in sorted(probabilities.items(), key=lambda x: x[1], reverse=True)[:5]])
    log(f"📊 Distribution top-5: {dist_str}")

    return probabilities
