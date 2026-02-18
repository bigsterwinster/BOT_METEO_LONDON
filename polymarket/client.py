from py_clob_client.client import ClobClient
from utils.logger import log
from config import (
    POLYMARKET_HOST,
    POLYMARKET_CHAIN_ID,
    POLYMARKET_PRIVATE_KEY,
    POLYMARKET_FUNDER_ADDRESS,
    POLYMARKET_SIGNATURE_TYPE,
)


def create_client() -> ClobClient | None:
    """
    Initialize and authenticate the Polymarket CLOB client.

    Returns:
        Authenticated ClobClient instance, or None on failure.
    """
    if not POLYMARKET_PRIVATE_KEY:
        log("Polymarket: POLYMARKET_PRIVATE_KEY non configurée", "error")
        return None
    if not POLYMARKET_FUNDER_ADDRESS:
        log("Polymarket: POLYMARKET_FUNDER_ADDRESS non configurée", "error")
        return None

    try:
        client = ClobClient(
            host=POLYMARKET_HOST,
            key=POLYMARKET_PRIVATE_KEY,
            chain_id=POLYMARKET_CHAIN_ID,
            signature_type=POLYMARKET_SIGNATURE_TYPE,
            funder=POLYMARKET_FUNDER_ADDRESS,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        log("Polymarket: client initialisé et authentifié")
        return client
    except Exception as e:
        log(f"Polymarket: erreur initialisation client — {e}", "error")
        return None


def _extract_price(raw, default: float) -> float:
    """Extract a float price from the raw get_price response (may be dict, str, or float)."""
    if isinstance(raw, dict):
        return float(raw.get("price", default))
    if raw is None:
        return default
    return float(raw)


def get_price(client: ClobClient, token_id: str) -> dict | None:
    """
    Get bid/ask/mid prices for a token.

    Returns:
        {"bid": float, "ask": float, "mid": float, "spread": float}
        or None if the token is resolved / has no orderbook.
    """
    try:
        raw_bid = client.get_price(token_id, side="BUY")
        raw_ask = client.get_price(token_id, side="SELL")
        log(f"DEBUG get_price token {token_id[:16]}... — raw_bid={raw_bid} raw_ask={raw_ask}", "debug")

        bid = _extract_price(raw_bid, 0)
        ask = _extract_price(raw_ask, 1)
        mid = (bid + ask) / 2
        return {"bid": bid, "ask": ask, "mid": mid, "spread": ask - bid}
    except Exception as e:
        log(f"Polymarket: prix indisponible token {token_id[:16]}... — {e}", "warning")
        return None
