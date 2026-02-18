import requests
from utils.logger import log
from config import LONDON_CITY_AIRPORT_LAT, LONDON_CITY_AIRPORT_LON

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def get_forecasts(forecast_days: int = 3) -> dict | None:
    """
    Fetch 3-day temperature forecast from Open-Meteo for London City Airport.

    Returns:
        {
            "2026-02-11": {"max_temp": 12.3, "min_temp": 5.1},
            "2026-02-12": {"max_temp": 10.8, "min_temp": 4.2},
            ...
        }
        or None on failure.
    """
    params = {
        "latitude": LONDON_CITY_AIRPORT_LAT,
        "longitude": LONDON_CITY_AIRPORT_LON,
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Europe/London",
        "forecast_days": forecast_days,
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])

        if not dates:
            log("Open-Meteo: réponse vide (pas de dates)", "warning")
            return None

        forecasts = {}
        for date, t_max, t_min in zip(dates, max_temps, min_temps):
            forecasts[date] = {"max_temp": t_max, "min_temp": t_min}

        log(f"Open-Meteo: prévisions récupérées pour {len(forecasts)} jours")
        return forecasts

    except requests.RequestException as e:
        log(f"Open-Meteo: erreur requête — {e}", "error")
        return None
    except (KeyError, ValueError) as e:
        log(f"Open-Meteo: erreur parsing — {e}", "error")
        return None
