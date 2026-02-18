"""
Results tracker — verify bot predictions against actual temperatures.

Checks resolved markets from previous days against actual max temperature
data and logs whether the bot's prediction would have won.
"""

import json
import os
from datetime import datetime, date, timedelta

import requests
from bs4 import BeautifulSoup

from config import LONDON_CITY_AIRPORT_LAT, LONDON_CITY_AIRPORT_LON
from utils.logger import log
from notifications.telegram import send_telegram

RESULTS_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_log.json")
BETS_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bets_history.json")


# ---------------------------------------------------------------------------
# Actual temperature retrieval
# ---------------------------------------------------------------------------

def get_actual_temperature_open_meteo(target_date: str) -> float | None:
    """
    Fetch actual max temperature from Open-Meteo archive API for a past date.

    Args:
        target_date: date string in YYYY-MM-DD format

    Returns:
        Max temperature in °C, or None on failure.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LONDON_CITY_AIRPORT_LAT,
        "longitude": LONDON_CITY_AIRPORT_LON,
        "start_date": target_date,
        "end_date": target_date,
        "daily": "temperature_2m_max",
        "timezone": "Europe/London",
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        max_temps = data.get("daily", {}).get("temperature_2m_max", [])
        if max_temps and max_temps[0] is not None:
            temp = float(max_temps[0])
            log(f"Open-Meteo archive: temp max réelle pour {target_date} = {temp}°C")
            return temp

        log(f"Open-Meteo archive: pas de données pour {target_date}", "warning")
        return None

    except requests.RequestException as e:
        log(f"Open-Meteo archive: erreur — {e}", "error")
        return None


def get_actual_temperature_wunderground(target_date: str) -> float | None:
    """
    Attempt to scrape actual max temperature from Weather Underground history page.

    Note: WU loads data via JS, so basic scraping often fails.
    This tries to extract data from embedded JSON in the page source.

    Args:
        target_date: date string in YYYY-MM-DD format

    Returns:
        Max temperature in °C, or None on failure.
    """
    d = date.fromisoformat(target_date)
    url = f"https://www.wunderground.com/history/daily/gb/london/EGLC/date/{d.year}-{d.month}-{d.day}"

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

        # Try to find temperature data in embedded script tags
        soup = BeautifulSoup(response.text, "html.parser")

        # WU sometimes embeds data in a lib-city-history-observation element
        for script in soup.find_all("script"):
            text = script.string or ""
            if "temperature" in text.lower() and "max" in text.lower():
                # Try to parse embedded JSON
                import re
                match = re.search(r'"maxTempC"\s*:\s*([\d.]+)', text)
                if match:
                    temp = float(match.group(1))
                    log(f"Weather Underground: temp max réelle pour {target_date} = {temp}°C")
                    return temp

        log(f"Weather Underground: scraping échec pour {target_date} (données JS non disponibles)", "warning")
        return None

    except requests.RequestException as e:
        log(f"Weather Underground: erreur scraping {target_date} — {e}", "warning")
        return None


def get_actual_temperature(target_date: str) -> float | None:
    """
    Get the actual max temperature for a past date.
    Tries Weather Underground first (official resolution source),
    falls back to Open-Meteo archive.
    """
    # Try WU first (official source)
    temp = get_actual_temperature_wunderground(target_date)
    if temp is not None:
        return temp

    # Fallback to Open-Meteo archive
    return get_actual_temperature_open_meteo(target_date)


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


def already_checked(target_date: str) -> bool:
    """Check if we already have a result for this date."""
    results = load_results_log()
    return any(r["date"] == target_date for r in results)


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
        if label.endswith("-"):
            threshold = int(label[:-1])
            if actual_temp_rounded <= threshold:
                return label
        elif label.endswith("+"):
            threshold = int(label[:-1])
            if actual_temp_rounded >= threshold:
                return label
        else:
            if actual_temp_rounded == int(label):
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

    for market_date, bet_info in history.items():
        # Skip if already checked
        if already_checked(market_date):
            continue

        # Only check past dates (resolved markets)
        try:
            target = date.fromisoformat(market_date)
        except ValueError:
            continue

        if target >= today:
            continue  # Market not yet resolved

        log(f"📊 Vérification du résultat pour {market_date}...")

        # Get actual temperature
        actual_temp = get_actual_temperature(market_date)
        if actual_temp is None:
            log(f"Results tracker: impossible de récupérer la temp réelle pour {market_date}", "warning")
            continue

        actual_rounded = round(actual_temp)
        bot_prediction = bet_info.get("tranche", "?")

        # Determine if prediction was correct
        would_have_won = str(actual_rounded) == bot_prediction
        # Also check edge tranches (e.g. "14+" means >=14, "8-" means <=8)
        if bot_prediction.endswith("+") and actual_rounded >= int(bot_prediction[:-1]):
            would_have_won = True
        elif bot_prediction.endswith("-") and actual_rounded <= int(bot_prediction[:-1]):
            would_have_won = True

        result_entry = {
            "date": market_date,
            "forecast_temp": bet_info.get("forecast_temp"),
            "bot_prediction": f"{bot_prediction}°C",
            "bot_probability": bet_info.get("our_probability"),
            "market_price_at_bet": bet_info.get("price_paid"),
            "actual_temp_raw": actual_temp,
            "actual_result": f"{actual_rounded}°C",
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
            f"{emoji} *Résultat {market_date}*\n"
            f"Temp réelle: {actual_rounded}°C ({actual_temp:.1f}°C)\n"
            f"Prédiction bot: {bot_prediction}°C (proba: {bet_info.get('our_probability', 0):.0%})\n"
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
