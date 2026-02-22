import requests
from utils.logger import log
from config import WU_API_KEY

# Weather Underground uses api.weather.com (The Weather Company) internally.
# The API key is the one embedded in WU's frontend — public but may rotate.
WU_FORECAST_URL = "https://api.weather.com/v3/wx/forecast/daily/5day"


def get_forecasts(lat: float, lon: float, forecast_days: int = 5) -> dict | None:
    """
    Fetch daily max/min temperature forecast from Weather Underground
    via the api.weather.com v3 internal API.

    Returns:
        {
            "2026-02-17": {"max_temp": 7.0, "min_temp": 2.0},
            "2026-02-18": {"max_temp": 6.0, "min_temp": 4.0},
            ...
        }
        or None on failure (timeout, 403, key expired, etc.).
    """
    if not WU_API_KEY:
        log("Weather Underground: WU_API_KEY non configurée dans .env — skip", "warning")
        return None

    params = {
        "geocode": f"{lat},{lon}",
        "language": "en-GB",
        "format": "json",
        "units": "m",
        "apiKey": WU_API_KEY,
    }

    try:
        response = requests.get(WU_FORECAST_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        # The API returns parallel arrays:
        #   validTimeLocal     — ["2026-02-16T07:00:00+0000", ...]
        #   calendarDayTemperatureMax — [10, 7, 6, ...]  (always populated)
        #   temperatureMax     — [null, 7, 6, ...]       (null for today after daytime)
        #   temperatureMin     — [2, 2, 4, ...]
        valid_times = data.get("validTimeLocal", [])
        calendar_max = data.get("calendarDayTemperatureMax", [])
        temp_max = data.get("temperatureMax", [])
        temp_min = data.get("temperatureMin", [])

        if not valid_times:
            log("Weather Underground: réponse vide (pas de dates)", "warning")
            return None

        forecasts = {}
        for i, ts in enumerate(valid_times):
            # Extract date part from "2026-02-17T07:00:00+0000"
            date_str = ts[:10]

            # Prefer temperatureMax when available; fall back to calendarDayTemperatureMax
            t_max = temp_max[i] if i < len(temp_max) and temp_max[i] is not None else None
            if t_max is None and i < len(calendar_max):
                t_max = calendar_max[i]

            t_min = temp_min[i] if i < len(temp_min) else None

            if t_max is not None:
                entry = {"max_temp": float(t_max)}
                if t_min is not None:
                    entry["min_temp"] = float(t_min)
                forecasts[date_str] = entry

        log(f"Weather Underground: prévisions récupérées pour {len(forecasts)} jours")
        return forecasts

    except requests.RequestException as e:
        log(f"Weather Underground: erreur requête — {e}", "warning")
        return None
    except (KeyError, ValueError, IndexError) as e:
        log(f"Weather Underground: erreur parsing — {e}", "warning")
        return None


def get_historical(date: str) -> dict | None:
    """
    Fetch historical max temperature from Weather Underground for a given date.

    Args:
        date: date string in YYYY-MM-DD format

    Returns:
        {"max_temp": float} or None on failure.
    """
    # TODO: Implement historical data retrieval via WU API or page scraping
    log(f"Weather Underground: historique pour {date} — non implémenté", "warning")
    return None
