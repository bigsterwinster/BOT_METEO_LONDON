"""
test_real_bet.py — Place a REAL micro-bet of $1 to validate the full chain.

Run on the server:
    cd /home/ai/DEV/BOT_POLYMARKET/METEO_LONDON
    source venv/bin/activate
    python3 test_real_bet.py
"""

import sys
import json
from datetime import date, timedelta

from cities import CITIES
from utils.logger import log
from polymarket.client import create_client, get_price
from polymarket.markets import find_temperature_markets
from polymarket.trader import place_bet
from notifications.telegram import send_telegram


TEST_BET_AMOUNT = 1.0  # $1 micro-bet


def main():
    print("=" * 60)
    print("🧪 TEST PARI RÉEL — $1 micro-bet")
    print("=" * 60)
    print()

    # 1. Initialize client
    print("1. Initialisation du client Polymarket...")
    client = create_client()
    if client is None:
        print("❌ ÉCHEC: impossible d'initialiser le client Polymarket")
        print("   Vérifiez POLYMARKET_PRIVATE_KEY et POLYMARKET_FUNDER_ADDRESS dans .env")
        sys.exit(1)
    print("   ✅ Client initialisé et authentifié")
    print()

    # 2. Find a market
    print("2. Recherche de marchés Londres...")
    markets = find_temperature_markets({"id": "london", **CITIES["london"]}, days_ahead=3)
    if not markets:
        print("❌ ÉCHEC: aucun marché température Londres trouvé")
        sys.exit(1)
    print(f"   ✅ {len(markets)} marché(s) trouvé(s)")
    for m in markets:
        print(f"      - {m['date']}: {m['title']} ({len(m['tranches'])} tranches)")
    print()

    # 3. Find cheapest tranche with liquidity
    print("3. Recherche de la tranche la moins chère avec liquidité...")
    best_tranche = None
    best_price = 1.0
    best_market = None

    for market in markets:
        for tranche in market["tranches"]:
            token_id = tranche["token_id_yes"]
            price_info = get_price(client, token_id)
            if price_info is None:
                continue

            ask = price_info.get("ask", 1.0)
            spread = price_info.get("spread", 1.0)

            # We want a liquid tranche with a reasonable ask price
            if 0.02 < ask < best_price and spread < 0.20:
                best_price = ask
                best_tranche = tranche
                best_market = market

    if best_tranche is None:
        print("❌ ÉCHEC: aucune tranche avec liquidité trouvée")
        sys.exit(1)

    print(f"   ✅ Tranche sélectionnée: {best_tranche['label']}°C")
    print(f"      Marché: {best_market['date']} — {best_market['title']}")
    print(f"      Prix ask: {best_price:.2f}")
    print(f"      Token ID: {best_tranche['token_id_yes'][:20]}...")
    print()

    # 4. Place micro-bet
    print(f"4. Placement du pari de {TEST_BET_AMOUNT}$...")
    result = place_bet(
        client=client,
        token_id=best_tranche["token_id_yes"],
        price=best_price,
        size=TEST_BET_AMOUNT,
    )

    print()
    if result is not None:
        print("=" * 60)
        print("✅ SUCCÈS — PARI RÉEL PLACÉ !")
        print("=" * 60)
        print(f"   Réponse API: {json.dumps(result, indent=2) if isinstance(result, dict) else result}")
        print()
        print("👉 Vérifie sur https://polymarket.com que le pari apparaît.")

        # Notify via Telegram
        send_telegram(
            f"🧪✅ TEST PARI RÉEL RÉUSSI\n"
            f"Montant: {TEST_BET_AMOUNT}$ sur {best_tranche['label']}°C\n"
            f"Marché: {best_market['date']}\n"
            f"Prix: {best_price:.2f}\n"
            f"Réponse: {result}"
        )
    else:
        print("=" * 60)
        print("❌ ÉCHEC — PARI NON PLACÉ")
        print("=" * 60)
        print("   place_bet() a retourné None.")
        print("   Vérifiez les logs ci-dessus pour le détail de l'erreur.")
        print()
        print("   Causes possibles:")
        print("   - Mot de passe/clé privée incorrecte")
        print("   - Pas assez de fonds USDC sur le wallet")
        print("   - Problème d'allowance (nécessite approve USDC)")
        print("   - API Polymarket en maintenance")

        send_telegram(
            f"🧪❌ TEST PARI RÉEL ÉCHOUÉ\n"
            f"Montant: {TEST_BET_AMOUNT}$ sur {best_tranche['label']}°C\n"
            f"place_bet() a retourné None — voir logs serveur"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
