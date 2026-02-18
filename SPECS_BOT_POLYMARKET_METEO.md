# 🤖 Bot Polymarket — Paris Température Max Londres

## Résumé du projet

Bot 100% automatique qui parie sur le marché Polymarket **"Highest temperature in London on [date]?"**. Il tourne en continu, récupère les prévisions météo, compare avec les cotes Polymarket, et parie quand il détecte un avantage (edge).

---

## 1. CONTEXTE & RÈGLES DU MARCHÉ POLYMARKET

### Format du marché
- **Question** : "Highest temperature in London on February 12?" (exemple)
- **Tranches** : températures exactes en °C (ex: 8°C or below, 9°C, 10°C, 11°C, 12°C, 13°C, 14°C or higher)
- **On achète** : "Yes" sur la tranche qu'on pense correcte, ou "No" sur celles qu'on pense fausses
- **Marchés disponibles** : 3 jours glissants (aujourd'hui J, demain J+1, après-demain J+2)
- **Prix** : entre 0.00$ et 1.00$ — le prix = probabilité implicite du marché

### Source de résolution (CRITIQUE)
- **Weather Underground** — station **London City Airport (EGLC)**
- URL : `https://www.wunderground.com/history/daily/gb/london/EGLC`
- **Précision** : degrés Celsius ENTIERS (ex: 9°C, pas 9.3°C)
- Le marché ne se résout qu'une fois les données WU finalisées pour la journée

### Identification des marchés
- Les marchés suivent ce pattern d'URL : `https://polymarket.com/event/highest-temperature-in-london-on-[month]-[day]-[year]`
- Chaque tranche de température a un `token_id` unique (YES et NO)
- On peut les trouver via l'API Gamma : `https://gamma-api.polymarket.com/markets`

---

## 2. ARCHITECTURE GLOBALE

```
polymarket-weather-bot/
├── .env                      # Clés privées et config (NE PAS COMMIT)
├── .env.example              # Template du .env
├── requirements.txt          # Dépendances Python
├── config.py                 # Configuration centralisée
├── main.py                   # Point d'entrée — boucle principale
├── weather/
│   ├── __init__.py
│   ├── open_meteo.py         # API Open-Meteo (prévisions gratuites)
│   ├── wunderground.py       # Scraping/API Weather Underground
│   └── analyzer.py           # Analyse & distribution de probabilité
├── polymarket/
│   ├── __init__.py
│   ├── client.py             # Wrapper Polymarket CLOB API
│   ├── markets.py            # Scanner les marchés température Londres
│   └── trader.py             # Logique de placement d'ordres
├── strategy/
│   ├── __init__.py
│   └── edge_calculator.py    # Calcul de l'edge et décision de pari
├── notifications/
│   ├── __init__.py
│   └── telegram.py           # Notifications Telegram
├── utils/
│   ├── __init__.py
│   └── logger.py             # Logging structuré
└── logs/
    └── bot.log               # Fichier de log
```

---

## 3. FICHIERS DE CONFIGURATION

### `.env.example`
```env
# Polymarket
POLYMARKET_PRIVATE_KEY=your_private_key_here
POLYMARKET_FUNDER_ADDRESS=your_funder_address_here

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Config
CHECK_INTERVAL_HOURS=4
MAX_BET_USDC=10
MIN_EDGE_PERCENT=10
MAX_UNCERTAINTY_SPREAD_C=3
```

### `config.py`
```python
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
LONDON_CITY_AIRPORT_LAT = 51.5053
LONDON_CITY_AIRPORT_LON = 0.0553
WUNDERGROUND_STATION = "EGLC"
WUNDERGROUND_URL = "https://www.wunderground.com/history/daily/gb/london/EGLC"

# Stratégie
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "4"))
MAX_BET_USDC = float(os.getenv("MAX_BET_USDC", "10"))
MIN_EDGE_PERCENT = float(os.getenv("MIN_EDGE_PERCENT", "10"))
MAX_UNCERTAINTY_SPREAD_C = int(os.getenv("MAX_UNCERTAINTY_SPREAD_C", "3"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
```

---

## 4. MODULE MÉTÉO (`weather/`)

### `weather/open_meteo.py`
Utilise l'API gratuite Open-Meteo pour obtenir les prévisions.

**API Endpoint** : `https://api.open-meteo.com/v1/forecast`

**Paramètres clés** :
- `latitude` : 51.5053 (London City Airport)
- `longitude` : 0.0553
- `daily` : `temperature_2m_max`
- `timezone` : `Europe/London`
- `forecast_days` : 3

**Ce que la fonction doit retourner** :
```python
{
    "2026-02-11": {"max_temp": 12.3, "min_temp": 5.1},
    "2026-02-12": {"max_temp": 10.8, "min_temp": 4.2},
    "2026-02-13": {"max_temp": 11.5, "min_temp": 3.9}
}
```

**Exemple d'appel** :
```python
import requests

url = "https://api.open-meteo.com/v1/forecast"
params = {
    "latitude": 51.5053,
    "longitude": 0.0553,
    "daily": "temperature_2m_max,temperature_2m_min",
    "timezone": "Europe/London",
    "forecast_days": 3
}
response = requests.get(url, params=params)
data = response.json()
# data["daily"]["temperature_2m_max"] -> [12.3, 10.8, 11.5]
# data["daily"]["time"] -> ["2026-02-11", "2026-02-12", "2026-02-13"]
```

### `weather/wunderground.py`
Récupère les prévisions depuis Weather Underground (la source de résolution officielle).

**Approche** : Scraping de la page de prévision WU pour London City Airport.

**URL prévisions** : `https://www.wunderground.com/forecast/gb/london/EGLC`

**URL historique (résolution)** : `https://www.wunderground.com/history/daily/gb/london/EGLC/date/{YYYY-MM-DD}`

**Ce que la fonction doit retourner** : même format que open_meteo.

**Note importante** : WU est la source de VÉRITÉ pour la résolution. Si WU et Open-Meteo divergent, WU a priorité.

### `weather/analyzer.py`
Analyse les prévisions et calcule une distribution de probabilité par tranche de température.

**Logique** :
1. Récupérer les prévisions de Open-Meteo (et idéalement WU)
2. La prévision donne une température max (ex: 12.3°C)
3. On arrondit à l'entier (12°C) car Polymarket résout en degrés entiers
4. On construit une distribution de probabilité gaussienne autour de cette valeur
5. L'écart-type dépend de l'horizon de prévision :
   - J (aujourd'hui) : σ = 0.8°C (très fiable)
   - J+1 (demain) : σ = 1.2°C
   - J+2 (après-demain) : σ = 1.8°C

**Exemple de sortie** :
```python
# Si la prévision est 12.3°C pour demain (J+1), σ = 1.2
{
    "10": 0.04,   # 4% de chance que le max soit 10°C
    "11": 0.15,   # 15%
    "12": 0.38,   # 38% ← plus probable
    "13": 0.28,   # 28%
    "14+": 0.12,  # 12%
    "9-":  0.03   # 3%
}
```

**Calcul concret (scipy.stats.norm)** :
```python
from scipy.stats import norm

def build_probability_distribution(forecast_temp: float, sigma: float, 
                                     tranches: list[str]) -> dict[str, float]:
    """
    Construit la distribution de probabilité pour chaque tranche Polymarket.
    
    Args:
        forecast_temp: température prévue (ex: 12.3)
        sigma: écart-type basé sur l'horizon (ex: 1.2 pour J+1)
        tranches: liste des tranches du marché (ex: ["8-", "9", "10", "11", "12", "13", "14+"])
    
    Returns:
        dict avec la probabilité pour chaque tranche
    """
    dist = norm(loc=forecast_temp, scale=sigma)
    probabilities = {}
    
    for tranche in tranches:
        if tranche.endswith("-"):  # "8°C or below"
            threshold = int(tranche[:-1])
            prob = dist.cdf(threshold + 0.5)
        elif tranche.endswith("+"):  # "14°C or higher"  
            threshold = int(tranche[:-1])
            prob = 1 - dist.cdf(threshold - 0.5)
        else:  # "12°C" exact
            temp = int(tranche)
            prob = dist.cdf(temp + 0.5) - dist.cdf(temp - 0.5)
        probabilities[tranche] = round(prob, 4)
    
    return probabilities
```

---

## 5. MODULE POLYMARKET (`polymarket/`)

### `polymarket/client.py`
Wrapper autour de `py-clob-client`.

**Installation** :
```bash
pip install py-clob-client web3==6.14.0 python-dotenv
```

**Initialisation** :
```python
from py_clob_client.client import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    key=POLYMARKET_PRIVATE_KEY,
    chain_id=137,
    signature_type=1,  # Magic/Google wallet
    funder=POLYMARKET_FUNDER_ADDRESS
)
client.set_api_creds(client.create_or_derive_api_creds())
```

### `polymarket/markets.py`
Scanner et identifier les marchés "température Londres".

**Approche** : Utiliser l'API Gamma pour trouver les marchés.

**Endpoint** : `https://gamma-api.polymarket.com/events?slug=highest-temperature-in-london`

**Alternative** : `https://gamma-api.polymarket.com/markets?tag=Weather`

**Ce qu'on cherche** : 
- Les événements dont le titre contient "Highest temperature in London on"
- Pour chaque événement, récupérer les marchés (= tranches de température)
- Pour chaque marché, récupérer le `clob_token_ids` (YES et NO token IDs)
- Récupérer les prix actuels (= cotes du marché)

**Exemple de recherche** :
```python
import requests

def find_london_temperature_markets():
    """Trouve tous les marchés température Londres actifs."""
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "closed": False,
        "limit": 50
    }
    response = requests.get(url, params=params)
    events = response.json()
    
    london_events = []
    for event in events:
        if "highest temperature in london" in event.get("title", "").lower():
            london_events.append(event)
    
    return london_events
```

**Pour chaque marché, récupérer les cotes** :
```python
def get_market_prices(token_id: str) -> dict:
    """Récupère le prix bid/ask pour un token."""
    bid = float(client.get_price(token_id, side="BUY") or 0)
    ask = float(client.get_price(token_id, side="SELL") or 1)
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "mid": mid, "spread": ask - bid}
```

### `polymarket/trader.py`
Place les ordres sur Polymarket.

**Logique de pari** :
```python
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY

def place_bet(client, token_id: str, price: float, size: float):
    """
    Place un pari (limit order BUY YES) sur une tranche de température.
    
    Args:
        token_id: le YES token ID de la tranche choisie
        price: prix auquel on veut acheter (ex: 0.50 = on pense >50%)
        size: montant en USDC (ex: 10.0 pour 10$)
    """
    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=size / price,  # nombre de shares = montant / prix
        side=BUY
    )
    signed_order = client.create_order(order_args)
    response = client.post_order(signed_order)
    return response
```

**Note sur le sizing** : 
- Si on mise 10$ et le prix est 0.50$, on achète 20 shares
- Si notre prédiction est correcte, chaque share vaut 1.00$ → profit = 20 × 0.50$ = 10$
- Si incorrect → perte = 10$

---

## 6. MODULE STRATÉGIE (`strategy/`)

### `strategy/edge_calculator.py`
Cœur de la décision : faut-il parier et sur quelle tranche ?

**Logique** :

```python
def calculate_edge(our_probability: float, market_price: float) -> float:
    """
    Calcule l'edge (avantage) par rapport au marché.
    
    Si notre proba = 60% et le marché dit 40% (prix = 0.40),
    notre edge = (0.60 - 0.40) / 0.40 = 50%
    """
    if market_price <= 0:
        return 0
    return (our_probability - market_price) / market_price

def find_best_bet(probability_distribution: dict, market_prices: dict, 
                  min_edge: float = 0.10) -> dict | None:
    """
    Trouve le meilleur pari possible.
    
    Args:
        probability_distribution: nos probas calculées {tranche: proba}
        market_prices: prix du marché pour chaque tranche {tranche: price}
        min_edge: edge minimum pour parier (défaut 10%)
    
    Returns:
        Le meilleur pari ou None si aucun edge suffisant
    """
    best_bet = None
    best_edge = 0
    
    for tranche, our_prob in probability_distribution.items():
        market_price = market_prices.get(tranche, {}).get("ask", 1.0)
        
        if market_price >= 0.95:  # Déjà trop cher, pas d'intérêt
            continue
        if market_price <= 0.01:  # Pas de liquidité
            continue
            
        edge = calculate_edge(our_prob, market_price)
        
        if edge > best_edge and edge >= min_edge:
            best_edge = edge
            best_bet = {
                "tranche": tranche,
                "our_probability": our_prob,
                "market_price": market_price,
                "edge": edge,
                "expected_value": our_prob * (1 / market_price) - 1
            }
    
    return best_bet
```

### Conditions pour NE PAS parier :
1. **Incertitude trop grande** : si l'écart-type des prévisions > `MAX_UNCERTAINTY_SPREAD_C` (3°C par défaut)
2. **Pas d'edge** : aucune tranche avec un edge > `MIN_EDGE_PERCENT`
3. **Marché illiquide** : spread bid/ask trop large (> 15 centimes)
4. **Déjà parié** : on ne parie qu'une fois par marché (tracker dans un fichier JSON local)

---

## 7. MODULE NOTIFICATIONS (`notifications/`)

### `notifications/telegram.py`
Envoie des notifications via Telegram.

**Setup préalable** :
1. Créer un bot via @BotFather sur Telegram → récupérer le token
2. Démarrer une conversation avec le bot
3. Récupérer le chat_id via `https://api.telegram.org/bot{TOKEN}/getUpdates`

**Code** :
```python
import requests

def send_telegram(message: str, token: str, chat_id: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)
```

**Messages types** :
- `🔍 Scan effectué — Aucun edge trouvé pour le 12/02`
- `✅ PARI PLACÉ : 10$ sur 12°C pour le 12/02 (edge: 25%, notre proba: 45% vs marché: 36%)`
- `⚠️ Incertitude trop grande pour le 13/02 — écart entre sources: 4°C`
- `❌ Erreur API Polymarket : [détail]`

---

## 8. BOUCLE PRINCIPALE (`main.py`)

```python
import time
import schedule
from datetime import datetime, timedelta

def run_bot():
    """Boucle principale du bot."""
    log("🔄 Démarrage du scan...")
    
    # 1. Trouver les marchés ouverts (aujourd'hui, demain, après-demain)
    markets = find_london_temperature_markets()
    
    for market in markets:
        market_date = market["date"]  # ex: "2026-02-12"
        
        # 2. Vérifier si on a déjà parié sur ce marché
        if already_bet_on(market_date):
            log(f"⏭️ Déjà parié sur {market_date}, skip")
            continue
        
        # 3. Récupérer les prévisions météo
        forecasts = get_weather_forecasts(market_date)
        
        # 4. Vérifier la cohérence des sources
        if sources_diverge_too_much(forecasts):
            notify(f"⚠️ Sources divergent trop pour {market_date}")
            continue
        
        # 5. Calculer la distribution de probabilité
        days_ahead = (parse_date(market_date) - datetime.now().date()).days
        sigma = get_sigma_for_horizon(days_ahead)  # 0.8, 1.2, ou 1.8
        forecast_temp = average_forecast(forecasts)
        
        probabilities = build_probability_distribution(
            forecast_temp, sigma, market["tranches"]
        )
        
        # 6. Récupérer les cotes du marché
        market_prices = get_all_market_prices(market)
        
        # 7. Trouver le meilleur pari
        best_bet = find_best_bet(probabilities, market_prices)
        
        if best_bet is None:
            log(f"🔍 Aucun edge trouvé pour {market_date}")
            continue
        
        # 8. Placer le pari
        result = place_bet(
            client=polymarket_client,
            token_id=best_bet["token_id"],
            price=best_bet["market_price"],
            size=MAX_BET_USDC
        )
        
        # 9. Enregistrer le pari
        record_bet(market_date, best_bet, result)
        
        # 10. Notifier
        notify(f"✅ PARI : {MAX_BET_USDC}$ sur {best_bet['tranche']} "
               f"pour {market_date} (edge: {best_bet['edge']:.0%})")
    
    log("✅ Scan terminé")

# Lancer toutes les X heures
schedule.every(CHECK_INTERVAL_HOURS).hours.do(run_bot)

# Premier lancement immédiat
run_bot()

while True:
    schedule.run_pending()
    time.sleep(60)
```

---

## 9. REQUIREMENTS

### `requirements.txt`
```
py-clob-client
web3==6.14.0
python-dotenv
requests
beautifulsoup4
scipy
numpy
schedule
```

---

## 10. GUIDE D'INSTALLATION (pour l'utilisateur final)

### Étape 1 : Setup Polymarket
1. Se connecter sur polymarket.com avec Google
2. Aller dans Cash → 3 points → **Export Private Key**
3. Copier la clé privée
4. Récupérer l'adresse du funder (= l'adresse Polygon de ton wallet Polymarket)

### Étape 2 : Setup Telegram
1. Ouvrir Telegram, chercher **@BotFather**
2. Envoyer `/newbot`, suivre les instructions
3. Copier le **token** du bot
4. Envoyer un message au bot depuis son compte perso
5. Aller sur `https://api.telegram.org/bot{TOKEN}/getUpdates`
6. Copier le `chat_id`

### Étape 3 : Installation
```bash
git clone [repo]
cd polymarket-weather-bot
pip install -r requirements.txt
cp .env.example .env
# Éditer .env avec ses clés
```

### Étape 4 : Lancement
```bash
python main.py
```

Pour lancer en arrière-plan sur PC :
```bash
# Linux/Mac
nohup python main.py &

# Windows (PowerShell)
Start-Process python -ArgumentList "main.py" -WindowStyle Hidden
```

---

## 11. TRACKER DE PARIS (`bets_history.json`)

Fichier JSON local pour éviter de parier deux fois sur le même marché :

```json
{
    "2026-02-11": {
        "tranche": "12",
        "amount_usdc": 10,
        "price_paid": 0.42,
        "our_probability": 0.55,
        "edge": 0.31,
        "timestamp": "2026-02-11T08:30:00",
        "order_id": "xxx",
        "status": "placed"
    }
}
```

---

## 12. PARAMÈTRES AJUSTABLES

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `CHECK_INTERVAL_HOURS` | 4 | Fréquence de scan (heures) |
| `MAX_BET_USDC` | 10 | Mise max par pari ($) |
| `MIN_EDGE_PERCENT` | 10 | Edge minimum pour parier (%) |
| `MAX_UNCERTAINTY_SPREAD_C` | 3 | Écart max entre sources (°C) |
| σ J+0 | 0.8 | Écart-type prévision jour même |
| σ J+1 | 1.2 | Écart-type prévision lendemain |
| σ J+2 | 1.8 | Écart-type prévision J+2 |

---

## 13. ÉVOLUTIONS FUTURES (V2)

- [ ] Ajouter Claude API comme couche d'analyse supplémentaire
- [ ] Étendre à d'autres villes (Seoul, NYC, Tokyo — aussi sur Polymarket)
- [ ] Stratégie de trading (acheter puis revendre si la cote bouge)
- [ ] Dashboard web pour suivre les performances
- [ ] Déploiement sur VPS cloud (toujours actif)
- [ ] Backtesting sur données historiques
