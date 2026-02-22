# 🌍 SPECS — Passage Multi-Villes du Bot Météo Polymarket

## Contexte

Le bot actuel (`BOT_METEO_LONDON`) parie uniquement sur la température max à Londres. On veut l'étendre pour couvrir **toutes les villes disponibles** sur Polymarket, sans casser le fonctionnement existant. Le bot doit scanner TOUTES les villes à chaque cycle et choisir les meilleurs paris toutes villes confondues.

Repo GitHub : `https://github.com/bigsterwinster/BOT_METEO_LONDON`

---

## 1. DONNÉES DES VILLES (mapping complet vérifié)

Créer un fichier `cities.py` à la racine avec cette configuration :

```python
CITIES = {
    "london": {
        "name": "London",
        "slug_pattern": "highest-temperature-in-london-on-{month}-{day}-{year}",
        "lat": 51.5053,
        "lon": 0.0553,
        "wu_station": "EGLC",
        "wu_history_url": "https://www.wunderground.com/history/daily/gb/london/EGLC",
        "unit": "celsius",       # Résolution en °C entiers
        "timezone": "Europe/London",
    },
    "nyc": {
        "name": "NYC",
        "slug_pattern": "highest-temperature-in-nyc-on-{month}-{day}-{year}",
        "lat": 40.7769,          # LaGuardia Airport
        "lon": -73.8740,
        "wu_station": "KLGA",
        "wu_history_url": "https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
        "unit": "fahrenheit",    # ⚠️ NYC résout en °F entiers !
        "timezone": "America/New_York",
    },
    "seoul": {
        "name": "Seoul",
        "slug_pattern": "highest-temperature-in-seoul-on-{month}-{day}-{year}",
        "lat": 37.4602,          # Incheon Intl Airport
        "lon": 126.4407,
        "wu_station": "RKSI",
        "wu_history_url": "https://www.wunderground.com/history/daily/kr/incheon/RKSI",
        "unit": "celsius",
        "timezone": "Asia/Seoul",
    },
    "toronto": {
        "name": "Toronto",
        "slug_pattern": "highest-temperature-in-toronto-on-{month}-{day}-{year}",
        "lat": 43.6777,          # Toronto Pearson (à vérifier via les rules Polymarket)
        "lon": -79.6248,
        "wu_station": "CYYZ",    # À VÉRIFIER — checker les rules du marché Polymarket Toronto
        "wu_history_url": "https://www.wunderground.com/history/daily/ca/toronto/CYYZ",
        "unit": "celsius",       # À VÉRIFIER
        "timezone": "America/Toronto",
    },
    "chicago": {
        "name": "Chicago",
        "slug_pattern": "highest-temperature-in-chicago-on-{month}-{day}-{year}",
        "lat": 41.9742,          # O'Hare (à vérifier)
        "lon": -87.9073,
        "wu_station": "KORD",    # À VÉRIFIER
        "wu_history_url": "https://www.wunderground.com/history/daily/us/il/chicago/KORD",
        "unit": "fahrenheit",    # US cities = Fahrenheit
        "timezone": "America/Chicago",
    },
    "atlanta": {
        "name": "Atlanta",
        "slug_pattern": "highest-temperature-in-atlanta-on-{month}-{day}-{year}",
        "lat": 33.6407,          # Hartsfield-Jackson (à vérifier)
        "lon": -84.4277,
        "wu_station": "KATL",    # À VÉRIFIER
        "wu_history_url": "https://www.wunderground.com/history/daily/us/ga/atlanta/KATL",
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "miami": {
        "name": "Miami",
        "slug_pattern": "highest-temperature-in-miami-on-{month}-{day}-{year}",
        "lat": 25.7959,          # Miami Intl (à vérifier)
        "lon": -80.2870,
        "wu_station": "KMIA",    # À VÉRIFIER
        "wu_history_url": "https://www.wunderground.com/history/daily/us/fl/miami/KMIA",
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "dallas": {
        "name": "Dallas",
        "slug_pattern": "highest-temperature-in-dallas-on-{month}-{day}-{year}",
        "lat": 32.8998,          # DFW Airport (à vérifier)
        "lon": -97.0403,
        "wu_station": "KDFW",    # À VÉRIFIER
        "wu_history_url": "https://www.wunderground.com/history/daily/us/tx/dallas/KDFW",
        "unit": "fahrenheit",
        "timezone": "America/Chicago",
    },
    "seattle": {
        "name": "Seattle",
        "slug_pattern": "highest-temperature-in-seattle-on-{month}-{day}-{year}",
        "lat": 47.4502,          # SeaTac (à vérifier)
        "lon": -122.3088,
        "wu_station": "KSEA",    # À VÉRIFIER
        "wu_history_url": "https://www.wunderground.com/history/daily/us/wa/seattle/KSEA",
        "unit": "fahrenheit",
        "timezone": "America/Los_Angeles",
    },
    "ankara": {
        "name": "Ankara",
        "slug_pattern": "highest-temperature-in-ankara-on-{month}-{day}-{year}",
        "lat": 40.1281,          # Esenboga Airport (à vérifier)
        "lon": 32.9951,
        "wu_station": "LTAC",    # À VÉRIFIER
        "wu_history_url": "https://www.wunderground.com/history/daily/tr/ankara/LTAC",
        "unit": "celsius",
        "timezone": "Europe/Istanbul",
    },
}
```

### ⚠️ IMPORTANT — Vérification des stations

Pour chaque ville marquée "À VÉRIFIER", il faut aller sur Polymarket, trouver un marché actif pour cette ville (ex: `polymarket.com/event/highest-temperature-in-toronto-on-february-23-2026`), lire les "Rules", et vérifier :
1. La station WU exacte utilisée pour la résolution
2. L'unité (Celsius ou Fahrenheit)
3. L'URL WU de résolution

Les 3 villes **déjà vérifiées** sont : London (EGLC, °C), NYC (KLGA, °F), Seoul (RKSI, °C).

---

## 2. FICHIERS À MODIFIER

### 2.1. `config.py` — Supprimer les constantes spécifiques Londres

Supprimer ces lignes :
```python
# SUPPRIMER :
LONDON_CITY_AIRPORT_LAT = 51.5053
LONDON_CITY_AIRPORT_LON = 0.0553
WUNDERGROUND_STATION = "EGLC"
WUNDERGROUND_URL = "https://www.wunderground.com/history/daily/gb/london/EGLC"
```

Ajouter :
```python
# Villes actives (liste de city_id depuis cities.py)
# Peut être overridé par ACTIVE_CITIES dans .env (comma-separated)
import os
ACTIVE_CITIES = os.getenv("ACTIVE_CITIES", "london,nyc,seoul,toronto,ankara").split(",")
```

### 2.2. `polymarket/markets.py` — Généraliser pour toutes les villes

Renommer `find_london_temperature_markets()` → `find_temperature_markets(city_config: dict)`

Le slug se construit maintenant avec `city_config["slug_pattern"]` :
```python
slug = city_config["slug_pattern"].format(month=month, day=day, year=year)
```

Le résultat doit inclure le `city_id` dans chaque market dict :
```python
{
    "city_id": "nyc",
    "city_name": "NYC",
    "event_id": "...",
    "title": "...",
    "date": "2026-02-23",
    "unit": "fahrenheit",
    "tranches": [...]
}
```

### 2.3. `weather/open_meteo.py` — Accepter lat/lon en paramètre

```python
def get_forecasts(lat: float, lon: float, timezone: str = "Europe/London", forecast_days: int = 3) -> dict | None:
```

Ne plus importer les constantes Londres depuis config.

### 2.4. `weather/wunderground.py` — Accepter lat/lon en paramètre

```python
def get_forecasts(lat: float, lon: float, forecast_days: int = 5) -> dict | None:
```

Le `geocode` dans les params WU utilise les lat/lon passés.

### 2.5. `weather/ensemble.py` — Accepter lat/lon en paramètre

```python
def get_ensemble_forecasts(lat: float, lon: float, timezone: str = "Europe/London", days: int = 3) -> dict[str, list[float]] | None:
```

**ATTENTION CRITIQUE pour les villes en Fahrenheit (US cities) :** Open-Meteo retourne toujours en °C. Pour les villes US, il faut convertir les températures des 51 membres en °F AVANT de les comparer aux tranches Polymarket. Ajouter un paramètre `unit` et faire la conversion dans `build_probability_from_ensemble()`.

### 2.6. `weather/analyzer.py` — Passer la config ville partout

```python
def get_weather_forecasts(target_date: str, city_config: dict) -> dict:
def get_probability_distribution(target_date, tranches, days_ahead, forecast_temp=None, city_config=None) -> tuple:
```

### 2.7. `main.py` — Boucle sur toutes les villes

La boucle principale devient :
```python
from cities import CITIES
from config import ACTIVE_CITIES

def run_bot():
    for city_id in ACTIVE_CITIES:
        city_config = CITIES[city_id]
        markets = find_temperature_markets(city_config)
        for market in markets:
            # ... même logique qu'avant, mais avec city_config passé partout
```

L'historique des paris (`bets_history.json`) doit utiliser la clé `f"{city_id}_{market_date}"` au lieu de juste `market_date`.

### 2.8. `notifications/telegram.py` — Inclure le nom de la ville

Tous les messages Telegram doivent inclure le nom de la ville. Ex :
```
🔴 PARI PLACÉ — Seoul
5.00$ sur 8°C @ 0.35 (edge: 28%)
Date: 2026-02-24 (J+1)
```

### 2.9. `results_tracker.py` — Adapter pour multi-villes

La vérification des résultats doit itérer sur toutes les villes et utiliser la bonne source WU pour chaque ville.

---

## 3. GESTION FAHRENHEIT vs CELSIUS (CRITIQUE)

C'est le point le plus délicat. NYC, Chicago, Atlanta, Miami, Dallas, Seattle utilisent des **tranches en °F** sur Polymarket (ex: "38-39°F", "40-41°F", "42°F or higher").

### Changements nécessaires dans `_extract_tranche_label()` :

Les marchés US ont des tranches au format :
- `"38-39°F"` → label `"38-39"` (range de 2°F)
- `"36-37°F"` → label `"36-37"`
- `"34°F or below"` → label `"34-"`
- `"42°F or higher"` → label `"42+"`

C'est **différent** de Londres/Seoul qui ont des tranches de 1°C exactement (ex: "8°C", "9°C").

### Changements dans `build_probability_from_ensemble()` :

Pour les villes US :
1. Les 51 températures des membres ensemble arrivent en °C
2. Il faut les convertir en °F : `temp_f = temp_c * 9/5 + 32`
3. Puis les arrondir à l'entier °F
4. Puis les mapper dans les tranches de 2°F

### Changements dans `build_probability_distribution_gaussian()` (fallback) :

Idem — la gaussienne doit travailler en °F pour les villes US.

---

## 4. STRUCTURE DES FICHIERS APRÈS REFACTORING

```
BOT_METEO_LONDON/           (on peut renommer le repo plus tard)
├── cities.py               ← NOUVEAU — config de toutes les villes
├── config.py               ← MODIFIÉ — sans constantes Londres
├── main.py                 ← MODIFIÉ — boucle multi-villes
├── polymarket/
│   ├── client.py           ← INCHANGÉ
│   ├── markets.py          ← MODIFIÉ — find_temperature_markets(city_config)
│   └── trader.py           ← INCHANGÉ
├── weather/
│   ├── analyzer.py         ← MODIFIÉ — city_config en paramètre
│   ├── ensemble.py         ← MODIFIÉ — lat/lon + conversion °F
│   ├── open_meteo.py       ← MODIFIÉ — lat/lon en paramètre
│   └── wunderground.py     ← MODIFIÉ — lat/lon en paramètre
├── strategy/
│   └── edge_calculator.py  ← INCHANGÉ
├── notifications/
│   └── telegram.py         ← MODIFIÉ — inclure nom ville
├── results_tracker.py      ← MODIFIÉ — multi-villes
├── bets_history.json
├── results_log.json
└── .env
```

---

## 5. VARIABLES D'ENVIRONNEMENT (.env)

Ajouter :
```env
# Villes actives (comma-separated, défaut = toutes)
ACTIVE_CITIES=london,nyc,seoul,toronto,ankara
```

Cela permet de facilement activer/désactiver des villes sans changer le code.

---

## 6. PRIORITÉ D'IMPLÉMENTATION

1. **D'abord** : créer `cities.py` et refactorer les weather modules pour accepter lat/lon
2. **Ensuite** : refactorer `markets.py` pour supporter le slug pattern configurable
3. **Puis** : gérer la conversion °F pour les villes US (c'est le plus délicat)
4. **Puis** : adapter `main.py` pour la boucle multi-villes
5. **Enfin** : adapter notifications et results_tracker
6. **Tester** en DRY RUN avec London + NYC pendant 1-2 jours avant d'activer les autres villes

---

## 7. TESTS À EFFECTUER

1. Vérifier que le bot trouve les marchés pour chaque ville active (via les slugs)
2. Vérifier que l'API Open-Meteo Ensemble retourne bien des données pour chaque ville
3. Vérifier que les tranches sont correctement parsées (°C simple pour Londres/Seoul, °F range pour NYC)
4. Vérifier que la conversion °C→°F dans l'ensemble fonctionne correctement
5. DRY RUN pendant 1-2 jours avec London + NYC, vérifier que les paris simulés sont cohérents
6. Comparer les prévisions ensemble avec les résolutions WU pour valider la calibration

---

## 8. SÉLECTION INTER-VILLES (NOUVEAU)

Avec plusieurs villes, le bot aura potentiellement plusieurs bons paris par scan. La stratégie :

- Scanner TOUTES les villes et collecter TOUS les paris avec edge positif
- Trier par score (EV × proba²) décroissant
- Placer les N meilleurs paris (limité par le budget / Kelly Criterion)
- Ne PAS dépasser le BANKROLL total

Dans `main.py`, au lieu de placer un pari immédiatement dans la boucle, collecter tous les candidats dans une liste, puis trier et placer les meilleurs.
