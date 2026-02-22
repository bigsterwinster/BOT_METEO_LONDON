import math
import traceback

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY
from utils.logger import log


def place_bet(client: ClobClient, token_id: str, price: float, size: float) -> dict | None:
    """
    Place a limit BUY YES order on a temperature tranche.

    Args:
        client: authenticated ClobClient
        token_id: YES token ID of the target tranche
        price: price to buy at (e.g. 0.50 means we think probability > 50%)
        size: amount in USDC to bet (e.g. 10.0 for $10)

    Returns:
        API response dict, or None on failure.
    """
    if price <= 0 or price >= 1:
        log(f"Trader: prix invalide ({price}), pari annulé", "warning")
        return None

    if size <= 0:
        log("Trader: montant invalide, pari annulé", "warning")
        return None

    # Arrondi vers le bas à 2 décimales pour éviter les rejets API
    num_shares = math.floor(size / price * 100) / 100

    # S'assurer que le montant total >= $1 minimum Polymarket
    if num_shares * price < 1.0:
        num_shares = math.ceil(1.0 / price * 100) / 100


    log(
        f"Trader: tentative d'ordre — {size:.2f}$ @ {price:.2f} "
        f"({num_shares:.1f} shares) sur token {token_id[:12]}..."
    )

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=num_shares,
            side=BUY,
        )
        log(f"Trader: création ordre signé (token={token_id[:16]}..., price={price}, size={num_shares:.2f})...")
        signed_order = client.create_order(order_args)
        log(f"Trader: ordre signé créé, envoi au CLOB...")
        response = client.post_order(signed_order)

        log(
            f"✅ Trader: ordre placé avec succès — {size:.2f}$ @ {price:.2f} "
            f"({num_shares:.1f} shares) sur token {token_id[:12]}..."
        )
        log(f"Trader: réponse API complète: {response}")
        return response

    except Exception as e:
        log(f"❌ Trader: ERREUR placement ordre — {type(e).__name__}: {e}", "error")
        log(f"Trader: traceback complet:\n{traceback.format_exc()}", "error")
        return None
