import requests
from utils.logger import log
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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


def notify_scan_no_edge(market_date: str):
    send_telegram(f"🔍 Scan effectué — Aucun edge trouvé pour le {market_date}")


def notify_bet_placed(amount: float, tranche: str, market_date: str, edge: float, our_prob: float, market_price: float,
                      source_summary: str = "", forecast_temp: float = None):
    forecast_str = f"{forecast_temp:.1f}°C" if forecast_temp is not None else "N/A"
    send_telegram(
        f"✅ *PARI PLACÉ* : {amount:.2f}$ sur {tranche}°C pour le {market_date} "
        f"(edge: {edge:.0%}, notre proba: {our_prob:.0%} vs marché: {market_price:.2f})\n"
        f"📊 Source: {source_summary} | Prévision: {forecast_str} | "
        f"Pari: {tranche}°C @ {market_price:.2f} (Kelly: {amount:.2f}$)"
    )


def notify_uncertainty(market_date: str, spread: float):
    send_telegram(f"⚠️ Incertitude trop grande pour le {market_date} — écart entre sources: {spread:.1f}°C")


def notify_dry_run_bet(amount: float, tranche: str, market_date: str, edge: float, our_prob: float, market_price: float,
                       source_summary: str = "", forecast_temp: float = None):
    forecast_str = f"{forecast_temp:.1f}°C" if forecast_temp is not None else "N/A"
    send_telegram(
        f"🧪 *DRY RUN* — Pari simulé : {amount:.2f}$ sur {tranche}°C pour le {market_date} "
        f"(edge: {edge:.0%}, notre proba: {our_prob:.0%} vs marché: {market_price:.2f})\n"
        f"📊 Source: {source_summary} | Prévision: {forecast_str} | "
        f"Pari: {tranche}°C @ {market_price:.2f} (Kelly: {amount:.2f}$)\n"
        f"_Aucun ordre réel placé_"
    )


def notify_error(detail: str):
    send_telegram(f"❌ Erreur : {detail}")
