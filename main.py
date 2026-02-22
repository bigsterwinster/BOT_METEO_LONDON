import json
import os
import time
import traceback
from datetime import datetime, date, timedelta

import schedule

from config import (
    CHECK_INTERVAL_HOURS, MAX_BET_USDC, MIN_EDGE_PERCENT,
    DRY_RUN, BANKROLL, KELLY_FRACTION,
)
from utils.logger import log
from weather.analyzer import (
    get_weather_forecasts,
    sources_diverge_too_much,
    average_forecast,
    get_probability_distribution,
    get_sigma_for_horizon,
)
from polymarket.client import create_client
from polymarket.markets import find_london_temperature_markets, get_all_market_prices
from polymarket.trader import place_bet
from strategy.edge_calculator import (
    find_best_bet,
    calculate_bet_size,
    get_min_edge_for_horizon,
)
from results_tracker import check_yesterday_results
from notifications.telegram import (
    send_telegram,
    notify_scan_no_edge,
    notify_bet_placed,
    notify_bet_failed,
    notify_dry_run_bet,
    notify_uncertainty,
    notify_error,
    notify_heartbeat,
)

BETS_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bets_history.json")


# ---------------------------------------------------------------------------
# Amélioration 2 — Timing optimal des paris
# ---------------------------------------------------------------------------

def should_bet_on_market(market_date: str) -> tuple[bool, str]:
    """
    Determine if now is the right time to bet on a given market date.

    Rules:
      - J+0 (today):          bet only in the morning (before noon)
      - J+1 (tomorrow):       ALWAYS allowed (forecasts are reliable 24/7)
      - J+2 (day after):      daytime only (6h–22h, weather models update at 6h)
      - J+3+:                 too far ahead — skip
    """
    now = datetime.now()
    try:
        target = date.fromisoformat(market_date)
    except ValueError:
        return False, "invalid_date"

    days_ahead = (target - now.date()).days
    hour = now.hour

    if days_ahead < 0:
        return False, "past"

    if days_ahead == 0:
        # Jour même : seulement avant midi (après, le marché est efficient)
        return hour < 12, "j0_morning_only"

    if days_ahead == 1:
        # Demain : TOUJOURS autorisé (les prévisions J+1 sont fiables 24h/24)
        return True, "j1_always"

    if days_ahead == 2:
        # J+2 : autorisé entre 6h et 22h (les cotes sont molles, on veut en profiter)
        return 6 <= hour <= 22, "j2_daytime"

    return False, "too_far"


# ---------------------------------------------------------------------------
# Bet history tracker
# ---------------------------------------------------------------------------

def load_bets_history() -> dict:
    """Load bet history from JSON file."""
    if not os.path.exists(BETS_HISTORY_FILE):
        return {}
    try:
        with open(BETS_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_bets_history(history: dict):
    """Save bet history to JSON file."""
    with open(BETS_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4, ensure_ascii=False)


def already_bet_on(market_date: str, days_ahead: int) -> bool:
    """
    Check if we already placed a bet on this market date for this horizon.

    Allows retry: a failed bet does NOT block a new attempt.
    """
    history = load_bets_history()
    if market_date not in history:
        return False

    previous_bet = history[market_date]

    # Allow retry if previous bet failed
    if previous_bet.get("status") == "failed":
        log(
            f"🔁 Pari précédent ÉCHOUÉ pour {market_date}, "
            f"nouvelle tentative autorisée"
        )
        return False

    return True



def record_bet(market_date: str, bet_info: dict, order_response: dict | None,
               forecast_temp: float | None = None, status: str = "placed",
               days_ahead: int = None, bet_amount: float = None,
               method: str = "gaussian"):
    """Record a placed or simulated bet in the history file."""
    history = load_bets_history()
    history[market_date] = {
        "tranche": bet_info["tranche"],
        "amount_usdc": bet_amount or MAX_BET_USDC,
        "price_paid": bet_info["market_price"],
        "our_probability": bet_info["our_probability"],
        "edge": bet_info["edge"],
        "forecast_temp": forecast_temp,
        "days_ahead": days_ahead,
        "method": method,
        "timestamp": datetime.now().isoformat(),
        "order_id": str(order_response) if order_response else "none",
        "status": status,
    }
    save_bets_history(history)
    log(f"Pari enregistré pour {market_date}: tranche {bet_info['tranche']} ({status})")


# ---------------------------------------------------------------------------
# Main bot loop
# ---------------------------------------------------------------------------

def run_bot():
    """Main scan loop: find markets, compute edge, place bets."""
    log("🔄 Démarrage du scan...")

    # 0. Check results from previous days
    try:
        check_yesterday_results()
    except Exception as e:
        log(f"Results tracker: erreur — {e}", "error")

    # Initialize Polymarket client
    polymarket_client = create_client()
    if polymarket_client is None:
        notify_error("Impossible d'initialiser le client Polymarket")
        log("Client Polymarket non disponible, scan annulé", "error")
        return

    # 1. Find open London temperature markets
    markets = find_london_temperature_markets()
    if not markets:
        log("Aucun marché température Londres trouvé")
        return

    for market in markets:
      try:
        market_date = market["date"]
        log(f"--- Analyse du marché {market_date} ({market['title']}) ---")

        # 1b. Calculate days_ahead
        today = date.today()
        try:
            target = date.fromisoformat(market_date)
        except ValueError:
            log(f"Date invalide: {market_date}", "error")
            continue

        days_ahead = (target - today).days
        if days_ahead < 0:
            log(f"Marché {market_date} déjà passé, skip")
            continue

        # 2. Amélioration 2 — Check timing
        should_bet, timing_reason = should_bet_on_market(market_date)
        if not should_bet:
            log(f"⏰ Pas le bon moment pour parier sur {market_date} ({timing_reason}), skip")
            continue

        # 3. Check if we already bet on this market (with reinforcement logic)
        if already_bet_on(market_date, days_ahead):
            log(f"⏭️ Déjà parié sur {market_date} (J+{days_ahead}), skip")
            continue

        # 4. Fetch weather forecasts
        forecasts = get_weather_forecasts(market_date)

        # 5. Check source coherence
        if sources_diverge_too_much(forecasts):
            om = forecasts.get("open_meteo")
            wu = forecasts.get("wunderground")
            spread = abs((om or {}).get("max_temp", 0) - (wu or {}).get("max_temp", 0))
            notify_uncertainty(market_date, spread)
            continue

        # 6. Compute forecast_temp (for Gaussian fallback)
        forecast_temp = average_forecast(forecasts)
        if forecast_temp is None:
            log(f"Pas de prévision disponible pour {market_date}, skip", "warning")
            continue

        # 7. Compute probability distribution (Ensemble first, Gaussian fallback)
        tranche_labels = [t["label"] for t in market["tranches"]]

        probabilities, source_info = get_probability_distribution(
            target_date=market_date,
            tranches=tranche_labels,
            days_ahead=days_ahead,
            forecast_temp=forecast_temp,
        )
        method = source_info["method"]
        log(f"Distribution ({method}): {probabilities}")

        # Build human-readable source summary for Telegram
        if method == "ensemble":
            source_summary = (
                f"Ensemble ({source_info['members']} membres, "
                f"spread {source_info['spread_min']}-{source_info['spread_max']}°C)"
            )
        else:
            source_summary = f"Gaussienne (σ={source_info['sigma']})"

        # 8. Fetch market prices
        market_prices = get_all_market_prices(polymarket_client, market)
        log(f"Prix marché: { {k: v['mid'] for k, v in market_prices.items()} }")

        # 9. Find best bet (with dynamic edge minimum — Amélioration 5)
        best_bet = find_best_bet(probabilities, market_prices, days_ahead=days_ahead)

        if best_bet is None:
            log(f"🔍 Aucun edge trouvé pour {market_date}")
            notify_scan_no_edge(market_date)
            continue

        # 10. Calculate bet size (Kelly Criterion — Amélioration 6)
        bet_amount = calculate_bet_size(
            our_prob=best_bet["our_probability"],
            market_price=best_bet["market_price"],
            bankroll=BANKROLL,
            max_bet=MAX_BET_USDC,
            kelly_fraction=KELLY_FRACTION,
        )

        if bet_amount <= 0:
            log(f"Kelly dit de ne pas parier (taille = 0), skip")
            continue

        log(
            f"💵 Kelly sizing: {bet_amount:.2f}$ "
            f"(bankroll={BANKROLL}$, fraction={KELLY_FRACTION}, "
            f"max={MAX_BET_USDC}$)"
        )

        # Find the YES token ID for the chosen tranche
        token_id = None
        for t in market["tranches"]:
            if t["label"] == best_bet["tranche"]:
                token_id = t["token_id_yes"]
                break

        if not token_id:
            log(f"Token ID introuvable pour tranche {best_bet['tranche']}", "error")
            continue

        # 11. Place the bet (or simulate in DRY_RUN mode)
        if DRY_RUN:
            log(
                f"🧪 DRY RUN — Pari simulé: {bet_amount:.2f}$ sur {best_bet['tranche']}°C "
                f"@ {best_bet['market_price']:.2f} (edge: {best_bet['edge']:.0%}) "
                f"[{method}, J+{days_ahead}]"
            )
            record_bet(
                market_date, best_bet, None,
                forecast_temp=forecast_temp, status="simulated",
                days_ahead=days_ahead, bet_amount=bet_amount, method=method,
            )
            notify_dry_run_bet(
                amount=bet_amount,
                tranche=best_bet["tranche"],
                market_date=market_date,
                edge=best_bet["edge"],
                our_prob=best_bet["our_probability"],
                market_price=best_bet["market_price"],
                source_summary=source_summary,
                forecast_temp=forecast_temp,
            )
        else:
            log(
                f"💰 Placement pari: {bet_amount:.2f}$ sur {best_bet['tranche']}°C "
                f"@ {best_bet['market_price']:.2f} (edge: {best_bet['edge']:.0%}) "
                f"[{method}, J+{days_ahead}]"
            )
            result = place_bet(
                client=polymarket_client,
                token_id=token_id,
                price=best_bet["market_price"],
                size=bet_amount,
            )

            if result is not None:
                # 12a. Ordre réussi — enregistrer et notifier
                record_bet(
                    market_date, best_bet, result,
                    forecast_temp=forecast_temp, status="placed",
                    days_ahead=days_ahead, bet_amount=bet_amount, method=method,
                )
                notify_bet_placed(
                    amount=bet_amount,
                    tranche=best_bet["tranche"],
                    market_date=market_date,
                    edge=best_bet["edge"],
                    our_prob=best_bet["our_probability"],
                    market_price=best_bet["market_price"],
                    source_summary=source_summary,
                    forecast_temp=forecast_temp,
                )
            else:
                # 12b. Ordre ÉCHOUÉ — enregistrer comme failed et notifier l'erreur
                log(
                    f"❌ ÉCHEC placement pari: {bet_amount:.2f}$ sur {best_bet['tranche']}°C "
                    f"@ {best_bet['market_price']:.2f} — place_bet() a retourné None",
                    "error",
                )
                record_bet(
                    market_date, best_bet, None,
                    forecast_temp=forecast_temp, status="failed",
                    days_ahead=days_ahead, bet_amount=bet_amount, method=method,
                )
                notify_bet_failed(
                    amount=bet_amount,
                    tranche=best_bet["tranche"],
                    market_date=market_date,
                    error_detail="place_bet() a retourné None — voir logs pour détails",
                    source_summary=source_summary,
                    forecast_temp=forecast_temp,
                )

      except Exception as e:
        log(f"❌ Erreur sur le marché {market.get('date', '?')}: {e}", "error")
        log(traceback.format_exc(), "error")
        continue

    log("✅ Scan terminé")


def safe_run_bot():
    """Wrapper around run_bot with global exception handling."""
    try:
        run_bot()
    except Exception as e:
        log(f"💀 CRASH dans run_bot(): {e}", "error")
        log(traceback.format_exc(), "error")
        try:
            notify_error(f"💀 Bot crash: {e}")
        except Exception:
            pass  # Don't let notification failure propagate


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode_label = "🧪 DRY RUN" if DRY_RUN else "🔴 LIVE"
    log(f"🤖 Bot Polymarket Météo London démarré ({mode_label}) — scan toutes les {CHECK_INTERVAL_HOURS}h")
    try:
        send_telegram(f"🤖 Bot démarré ({mode_label}) — scan toutes les {CHECK_INTERVAL_HOURS}h")
    except Exception as e:
        log(f"Telegram au démarrage échoué: {e}", "warning")

    # Premier scan immédiat au lancement
    safe_run_bot()

    # Puis toutes les 2h
    schedule.every(CHECK_INTERVAL_HOURS).hours.do(safe_run_bot)

    # Keep running
    scan_count = 0
    heartbeat_count = 0
    while True:
        schedule.run_pending()
        time.sleep(60)

        scan_count += 1
        heartbeat_count += 1

        # Heartbeat log every ~2h (120 iterations × 60s sleep)
        if scan_count % 120 == 0:
            next_run = schedule.next_run()
            if next_run:
                delta = next_run - datetime.now()
                minutes_left = max(0, int(delta.total_seconds() // 60))
                log(f"🔄 Heartbeat — bot actif, prochain scan dans {minutes_left}min")
            else:
                log("🔄 Heartbeat — bot actif")

        # Heartbeat Telegram every ~12h (720 iterations × 60s sleep)
        if heartbeat_count % 720 == 0:
            heartbeat_count = 0
            now = datetime.now()
            last_scan = now.strftime("%H:%M")
            tomorrow = (date.today() + timedelta(days=1)).strftime("%d/%m")
            after_tomorrow = (date.today() + timedelta(days=2)).strftime("%d/%m")
            markets_summary = f"prochains paris possibles : J+1 {tomorrow}, J+2 {after_tomorrow}"
            try:
                notify_heartbeat(last_scan, markets_summary)
            except Exception:
                pass
