import re
import json
import requests
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient
from utils.logger import log
from polymarket.client import get_price

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


def find_london_temperature_markets(days_ahead: int = 3) -> list[dict]:
    """
    Find all active Polymarket events for "Highest temperature in London on ..."
    by constructing the known slug pattern for each day.

    Args:
        days_ahead: number of days to scan (today + N-1 days)

    Returns:
        List of parsed market dicts:
        [
            {
                "event_id": str,
                "title": str,
                "date": "YYYY-MM-DD",
                "tranches": [
                    {
                        "label": "12",          # or "8-" / "14+"
                        "question": "...",
                        "token_id_yes": str,
                        "token_id_no": str,
                        "condition_id": str,
                    },
                    ...
                ],
            },
            ...
        ]
    """
    london_events = []
    today = datetime.now()

    for offset in range(days_ahead):
        target = today + timedelta(days=offset)
        month = target.strftime("%B").lower()  # e.g. "february"
        day = target.day
        year = target.year
        market_date = target.strftime("%Y-%m-%d")

        slug = f"highest-temperature-in-london-on-{month}-{day}-{year}"

        try:
            response = requests.get(
                GAMMA_EVENTS_URL,
                params={"slug": slug},
                timeout=30,
            )
            response.raise_for_status()
            events = response.json()
        except requests.RequestException as e:
            log(f"Gamma API: erreur requête slug '{slug}' — {e}", "error")
            continue

        if not events:
            log(f"Gamma API: aucun événement trouvé pour {market_date} (slug: {slug})")
            continue

        event = events[0]
        tranches = _parse_tranches(event.get("markets", []))
        if not tranches:
            log(f"Gamma API: aucune tranche trouvée pour '{event.get('title')}'", "warning")
            continue

        london_events.append({
            "event_id": event.get("id", ""),
            "title": event.get("title", ""),
            "date": market_date,
            "tranches": tranches,
        })

    log(f"Gamma API: {len(london_events)} marché(s) température Londres trouvé(s)")
    return london_events


def _parse_tranches(markets: list[dict]) -> list[dict]:
    """
    Parse Polymarket sub-markets (tranches) from a Gamma API event's markets list.

    Each market represents a temperature tranche (e.g. "9°C", "8°C or below", "14°C or higher").
    """
    tranches = []
    for market in markets:
        question = market.get("question", "")
        label = _extract_tranche_label(question)
        if label is None:
            continue

        # clobTokenIds is a JSON string: "[yes_token_id, no_token_id]"
        token_ids_raw = market.get("clobTokenIds", "[]")
        try:
            if isinstance(token_ids_raw, str):
                token_ids = json.loads(token_ids_raw)
            else:
                token_ids = token_ids_raw
        except (json.JSONDecodeError, TypeError):
            token_ids = []

        if len(token_ids) < 2:
            log(f"Tranche '{question}': token IDs manquants", "warning")
            continue

        tranches.append({
            "label": label,
            "question": question,
            "token_id_yes": token_ids[0],
            "token_id_no": token_ids[1],
            "condition_id": market.get("conditionId", ""),
        })

    return tranches


def _extract_tranche_label(question: str) -> str | None:
    """
    Convert a market question to a tranche label.

    Examples:
        "Will the highest temperature in London be 8°C or below on February 12?" -> "8-"
        "Will the highest temperature in London be 9°C on February 12?"          -> "9"
        "Will the highest temperature in London be 14°C or higher on ..."        -> "14+"
    """
    q = question.strip().lower()

    # "X°C or below" / "X°c or less"
    match = re.search(r"(\d+)\s*°?\s*c?\s*(or\s+below|or\s+less)", q)
    if match:
        return match.group(1) + "-"

    # "X°C or higher" / "X°C or above" / "X°C or more"
    match = re.search(r"(\d+)\s*°?\s*c?\s*(or\s+higher|or\s+above|or\s+more)", q)
    if match:
        return match.group(1) + "+"

    # Exact "X°C" or just "X"
    match = re.search(r"(\d+)\s*°?\s*c?", q)
    if match:
        return match.group(1)

    return None


def get_all_market_prices(client: ClobClient, market: dict) -> dict[str, dict]:
    """
    Fetch current prices for all tranches in a market.

    Returns:
        {
            "12": {"bid": 0.40, "ask": 0.45, "mid": 0.425, "spread": 0.05},
            ...
        }
    """
    prices = {}
    for tranche in market.get("tranches", []):
        label = tranche["label"]
        token_id = tranche["token_id_yes"]
        price_info = get_price(client, token_id)
        if price_info is not None:
            prices[label] = price_info
        else:
            log(f"Tranche {label}: prix indisponible (token résolu?), exclue de l'analyse")

    return prices
