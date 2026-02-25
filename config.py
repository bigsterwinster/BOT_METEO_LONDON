import os
from dotenv import load_dotenv

load_dotenv()

# Polymarket
POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_CHAIN_ID = 137  # Polygon
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
POLYMARKET_SIGNATURE_TYPE = 1  # Google/Magic wallet

# Météo
WU_API_KEY = os.getenv("WU_API_KEY", "")

# Villes actives (liste de city_id depuis cities.py)
# Peut être overridé par ACTIVE_CITIES dans .env (comma-separated)
ACTIVE_CITIES = [
    city.strip().lower()
    for city in os.getenv("ACTIVE_CITIES", "london").split(",")
    if city.strip()
]

# Stratégie
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "2"))  # Amélioration 7: 2h au lieu de 4h
MAX_BET_USDC = float(os.getenv("MAX_BET_USDC", "10"))
MIN_EDGE_PERCENT = float(os.getenv("MIN_EDGE_PERCENT", "10"))
MAX_UNCERTAINTY_SPREAD_C = int(os.getenv("MAX_UNCERTAINTY_SPREAD_C", "3"))

# Kelly Criterion (Amélioration 6)
BANKROLL = float(os.getenv("BANKROLL", "50"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
