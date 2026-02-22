"""
Results tracker — verify bot predictions against actual temperatures.

Checks resolved markets from previous days against actual max temperature
data and logs whether the bot's prediction would have won.
"""

import json
import math
import os
import re
from datetime import datetime, date

import requests

from cities import CITIES
from utils.logger import log
from notifications.telegram import send_telegram

RESULTS_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_log.json")
BETS_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bets_history.json")


def _unit_symbol(unit: str) -> str:
    return "\u00b0F" if unit.lower() == "fahrenheit" else "\u00b0C"


def _celsius_to_fahrenheit(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def _round_half_up(temp: float) -> int:
    if temp >= 0:
        return int(math.floor(temp + 0.5))
    return int(math.ceil(temp - 0.5))


def _temp_matches_tranche(rounded_temp: int, tranche_label: str) -> bool:
    label = _normalize_tranche_label(tranche_label)

    try:
        if label.endswith("-"):
            threshold = int(label[:-1])
            return rounded_temp <= threshold

        if label.endswith("+"):
            threshold = int(label[:-1])
            return rounded_temp >= threshold

        if "-" in label:
            low_str, high_str = label.split("-", 1)
            if low_str and high_str:
                low = int(low_str)
                high = int(high_str)
                return low <= rounded_temp <= high

        return rounded_temp == int(label)
    except ValueError:
        return False


def _normalize_tranche_label(label: str) -> str:
    normalized = label.strip().lower().replace(" ", "").replace("°", "")
    if normalized.endswith("c") or normalized.endswith("f"):
        normalized = normalized[:-1]
    return normalized


def _extract_city_and_date(market_key: str, bet_info: dict) -> tuple[str, str]:
    """
    Return (city_id, market_date) from bet record.

    Supports both new keys (city_date) and legacy keys (date only).
    """
    city_id = (bet_info.get("city_id") or "").strip().lower()
    market_date = (bet_info.get("market_date") or "").strip()

    if market_date:
        return city_id or "london", market_date

    if isinstance(market_key, str) and "_" in market_key:
        maybe_city, maybe_date = market_key.split("_", 1)
        if maybe_city in CITIES:
            return city_id or maybe_city, maybe_date

    return city_id or "london", str(market_key)


# ---------------------------------------------------------------------------
# Actual temperature retrieval
# ---------------------------------------------------------------------------

def get_actual_temperature_open_meteo(target_date: str, city_config: dict) -> float | None:
    """
    Fetch actual max temperature from Open-Meteo archive API for a past date.

    Args:
        target_date: date string in YYYY-MM-DD format

    Returns:
        Max temperature in city market unit, or None on failure.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    unit = city_config.get("unit", "celsius")
    unit_symbol = _unit_symbol(unit)
    params = {
        "latitude": city_config["lat"],
        "longitude": city_config["lon"],
        "start_date": target_date,
        "end_date": target_date,
        "daily": "temperature_2m_max",
        "timezone": city_config.get("timezone", "Europe/London"),
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        max_temps = data.get("daily", {}).get("temperature_2m_max", [])
        if max_temps and max_temps[0] is not None:
            temp_c = float(max_temps[0])
            temp = _celsius_to_fahrenheit(temp_c) if unit == "fahrenheit" else temp_c
            log(
                f"Open-Meteo archive [{city_config['name']}]: "
                f"temp max réelle pour {target_date} = {temp:.1f}{unit_symbol}"
            )
            return temp

        log(f"Open-Meteo archive: pas de données pour {target_date}", "warning")
        return None

    except requests.RequestException as e:
        log(f"Open-Meteo archive: erreur — {e}", "error")
        return None


def get_actual_temperature_wunderground(target_date: str, city_config: dict) -> float | None:
    """
    Attempt to scrape actual max temperature from Weather Underground history page.

    Note: WU loads data via JS, so basic scraping often fails.
    This tries to extract data from embedded JSON in the page source.

    Args:
        target_date: date string in YYYY-MM-DD format

    Returns:
        Max temperature in city market unit, or None on failure.
    """
    d = date.fromisoformat(target_date)
    base_url = city_config.get("wu_history_url")
    if not base_url:
        return None

    url = f"{base_url}/date/{d.year}-{d.month}-{d.day}"
    unit = city_config.get("unit", "celsius")
    unit_symbol = _unit_symbol(unit)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        match_c = re.search(r'"maxTempC"\s*:\s*(-?[\d.]+)', response.text)
        match_f = re.search(r'"maxTempF"\s*:\s*(-?[\d.]+)', response.text)

        temp_c = float(match_c.group(1)) if match_c else None
        temp_f = float(match_f.group(1)) if match_f else None

        if unit == "fahrenheit":
            if temp_f is not None:
                log(
                    f"Weather Underground [{city_config['name']}]: "
                    f"temp max réelle pour {target_date} = {temp_f:.1f}{unit_symbol}"
                )
                return temp_f
            if temp_c is not None:
                converted = _celsius_to_fahrenheit(temp_c)
                log(
                    f"Weather Underground [{city_config['name']}]: "
                    f"temp max réelle convertie pour {target_date} = {converted:.1f}{unit_symbol}"
                )
                return converted
        else:
            if temp_c is not None:
                log(
                    f"Weather Underground [{city_config['name']}]: "
                    f"temp max réelle pour {target_date} = {temp_c:.1f}{unit_symbol}"
                )
                return temp_c
            if temp_f is not None:
                converted = (temp_f - 32.0) * 5.0 / 9.0
                log(
                    f"Weather Underground [{city_config['name']}]: "
                    f"temp max réelle convertie pour {target_date} = {converted:.1f}{unit_symbol}"
                )
                return converted

        log(f"Weather Underground: scraping échec pour {target_date} (données JS non disponibles)", "warning")
        return None

    except requests.RequestException as e:
        log(f"Weather Underground: erreur scraping {target_date} — {e}", "warning")
        return None


def get_actual_temperature(target_date: str, city_config: dict) -> float | None:
    """
    Get the actual max temperature for a past date.
    Tries Weather Underground first (official resolution source),
    falls back to Open-Meteo archive.
    """
    # Try WU first (official source)
    temp = get_actual_temperature_wunderground(target_date, city_config)
    if temp is not None:
        return temp

    # Fallback to Open-Meteo archive
    return get_actual_temperature_open_meteo(target_date, city_config)


# ---------------------------------------------------------------------------
# Results log management
# ---------------------------------------------------------------------------

def load_results_log() -> list[dict]:
    """Load results log from JSON file."""
    if not os.path.exists(RESULTS_LOG_FILE):
        return []
    try:
        with open(RESULTS_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_results_log(results: list[dict]):
    """Save results log to JSON file."""
    with open(RESULTS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)


def load_bets_history() -> dict:
    """Load bet history from JSON file."""
    if not os.path.exists(BETS_HISTORY_FILE):
        return {}
    try:
        with open(BETS_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def already_checked(target_date: str, city_id: str) -> bool:
    """Check if we already have a result for this city/date pair."""
    results = load_results_log()
    return any(
        r.get("date") == target_date and r.get("city_id", "london") == city_id
        for r in results
    )


def determine_winning_tranche(actual_temp_rounded: int, tranches_labels: list[str]) -> str:
    """
    Determine which tranche label matches the actual temperature.

    Args:
        actual_temp_rounded: rounded integer temperature
        tranches_labels: list of tranche labels like ["8-", "9", "10", ..., "14+"]

    Returns:
        The matching tranche label.
    """
    for label in tranches_labels:
        if _temp_matches_tranche(actual_temp_rounded, label):
            return label

    return f"{actual_temp_rounded}"


# ---------------------------------------------------------------------------
# Main check function
# ---------------------------------------------------------------------------

def check_yesterday_results():
    """
    Check results for any past bets/simulations that haven't been verified yet.
    Looks at bets_history.json for predictions and compares with actual temperatures.
    """
    history = load_bets_history()
    if not history:
        log("Results tracker: aucun pari/simulation à vérifier")
        return

    today = date.today()
    checked_count = 0

    for market_key, bet_info in history.items():
        city_id, market_date = _extract_city_and_date(market_key, bet_info)
        city_config = CITIES.get(city_id)
        if city_config is None:
            log(f"Results tracker: city_id inconnu '{city_id}' pour {market_key}", "warning")
            continue

        city_name = city_config.get("name", city_id)
        unit = city_config.get("unit", "celsius")
        unit_symbol = _unit_symbol(unit)

        # Skip if already checked
        if already_checked(market_date, city_id):
            continue

        # Only check past dates (resolved markets)
        try:
            target = date.fromisoformat(market_date)
        except ValueError:
            continue

        if target >= today:
            continue  # Market not yet resolved

        log(f"📊 Vérification du résultat pour {city_name} {market_date}...")

        # Get actual temperature
        actual_temp = get_actual_temperature(market_date, city_config)
        if actual_temp is None:
            log(
                f"Results tracker: impossible de récupérer la temp réelle pour {city_name} {market_date}",
                "warning",
            )
            continue

        actual_rounded = _round_half_up(actual_temp)
        bot_prediction = _normalize_tranche_label(str(bet_info.get("tranche", "?")).strip())
        forecast_temp = bet_info.get("forecast_temp")
        if forecast_temp is not None and unit == "fahrenheit":
            forecast_temp = _celsius_to_fahrenheit(float(forecast_temp))

        # Determine if prediction was correct
        would_have_won = _temp_matches_tranche(actual_rounded, bot_prediction)

        result_entry = {
            "market_key": market_key,
            "city_id": city_id,
            "city_name": city_name,
            "date": market_date,
            "unit": unit,
            "forecast_temp": round(float(forecast_temp), 1) if forecast_temp is not None else None,
            "bot_prediction": f"{bot_prediction}{unit_symbol}",
            "bot_probability": bet_info.get("our_probability"),
            "market_price_at_bet": bet_info.get("price_paid"),
            "actual_temp_raw": actual_temp,
            "actual_result": f"{actual_rounded}{unit_symbol}",
            "would_have_won": would_have_won,
            "status": bet_info.get("status", "unknown"),
            "checked_at": datetime.now().isoformat(),
        }

        # Save to results log
        results = load_results_log()
        results.append(result_entry)
        save_results_log(results)

        # Log and notify
        emoji = "✅" if would_have_won else "❌"
        msg = (
            f"{emoji} *Résultat {city_name} — {market_date}*\n"
            f"Temp réelle: {actual_rounded}{unit_symbol} ({actual_temp:.1f}{unit_symbol})\n"
            f"Prédiction bot: {bot_prediction}{unit_symbol} (proba: {bet_info.get('our_probability', 0):.0%})\n"
            f"Prix marché: {bet_info.get('price_paid', 0):.2f}\n"
            f"Résultat: {'GAGNÉ ✅' if would_have_won else 'PERDU ❌'}"
        )
        log(msg.replace("*", "").replace("\n", " | "))
        send_telegram(msg)

        checked_count += 1

    if checked_count > 0:
        log(f"📊 {checked_count} résultat(s) vérifié(s)")
    else:
        log("📊 Aucun nouveau résultat à vérifier")
