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

    num_shares = size / price  # shares = amount / price_per_share

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=num_shares,
            side=BUY,
        )
        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order)

        log(
            f"Trader: ordre placé — {size:.2f}$ @ {price:.2f} "
            f"({num_shares:.1f} shares) sur token {token_id[:12]}..."
        )
        return response

    except Exception as e:
        log(f"Trader: erreur placement ordre — {e}", "error")
        return None
