from utils.logger import log
from config import MIN_EDGE_PERCENT

# Ne pas parier si notre propre probabilité est trop faible
MIN_OUR_PROBABILITY = 0.25


# ---------------------------------------------------------------------------
# Amélioration 5 — Edge minimum dynamique par horizon
# ---------------------------------------------------------------------------

def get_min_edge_for_horizon(days_ahead: int) -> float:
    """
    Return the minimum required edge based on forecast horizon.

    Rationale:
      - J+0: forecast is very reliable → accept smaller edges (8%)
      - J+1: good forecast → moderate edge required (12%)
      - J+2: uncertain → demand a large edge to compensate (20%)
    """
    return {
        0: 0.08,   # 8%
        1: 0.12,   # 12%
        2: 0.20,   # 20%
    }.get(days_ahead, 0.25)


# ---------------------------------------------------------------------------
# Amélioration 6 — Kelly Criterion (sizing dynamique)
# ---------------------------------------------------------------------------

def calculate_bet_size(
    our_prob: float,
    market_price: float,
    bankroll: float,
    max_bet: float,
    kelly_fraction: float = 0.25,
) -> float:
    """
    Calculate optimal bet size using the fractional Kelly Criterion.

    Kelly = (prob * odds - (1-prob)) / odds
    We use kelly_fraction (25% by default) of the optimal Kelly to reduce
    variance while still sizing proportionally to edge.

    Returns:
        Bet size in USDC (0 if no edge).
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0

    odds = (1.0 / market_price) - 1.0  # decimal odds minus 1
    kelly = (our_prob * odds - (1.0 - our_prob)) / odds

    if kelly <= 0:
        return 0.0

    bet_fraction = kelly * kelly_fraction
    bet = bankroll * bet_fraction

    # Clamp to max_bet and enforce a minimum of $1
    bet = min(bet, max_bet)
    if bet < 1.0:
        return 0.0

    return round(bet, 2)


# ---------------------------------------------------------------------------
# Core edge / score functions
# ---------------------------------------------------------------------------

def calculate_edge(our_probability: float, market_price: float) -> float:
    """
    Calculate our edge (advantage) over the market.
    If our probability = 60% and market says 40% (price = 0.40),
    edge = (0.60 - 0.40) / 0.40 = 50%
    """
    if market_price <= 0:
        return 0
    return (our_probability - market_price) / market_price


def calculate_score(our_probability: float, market_price: float) -> float:
    """
    Calculate a weighted score that favours bets with both good edge AND
    high probability. Uses our_prob² to heavily penalise low-probability bets.

    score = EV * our_prob² = ((our_prob / market_price) - 1) * our_prob²
    """
    if market_price <= 0:
        return 0
    ev = (our_probability / market_price) - 1
    return ev * (our_probability ** 2)


def find_best_bet(
    probability_distribution: dict[str, float],
    market_prices: dict[str, dict],
    days_ahead: int = 1,
    min_edge: float = None,
) -> dict | None:
    """
    Find the best bet across all tranches.

    Args:
        probability_distribution: our computed probabilities {tranche: prob}
        market_prices: market prices {tranche: {"bid", "ask", "mid", "spread"}}
        days_ahead: forecast horizon (used for dynamic min_edge)
        min_edge: override minimum edge (default: dynamic based on days_ahead)

    Returns:
        Best bet dict or None if no sufficient edge found.
    """
    if min_edge is None:
        min_edge = get_min_edge_for_horizon(days_ahead)
        log(f"Edge minimum dynamique pour J+{days_ahead}: {min_edge:.0%}")

    # --- Guard: skip if the two most probable tranches are too close ---
    sorted_tranches = sorted(probability_distribution.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_tranches) >= 2:
        top1_tranche, top1_prob = sorted_tranches[0]
        top2_tranche, top2_prob = sorted_tranches[1]
        prob_gap = top1_prob - top2_prob

        if prob_gap < 0.05:  # less than 5% difference
            # Check if the market also reflects this uncertainty
            top1_price_info = market_prices.get(top1_tranche)
            top2_price_info = market_prices.get(top2_tranche)
            if top1_price_info and top2_price_info:
                top1_mid = top1_price_info.get("mid", 0)
                top2_mid = top2_price_info.get("mid", 0)
                market_gap = abs(top1_mid - top2_mid)
                if market_gap < 0.10:  # market prices within 10c of each other
                    log(
                        f"⚠️ Trop serré entre {top1_tranche}°C ({top1_prob:.0%}) "
                        f"et {top2_tranche}°C ({top2_prob:.0%}), skip"
                    )
                    return None

    best_bet = None
    best_score = 0

    for tranche, our_prob in probability_distribution.items():
        price_info = market_prices.get(tranche)
        if not price_info:
            continue

        market_price = price_info.get("ask", 1.0)

        # Skip if our own probability is too low
        if our_prob < MIN_OUR_PROBABILITY:
            log(f"  ❌ Tranche {tranche}: proba {our_prob:.0%} < seuil {MIN_OUR_PROBABILITY:.0%} → skip")
            continue

        # Skip if already too expensive or no liquidity
        if market_price >= 0.95:
            log(f"  ❌ Tranche {tranche}: prix marché {market_price:.2f} trop élevé → skip")
            continue
        if market_price <= 0.01:
            log(f"  ❌ Tranche {tranche}: prix marché {market_price:.2f} sans liquidité → skip")
            continue

        # Skip if spread too large (illiquid)
        spread = price_info.get("spread", 1.0)
        if spread > 0.15:
            log(f"  ❌ Tranche {tranche}: spread {spread:.2f} trop large → skip")
            continue

        edge = calculate_edge(our_prob, market_price)
        if edge < min_edge:
            log(f"  ❌ Tranche {tranche}: edge {edge:.0%} < minimum {min_edge:.0%} → skip")
            continue

        log(f"  ✅ Tranche {tranche}: proba={our_prob:.0%}, prix={market_price:.2f}, edge={edge:.0%} → candidat")
        score = calculate_score(our_prob, market_price)

        if score > best_score:
            best_score = score
            best_bet = {
                "tranche": tranche,
                "our_probability": our_prob,
                "market_price": market_price,
                "edge": edge,
                "score": score,
                "expected_value": (our_prob / market_price) - 1,
            }

    if best_bet:
        log(
            f"✅ Meilleur pari retenu: tranche {best_bet['tranche']} — "
            f"edge {best_bet['edge']:.0%}, score {best_bet['score']:.3f}, "
            f"notre proba {best_bet['our_probability']:.0%} vs marché {best_bet['market_price']:.2f}"
        )
    else:
        log("🔍 Aucun pari avec edge suffisant — toutes les tranches rejetées")

    return best_bet
