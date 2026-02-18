from datetime import datetime, date
from scipy.stats import norm
from utils.logger import log
from weather import open_meteo, wunderground
from weather.ensemble import get_ensemble_forecasts, build_probability_from_ensemble
from config import MAX_UNCERTAINTY_SPREAD_C

# Écart-type par horizon de prévision (fallback si l'API Ensemble échoue)
SIGMA_BY_HORIZON = {
    0: 0.5,   # J   — aujourd'hui (très fiable)
    1: 1.0,   # J+1 — demain
    2: 1.5,   # J+2 — après-demain
}


def get_sigma_for_horizon(days_ahead: int) -> float:
    """Return the standard deviation for a given forecast horizon."""
    return SIGMA_BY_HORIZON.get(days_ahead, 2.0)


def build_probability_distribution_gaussian(
    forecast_temp: float, sigma: float, tranches: list[str]
) -> dict[str, float]:
    """
    Build a probability distribution over Polymarket temperature tranches
    using a Gaussian (normal) distribution.

    This is the FALLBACK method — used only if the Ensemble API fails.
    """
    dist = norm(loc=forecast_temp, scale=sigma)
    probabilities = {}

    for tranche in tranches:
        if tranche.endswith("-"):  # "8°C or below"
            threshold = int(tranche[:-1])
            prob = dist.cdf(threshold + 0.5)
        elif tranche.endswith("+"):  # "14°C or higher"
            threshold = int(tranche[:-1])
            prob = 1 - dist.cdf(threshold - 0.5)
        else:  # "12°C" exact
            temp = int(tranche)
            prob = dist.cdf(temp + 0.5) - dist.cdf(temp - 0.5)
        probabilities[tranche] = round(prob, 4)

    return probabilities


# Keep the old name as an alias for backward compatibility
build_probability_distribution = build_probability_distribution_gaussian


def get_probability_distribution(
    target_date: str, tranches: list[str], days_ahead: int,
    forecast_temp: float | None = None,
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
    # --- 1) Try Ensemble API ---
    try:
        ensemble_data = get_ensemble_forecasts(days=max(days_ahead + 1, 3))
        if ensemble_data and target_date in ensemble_data:
            member_temps = ensemble_data[target_date]
            if len(member_temps) >= 10:  # need enough members
                probs = build_probability_from_ensemble(member_temps, tranches)
                mean_temp = sum(member_temps) / len(member_temps)
                spread_min = min(member_temps)
                spread_max = max(member_temps)
                log(
                    f"Ensemble: {len(member_temps)} membres, "
                    f"moyenne={mean_temp:.1f}°C, spread={spread_max - spread_min:.1f}°C"
                )
                source_info = {
                    "method": "ensemble",
                    "members": len(member_temps),
                    "spread_min": round(spread_min, 1),
                    "spread_max": round(spread_max, 1),
                    "mean_temp": round(mean_temp, 1),
                    "sigma": None,
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
                       "spread_max": None, "mean_temp": forecast_temp, "sigma": None}
        return {t: 0.0 for t in tranches}, source_info

    sigma = get_sigma_for_horizon(days_ahead)
    probs = build_probability_distribution_gaussian(forecast_temp, sigma, tranches)
    log(f"Gaussienne (fallback): μ={forecast_temp:.1f}°C, σ={sigma}")
    source_info = {
        "method": "gaussian",
        "members": 0,
        "spread_min": None,
        "spread_max": None,
        "mean_temp": round(forecast_temp, 1),
        "sigma": sigma,
    }
    return probs, source_info


def get_weather_forecasts(target_date: str) -> dict:
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
    om_data = open_meteo.get_forecasts()
    if om_data and target_date in om_data:
        result["open_meteo"] = om_data[target_date]

    # Weather Underground (may return None — that's fine)
    wu_data = wunderground.get_forecasts()
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
