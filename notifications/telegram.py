import requests
from utils.logger import log
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _unit_symbol(unit: str) -> str:
    return "\u00b0F" if unit.lower() == "fahrenheit" else "\u00b0C"


def _celsius_to_fahrenheit(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def _format_forecast_temp(forecast_temp_c: float | None, unit: str) -> str:
    if forecast_temp_c is None:
        return "N/A"
    value = _celsius_to_fahrenheit(forecast_temp_c) if unit.lower() == "fahrenheit" else forecast_temp_c
    return f"{value:.1f}{_unit_symbol(unit)}"


def _format_tranche(tranche: str, unit: str) -> str:
    return f"{tranche}{_unit_symbol(unit)}"


def send_telegram(message: str, token: str = None, chat_id: str = None) -> bool:
    """
    Send a message via Telegram bot.

    Args:
        message: text to send (supports Markdown)
        token: bot token (defaults to config)
        chat_id: chat ID (defaults to config)

    Returns:
        True if sent successfully, False otherwise.
    """
    token = token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log("Telegram: token ou chat_id non configuré, notification ignorée", "warning")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        log("Telegram: message envoyé")
        return True
    except requests.RequestException as e:
        log(f"Telegram: erreur envoi — {e}", "error")
        return False


def notify_scan_no_edge(market_date: str, city_name: str = ""):
    city_suffix = f" — {city_name}" if city_name else ""
    send_telegram(f"🔍 Scan effectué{city_suffix} — Aucun edge trouvé pour le {market_date}")


def notify_bet_placed(
    amount: float,
    tranche: str,
    market_date: str,
    edge: float,
    our_prob: float,
    market_price: float,
    source_summary: str = "",
    forecast_temp: float = None,
    city_name: str = "London",
    unit: str = "celsius",
):
    forecast_str = _format_forecast_temp(forecast_temp, unit)
    tranche_str = _format_tranche(tranche, unit)
    send_telegram(
        f"✅ *PARI PLACÉ — {city_name}*\n"
        f"{amount:.2f}$ sur {tranche_str} @ {market_price:.2f} "
        f"(edge: {edge:.0%}, notre proba: {our_prob:.0%})\n"
        f"Date: {market_date}\n"
        f"📊 Source: {source_summary} | Prévision: {forecast_str}"
    )


def notify_uncertainty(market_date: str, spread: float, city_name: str = "", unit: str = "celsius"):
    spread_value = spread * 9.0 / 5.0 if unit.lower() == "fahrenheit" else spread
    city_suffix = f" — {city_name}" if city_name else ""
    send_telegram(
        f"⚠️ Incertitude trop grande{city_suffix} pour le {market_date} "
        f"— écart entre sources: {spread_value:.1f}{_unit_symbol(unit)}"
    )


def notify_dry_run_bet(
    amount: float,
    tranche: str,
    market_date: str,
    edge: float,
    our_prob: float,
    market_price: float,
    source_summary: str = "",
    forecast_temp: float = None,
    city_name: str = "London",
    unit: str = "celsius",
):
    forecast_str = _format_forecast_temp(forecast_temp, unit)
    tranche_str = _format_tranche(tranche, unit)
    send_telegram(
        f"🧪 *DRY RUN — {city_name}*\n"
        f"{amount:.2f}$ sur {tranche_str} @ {market_price:.2f} "
        f"(edge: {edge:.0%}, notre proba: {our_prob:.0%})\n"
        f"Date: {market_date}\n"
        f"📊 Source: {source_summary} | Prévision: {forecast_str}\n"
        f"_Aucun ordre réel placé_"
    )


def notify_bet_failed(
    amount: float,
    tranche: str,
    market_date: str,
    error_detail: str,
    source_summary: str = "",
    forecast_temp: float = None,
    city_name: str = "London",
    unit: str = "celsius",
):
    forecast_str = _format_forecast_temp(forecast_temp, unit)
    tranche_str = _format_tranche(tranche, unit)
    send_telegram(
        f"❌ *ÉCHEC ORDRE — {city_name}*\n"
        f"{amount:.2f}$ sur {tranche_str} pour le {market_date}\n"
        f"Erreur: {error_detail}\n"
        f"📊 Source: {source_summary} | Prévision: {forecast_str}"
    )


def notify_heartbeat(last_scan_time: str, markets_summary: str):
    send_telegram(
        f"🔄 Bot actif — dernier scan : {last_scan_time} — {markets_summary}"
    )


def notify_error(detail: str):
    send_telegram(f"❌ Erreur : {detail}")
