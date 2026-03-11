import json
import os
import time
import traceback
from datetime import datetime, date, timedelta

import schedule

from cities import CITIES
from config import (
    ACTIVE_CITIES,
    CHECK_INTERVAL_HOURS,
    MAX_BET_USDC,
    DRY_RUN, BANKROLL, KELLY_FRACTION,
)
from utils.logger import log
from weather.analyzer import (
    get_weather_forecasts,
    sources_diverge_too_much,
    average_forecast,
    get_probability_distribution,
)
from polymarket.client import create_client
from polymarket.markets import find_temperature_markets, get_all_market_prices
from polymarket.trader import place_bet
from strategy.edge_calculator import (
    find_best_bet,
    calculate_bet_size,
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


def _unit_symbol(unit: str) -> str:
    return "\u00b0F" if unit.lower() == "fahrenheit" else "\u00b0C"


def _market_key(city_id: str, market_date: str) -> str:
    return f"{city_id}_{market_date}"


def _active_city_configs() -> list[dict]:
    configs: list[dict] = []
    seen: set[str] = set()
    for raw_city_id in ACTIVE_CITIES:
        city_id = raw_city_id.strip().lower()
        if not city_id:
            continue

        if city_id in seen:
            continue
        seen.add(city_id)

        city_config = CITIES.get(city_id)
        if city_config is None:
            log(f"Ville inconnue dans ACTIVE_CITIES: '{city_id}' — ignorée", "warning")
            continue

        configs.append({"id": city_id, **city_config})

    return configs


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


def already_bet_on(market_key: str) -> bool:
    """
    Check if we already placed a bet on this market key (city + date).

    Allows retry: a failed bet does NOT block a new attempt.
    """
    history = load_bets_history()
    previous_bet = history.get(market_key)

    # Backward compatibility: old London-only keys were just market_date.
    if previous_bet is None and market_key.startswith("london_") and "_" in market_key:
        _, market_date = market_key.split("_", 1)
        previous_bet = history.get(market_date)

    if previous_bet is None:
        return False

    # Allow retry if previous bet failed
    if previous_bet.get("status") == "failed":
        log(
            f"🔁 Pari précédent ÉCHOUÉ pour {market_key}, "
            f"nouvelle tentative autorisée"
        )
        return False

    return True



def record_bet(
    market_key: str,
    market_date: str,
    city_config: dict,
    bet_info: dict,
    order_response: dict | None,
    forecast_temp: float | None = None,
    status: str = "placed",
    days_ahead: int = None,
    bet_amount: float = None,
    method: str = "gaussian",
):
    """Record a placed or simulated bet in the history file."""
    history = load_bets_history()
    history[market_key] = {
        "market_key": market_key,
        "market_date": market_date,
        "city_id": city_config["id"],
        "city_name": city_config["name"],
        "unit": city_config.get("unit", "celsius"),
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
    log(
        f"Pari enregistré pour {city_config['name']} {market_date}: "
        f"tranche {bet_info['tranche']} ({status})"
    )


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

    city_configs = _active_city_configs()
    if not city_configs:
        log("Aucune ville active valide dans ACTIVE_CITIES", "error")
        return

    candidates = []

    for city_config in city_configs:
        city_id = city_config["id"]
        city_name = city_config["name"]
        unit = city_config.get("unit", "celsius")
        unit_symbol = _unit_symbol(unit)

        markets = find_temperature_markets(city_config)
        if not markets:
            log(f"Aucun marché température trouvé pour {city_name}")
            continue

        for market in markets:
            try:
                market_date = market["date"]
                market_key = _market_key(city_id, market_date)
                log(f"--- [{city_name}] Analyse du marché {market_date} ({market['title']}) ---")

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

                # 3. Check if we already bet on this market
                if already_bet_on(market_key):
                    log(f"⏭️ Déjà parié sur {city_name} {market_date} (J+{days_ahead}), skip")
                    continue

                # 4. Fetch weather forecasts
                forecasts = get_weather_forecasts(market_date, city_config=city_config)

                # 5. Check source coherence
                if sources_diverge_too_much(forecasts):
                    om = forecasts.get("open_meteo")
                    wu = forecasts.get("wunderground")
                    spread = abs((om or {}).get("max_temp", 0) - (wu or {}).get("max_temp", 0))
                    notify_uncertainty(market_date, spread, city_name=city_name, unit=unit)
                    continue

                # 6. Compute forecast_temp (for Gaussian fallback)
                forecast_temp = average_forecast(forecasts)
                if forecast_temp is None:
                    log(f"Pas de prévision disponible pour {city_name} {market_date}, skip", "warning")
                    continue

                # 7. Compute probability distribution (Ensemble first, Gaussian fallback)
                tranche_labels = [t["label"] for t in market["tranches"]]

                probabilities, source_info = get_probability_distribution(
                    target_date=market_date,
                    tranches=tranche_labels,
                    days_ahead=days_ahead,
                    forecast_temp=forecast_temp,
                    city_config=city_config,
                )
                method = source_info["method"]
                log(f"[{city_name}] Distribution ({method}): {probabilities}")

                # Build human-readable source summary for Telegram
                if method == "ensemble":
                    source_summary = (
                        f"Ensemble ({source_info['members']} membres, "
                        f"spread {source_info['spread_min']}-{source_info['spread_max']}{unit_symbol})"
                    )
                else:
                    source_summary = f"Gaussienne (σ={source_info['sigma']}{unit_symbol})"

                # 8. Fetch market prices
                market_prices = get_all_market_prices(polymarket_client, market)
                log(f"[{city_name}] Prix marché: { {k: v['mid'] for k, v in market_prices.items()} }")

                # 9. Find best bet
                best_bet = find_best_bet(probabilities, market_prices, days_ahead=days_ahead)

                if best_bet is None:
                    log(f"🔍 Aucun edge trouvé pour {city_name} {market_date}")
                    notify_scan_no_edge(market_date, city_name=city_name)
                    continue

                candidates.append(
                    {
                        "city_config": city_config,
                        "market": market,
                        "market_key": market_key,
                        "days_ahead": days_ahead,
                        "best_bet": best_bet,
                        "forecast_temp": forecast_temp,
                        "source_summary": source_summary,
                        "method": method,
                    }
                )

            except Exception as e:
                log(f"❌ Erreur sur le marché {city_name} {market.get('date', '?')}: {e}", "error")
                log(traceback.format_exc(), "error")
                continue

    if not candidates:
        log("✅ Scan terminé — aucun pari candidat")
        return

    candidates.sort(key=lambda item: item["best_bet"]["score"], reverse=True)
    remaining_bankroll = BANKROLL
    log(f"📋 {len(candidates)} pari(s) candidat(s) collecté(s), triés par score")

    for candidate in candidates:
        city_config = candidate["city_config"]
        city_name = city_config["name"]
        unit = city_config.get("unit", "celsius")
        unit_symbol = _unit_symbol(unit)

        market = candidate["market"]
        market_date = market["date"]
        market_key = candidate["market_key"]
        days_ahead = candidate["days_ahead"]
        best_bet = candidate["best_bet"]
        forecast_temp = candidate["forecast_temp"]
        source_summary = candidate["source_summary"]
        method = candidate["method"]

        if remaining_bankroll < 1.0:
            log("💸 Bankroll restant < 1$, arrêt des placements")
            break

        bet_amount = calculate_bet_size(
            our_prob=best_bet["our_probability"],
            market_price=best_bet["market_price"],
            bankroll=remaining_bankroll,
            max_bet=MAX_BET_USDC,
            kelly_fraction=KELLY_FRACTION,
        )

        if bet_amount <= 0:
            log(f"[{city_name} {market_date}] Kelly dit de ne pas parier (taille = 0), skip")
            continue

        if bet_amount > remaining_bankroll:
            bet_amount = round(remaining_bankroll, 2)

        if bet_amount < 1.0:
            log(f"[{city_name} {market_date}] Montant < 1$, skip")
            continue

        log(
            f"💵 [{city_name}] Kelly sizing: {bet_amount:.2f}$ "
            f"(bankroll restant={remaining_bankroll:.2f}$, fraction={KELLY_FRACTION}, "
            f"max={MAX_BET_USDC}$)"
        )

        # Find the YES token ID for the chosen tranche
        token_id = None
        for tranche in market["tranches"]:
            if tranche["label"] == best_bet["tranche"]:
                token_id = tranche["token_id_yes"]
                break

        if not token_id:
            log(f"Token ID introuvable pour tranche {best_bet['tranche']}", "error")
            continue

        # Place the bet (or simulate in DRY_RUN mode)
        if DRY_RUN:
            log(
                f"🧪 DRY RUN — [{city_name}] Pari simulé: {bet_amount:.2f}$ sur {best_bet['tranche']}{unit_symbol} "
                f"@ {best_bet['market_price']:.2f} (edge: {best_bet['edge']:.0%}) "
                f"[{method}, J+{days_ahead}]"
            )
            record_bet(
                market_key=market_key,
                market_date=market_date,
                city_config=city_config,
                bet_info=best_bet,
                order_response=None,
                forecast_temp=forecast_temp,
                status="simulated",
                days_ahead=days_ahead,
                bet_amount=bet_amount,
                method=method,
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
                city_name=city_name,
                unit=unit,
            )
            remaining_bankroll = round(remaining_bankroll - bet_amount, 2)
        else:
            log(
                f"💰 [{city_name}] Placement pari: {bet_amount:.2f}$ sur {best_bet['tranche']}{unit_symbol} "
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
                # Ordre réussi — enregistrer et notifier
                record_bet(
                    market_key=market_key,
                    market_date=market_date,
                    city_config=city_config,
                    bet_info=best_bet,
                    order_response=result,
                    forecast_temp=forecast_temp,
                    status="placed",
                    days_ahead=days_ahead,
                    bet_amount=bet_amount,
                    method=method,
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
                    city_name=city_name,
                    unit=unit,
                )
                remaining_bankroll = round(remaining_bankroll - bet_amount, 2)
            else:
                # Ordre ÉCHOUÉ — enregistrer comme failed et notifier
                log(
                    f"❌ ÉCHEC placement pari [{city_name}]: {bet_amount:.2f}$ sur {best_bet['tranche']}{unit_symbol} "
                    f"@ {best_bet['market_price']:.2f} — place_bet() a retourné None",
                    "error",
                )
                record_bet(
                    market_key=market_key,
                    market_date=market_date,
                    city_config=city_config,
                    bet_info=best_bet,
                    order_response=None,
                    forecast_temp=forecast_temp,
                    status="failed",
                    days_ahead=days_ahead,
                    bet_amount=bet_amount,
                    method=method,
                )
                notify_bet_failed(
                    amount=bet_amount,
                    tranche=best_bet["tranche"],
                    market_date=market_date,
                    error_detail="place_bet() a retourné None — voir logs pour détails",
                    source_summary=source_summary,
                    forecast_temp=forecast_temp,
                    city_name=city_name,
                    unit=unit,
                )

    log(f"✅ Scan terminé — bankroll restant estimé: {remaining_bankroll:.2f}$")


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
    active_cities_label = ", ".join(ACTIVE_CITIES) if ACTIVE_CITIES else "aucune"
    log(
        f"🤖 Bot Polymarket Météo multi-ville démarré ({mode_label}) "
        f"— scan toutes les {CHECK_INTERVAL_HOURS}h — villes: {active_cities_label}"
    )
    try:
        send_telegram(
            f"🤖 Bot démarré ({mode_label}) — scan toutes les {CHECK_INTERVAL_HOURS}h\n"
            f"Villes actives: {active_cities_label}"
        )
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
