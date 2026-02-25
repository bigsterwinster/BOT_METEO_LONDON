from scipy.stats import norm
from utils.logger import log
from cities import CITIES
from weather import open_meteo, wunderground
from weather.ensemble import get_ensemble_forecasts, build_probability_from_ensemble
from config import MAX_UNCERTAINTY_SPREAD_C

DEFAULT_CITY_CONFIG = {"id": "london", **CITIES["london"]}

# Écart-type par horizon de prévision (fallback si l'API Ensemble échoue)
SIGMA_BY_HORIZON = {
    0: 0.5,   # J   — aujourd'hui (très fiable)
    1: 1.0,   # J+1 — demain
    2: 1.5,   # J+2 — après-demain
}


def get_sigma_for_horizon(days_ahead: int) -> float:
    """Return the standard deviation for a given forecast horizon."""
    return SIGMA_BY_HORIZON.get(days_ahead, 2.0)


def _celsius_to_fahrenheit(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def _temp_unit_symbol(unit: str) -> str:
    return "\u00b0F" if unit.lower() == "fahrenheit" else "\u00b0C"


def _tranche_probability(dist, tranche: str) -> float:
    """Probability mass for one tranche label over a discrete rounded temp market."""
    label = tranche.strip()

    try:
        if label.endswith("-"):
            threshold = int(label[:-1])
            return dist.cdf(threshold + 0.5)

        if label.endswith("+"):
            threshold = int(label[:-1])
            return 1 - dist.cdf(threshold - 0.5)

        # US style range, e.g. "38-39"
        if "-" in label:
            low_str, high_str = label.split("-", 1)
            if low_str and high_str:
                low = int(low_str)
                high = int(high_str)
                return dist.cdf(high + 0.5) - dist.cdf(low - 0.5)

        temp = int(label)
        return dist.cdf(temp + 0.5) - dist.cdf(temp - 0.5)
    except ValueError:
        return 0.0


def build_probability_distribution_gaussian(
    forecast_temp: float,
    sigma: float,
    tranches: list[str],
    unit: str = "celsius",
) -> dict[str, float]:
    """
    Build a probability distribution over Polymarket temperature tranches
    using a Gaussian (normal) distribution.

    This is the FALLBACK method — used only if the Ensemble API fails.
    """
    use_fahrenheit = unit.lower() == "fahrenheit"
    forecast_temp_local = _celsius_to_fahrenheit(forecast_temp) if use_fahrenheit else forecast_temp
    sigma_local = sigma * 9.0 / 5.0 if use_fahrenheit else sigma

    dist = norm(loc=forecast_temp_local, scale=sigma_local)
    probabilities = {}

    for tranche in tranches:
        prob = _tranche_probability(dist, tranche)
        probabilities[tranche] = float(round(prob, 4))

    return probabilities


# Keep the old name as an alias for backward compatibility
build_probability_distribution = build_probability_distribution_gaussian


def get_probability_distribution(
    target_date: str, tranches: list[str], days_ahead: int,
    forecast_temp: float | None = None,
    city_config: dict | None = None,
) -> tuple[dict[str, float], dict]:
    """
    Compute the probability distribution for a target date.

    Strategy:
        1. Try the Ensemble API (51 ECMWF members) → real distribution
        2. Fallback to Gaussian if ensemble fails

    Args:
        target_date:   ISO date string (e.g. "2026-02-18")
        tranches:      list of market tranche labels
        days_ahead:    forecast horizon in days (0, 1, 2)
        forecast_temp: weighted average temp (needed for Gaussian fallback)

    Returns:
        (probabilities dict, source_info dict with keys: method, members,
         spread_min, spread_max, mean_temp, sigma)
    """
    city_config = city_config or DEFAULT_CITY_CONFIG
    unit = city_config.get("unit", "celsius").lower()
    unit_symbol = _temp_unit_symbol(unit)

    # --- 1) Try Ensemble API ---
    try:
        ensemble_data = get_ensemble_forecasts(
            lat=city_config["lat"],
            lon=city_config["lon"],
            timezone=city_config.get("timezone", "Europe/London"),
            days=max(days_ahead + 1, 3),
        )
        if ensemble_data and target_date in ensemble_data:
            member_temps = ensemble_data[target_date]
            if len(member_temps) >= 10:  # need enough members
                probs = build_probability_from_ensemble(
                    member_temps, tranches, unit=unit,
                    city_id=city_config.get("id"),
                )
                member_temps_local = [
                    _celsius_to_fahrenheit(temp) if unit == "fahrenheit" else temp
                    for temp in member_temps
                ]
                mean_temp = sum(member_temps_local) / len(member_temps_local)
                spread_min = min(member_temps_local)
                spread_max = max(member_temps_local)
                log(
                    f"Ensemble: {len(member_temps)} membres, "
                    f"moyenne={mean_temp:.1f}{unit_symbol}, "
                    f"spread={spread_max - spread_min:.1f}{unit_symbol}"
                )
                source_info = {
                    "method": "ensemble",
                    "members": len(member_temps),
                    "spread_min": round(spread_min, 1),
                    "spread_max": round(spread_max, 1),
                    "mean_temp": round(mean_temp, 1),
                    "sigma": None,
                    "unit": unit,
                }
                return probs, source_info
            else:
                log(f"Ensemble: seulement {len(member_temps)} membres, fallback gaussienne", "warning")
    except Exception as e:
        log(f"Ensemble API échouée: {e} — fallback gaussienne", "warning")

    # --- 2) Fallback: Gaussian ---
    if forecast_temp is None:
        log("Pas de forecast_temp pour le fallback gaussien", "error")
        source_info = {"method": "gaussian", "members": 0, "spread_min": None,
                       "spread_max": None, "mean_temp": forecast_temp, "sigma": None, "unit": unit}
        return {t: 0.0 for t in tranches}, source_info

    sigma_c = get_sigma_for_horizon(days_ahead)
    probs = build_probability_distribution_gaussian(
        forecast_temp,
        sigma_c,
        tranches,
        unit=unit,
    )
    display_temp = _celsius_to_fahrenheit(forecast_temp) if unit == "fahrenheit" else forecast_temp
    display_sigma = sigma_c * 9.0 / 5.0 if unit == "fahrenheit" else sigma_c
    log(f"Gaussienne (fallback): μ={display_temp:.1f}{unit_symbol}, σ={display_sigma:.1f}{unit_symbol}")
    source_info = {
        "method": "gaussian",
        "members": 0,
        "spread_min": None,
        "spread_max": None,
        "mean_temp": round(display_temp, 1),
        "sigma": round(display_sigma, 2),
        "unit": unit,
    }
    return probs, source_info


def get_weather_forecasts(target_date: str, city_config: dict) -> dict:
    """
    Gather forecasts from all available sources for a given date.

    Returns:
        {
            "open_meteo": {"max_temp": float, "min_temp": float} | None,
            "wunderground": {"max_temp": float, "min_temp": float} | None,
        }
    """
    result = {"open_meteo": None, "wunderground": None}

    # Open-Meteo
    om_data = open_meteo.get_forecasts(
        lat=city_config["lat"],
        lon=city_config["lon"],
        timezone=city_config.get("timezone", "Europe/London"),
    )
    if om_data and target_date in om_data:
        result["open_meteo"] = om_data[target_date]

    # Weather Underground (may return None — that's fine)
    wu_data = wunderground.get_forecasts(
        lat=city_config["lat"],
        lon=city_config["lon"],
    )
    if wu_data and target_date in wu_data:
        result["wunderground"] = wu_data[target_date]

    return result


def sources_diverge_too_much(forecasts: dict) -> bool:
    """
    Check if weather sources diverge by more than MAX_UNCERTAINTY_SPREAD_C.
    If only one source is available, we can't compare — return False.
    """
    om = forecasts.get("open_meteo")
    wu = forecasts.get("wunderground")

    if om is None or wu is None:
        return False

    spread = abs(om["max_temp"] - wu["max_temp"])
    if spread > MAX_UNCERTAINTY_SPREAD_C:
        log(f"Sources divergent de {spread:.1f}°C (max autorisé: {MAX_UNCERTAINTY_SPREAD_C}°C)", "warning")
        return True

    return False


def average_forecast(forecasts: dict) -> float | None:
    """
    Compute weighted average max_temp across available sources.

    Weights (when both available):
        - Weather Underground: 60% (source de résolution Polymarket)
        - Open-Meteo: 40%

    Falls back to whichever single source is available.

    Returns:
        Weighted max temperature, or None if no source is available.
    """
    wu = forecasts.get("wunderground")
    om = forecasts.get("open_meteo")

    if wu is not None and om is not None:
        avg = wu["max_temp"] * 0.6 + om["max_temp"] * 0.4
        log(
            f"Température pondérée: {avg:.1f}°C "
            f"(WU={wu['max_temp']}°C×60% + OM={om['max_temp']}°C×40%)"
        )
        return avg

    if wu is not None:
        log(f"Température WU seule: {wu['max_temp']:.1f}°C")
        return wu["max_temp"]

    if om is not None:
        log(f"Température Open-Meteo seule (fallback): {om['max_temp']:.1f}°C")
        return om["max_temp"]

    log("Aucune source météo disponible", "error")
    return None
