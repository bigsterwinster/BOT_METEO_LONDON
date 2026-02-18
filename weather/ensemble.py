"""
Ensemble weather forecasts from Open-Meteo (ECMWF IFS 51 members).

Provides a REAL probability distribution based on 51 model runs instead
of an artificial Gaussian approximation.
"""

import requests
from utils.logger import log
from config import LONDON_CITY_AIRPORT_LAT, LONDON_CITY_AIRPORT_LON

ENSEMBLE_API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


def get_ensemble_forecasts(
    lat: float = None, lon: float = None, days: int = 3
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
    lat = lat or LONDON_CITY_AIRPORT_LAT
    lon = lon or LONDON_CITY_AIRPORT_LON

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "ecmwf_ifs025",
        "forecast_days": days,
        "timezone": "Europe/London",
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
    member_temps: list[float], tranches: list[str]
) -> dict[str, float]:
    """
    Build probability distribution directly from ensemble members.

    NO Gaussian — we simply count how many of the 51 members fall into each
    temperature tranche.  Example: 20/51 members predict 12°C → P = 39%.
    """
    total = len(member_temps)
    if total == 0:
        return {t: 0.0 for t in tranches}

    probabilities = {}

    for tranche in tranches:
        count = 0
        for temp in member_temps:
            rounded = round(temp)

            if tranche.endswith("-"):
                threshold = int(tranche[:-1])
                if rounded <= threshold:
                    count += 1
            elif tranche.endswith("+"):
                threshold = int(tranche[:-1])
                if rounded >= threshold:
                    count += 1
            else:
                if rounded == int(tranche):
                    count += 1

        probabilities[tranche] = round(count / total, 4)

    return probabilities
