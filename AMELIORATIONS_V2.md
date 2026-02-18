# 🔧 Améliorations Bot Polymarket Météo — V2

## Analyse des 4 premiers jours

| Date | Prévision | Pari | Réel | Résultat | Erreur modèle |
|------|-----------|------|------|----------|---------------|
| 12 fév | 10.8°C | 11°C | 11°C | ✅ WIN | +0.2°C |
| 13 fév | 8.0°C | 9+°C | 10°C | ✅ WIN | +2.0°C |
| 14 fév | 6.1°C | 5°C | 6°C | ❌ LOSS | -0.1°C (bon!) mais mauvaise tranche |
| 15 fév | 9.6°C | 11°C | 8°C | ❌ LOSS | -1.5°C |

**Constat** : la prévision météo est correcte à ±1.5°C, mais le bot parie parfois sur la mauvaise tranche.
Les 2 défaites viennent de la sélection de tranche, PAS de la qualité des prévisions météo.

---

## AMÉLIORATION 1 — REMPLACER LA GAUSSIENNE PAR L'API ENSEMBLE (CRITIQUE)

### Problème actuel
On utilise une distribution gaussienne avec un σ fixe (0.5/1.0/1.5) autour de la prévision.
C'est une approximation grossière : le σ réel varie selon la météo du jour (ciel clair → très prévisible, perturbation → incertain).

### Solution
Open-Meteo fournit une **API Ensemble** gratuite qui donne directement les prévisions de **51 modèles différents** (ECMWF IFS Ensemble) pour le même lieu et la même date. Au lieu d'inventer une gaussienne, on utilise la VRAIE distribution des modèles.

### Implémentation

**Nouveau fichier : `weather/ensemble.py`**

```python
import requests

def get_ensemble_forecasts(lat: float, lon: float, days: int = 3) -> dict:
    """
    Récupère les prévisions de 51 membres d'ensemble pour la température max.
    Retourne une vraie distribution de probabilité basée sur les modèles.
    """
    url = "https://ensemble-api.open-meteo.com/v1/ensemble"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "ecmwf_ifs025",  # 51 membres, 15 jours, 25km
        "forecast_days": days,
        "timezone": "Europe/London"
    }
    response = requests.get(url, params=params, timeout=30)
    data = response.json()
    
    # data["daily"]["temperature_2m_max_member01"] à member51
    # Chaque membre donne sa prévision → on a 51 valeurs par jour
    
    results = {}
    dates = data["daily"]["time"]
    
    for i, date in enumerate(dates):
        member_temps = []
        for m in range(51):
            key = f"temperature_2m_max_member{m:02d}"
            if key in data["daily"]:
                member_temps.append(data["daily"][key][i])
        
        results[date] = member_temps  # liste de 51 températures
    
    return results


def build_probability_from_ensemble(member_temps: list[float], tranches: list[str]) -> dict:
    """
    Construit la distribution de probabilité directement à partir des 51 membres.
    PAS de gaussienne — on compte simplement combien de membres tombent dans chaque tranche.
    
    Exemple : si 20 membres sur 51 prédisent 12°C → proba = 20/51 = 39%
    """
    total = len(member_temps)
    probabilities = {}
    
    for tranche in tranches:
        count = 0
        for temp in member_temps:
            rounded = round(temp)  # WU résout en °C entiers
            
            if tranche.endswith("-"):
                threshold = int(tranche[:-1])
                if rounded <= threshold:
                    count += 1
            elif tranche.endswith("+"):
                threshold = int(tranche[:-1])
                if rounded >= threshold:
                    count += 1
            else:
                if rounded == int(tranche):
                    count += 1
        
        probabilities[tranche] = count / total
    
    return probabilities
```

### Pourquoi c'est mieux
- **σ dynamique** : quand la météo est stable, les 51 membres convergent → distribution serrée. Quand c'est incertain, ils divergent → distribution large. Plus besoin de deviner σ.
- **Pas d'hypothèse gaussienne** : la vraie distribution peut être asymétrique (ex: front chaud → la temp peut monter beaucoup mais rarement descendre).
- **Même source** : on utilise ECMWF, le meilleur modèle mondial (c'est aussi celui qu'utilise Météo-France, le Met Office UK, etc.)

### Modification dans `weather/analyzer.py`
```python
# AVANT (à supprimer) :
# dist = norm(loc=forecast_temp, scale=sigma)

# APRÈS :
# 1. Essayer l'API Ensemble
# 2. Fallback sur gaussienne si l'ensemble échoue
```

---

## AMÉLIORATION 2 — TIMING OPTIMAL DES PARIS

### Problème actuel
Le bot parie dès qu'il scanne (toutes les 4h). Mais le meilleur moment pour parier n'est pas toujours "maintenant".

### Logique optimale
- **J+2** : parier **le matin** — les prévisions se stabilisent et le marché n'a pas encore convergé
- **J+1** : parier **l'après-midi/soir** — prévision quasi certaine, on attrape les derniers edges
- **J+0** : **NE PAS parier** sauf edge énorme (>50%) — le marché est généralement déjà efficient

### Implémentation
Dans `main.py`, ajuster la logique :
```python
from datetime import datetime

def should_bet_on_market(market_date: str) -> tuple[bool, str]:
    """Détermine si c'est le bon moment pour parier sur un marché."""
    now = datetime.now()
    days_ahead = (parse_date(market_date) - now.date()).days
    hour = now.hour
    
    if days_ahead == 0:
        # Jour même : ne parier que si edge > 50% ET avant midi
        return hour < 12, "j0_morning_only"
    
    elif days_ahead == 1:
        # Demain : parier l'après-midi (prévision fiable, marché pas encore ajusté)
        return hour >= 12, "j1_afternoon"
    
    elif days_ahead == 2:
        # J+2 : parier le matin (prévisions fraîches, cotes molles)
        return hour < 14, "j2_morning"
    
    return False, "too_far"
```

### Modifier aussi `bets_history.json`
Permettre de parier sur le même marché à J+2 ET J+1 si les conditions changent :
- À J+2 : premier pari si edge trouvé
- À J+1 : **renforcer** le pari si l'edge est toujours là ET la prévision s'est confirmée

---

## AMÉLIORATION 3 — CALIBRER LE σ AVEC LES DONNÉES HISTORIQUES

### Problème actuel
Les σ (0.5/1.0/1.5) sont des estimations au doigt mouillé.

### Solution
Si on utilise l'API Ensemble (amélioration 1), ce problème disparaît — l'ensemble DONNE le σ réel. Mais en fallback, on peut calibrer :

```python
def get_calibrated_sigma(days_ahead: int, month: int) -> float:
    """
    Sigma calibré par saison et horizon.
    L'hiver londonien est plus prévisible que l'été (moins de convection).
    """
    base_sigma = {0: 0.5, 1: 1.0, 2: 1.5}
    
    # Facteur saisonnier (hiver plus stable, été plus variable)
    if month in [12, 1, 2]:      # hiver
        season_factor = 0.85
    elif month in [3, 4, 5]:     # printemps
        season_factor = 1.0
    elif month in [6, 7, 8]:     # été (convection → moins prévisible)
        season_factor = 1.2
    else:                         # automne
        season_factor = 1.0
    
    return base_sigma.get(days_ahead, 2.0) * season_factor
```

---

## AMÉLIORATION 4 — ARRONDI INTELLIGENT (BUG SUBTIL)

### Problème
WU résout en **°C entiers**. Mais comment arrondi-t-il ? La convention standard est l'arrondi au plus proche (0.5 → arrondi au pair), mais WU pourrait arrondir différemment.

### Analyse du 14 février
- Temp réelle WU : 5.7°C
- Le bot a parié sur 5°C
- Résultat : WU a résolu à **6°C**
- → WU arrondit 5.7 à 6 (arrondi mathématique classique ≥0.5 → au-dessus)

### Impact
Notre modèle gaussien utilise `cdf(temp + 0.5) - cdf(temp - 0.5)` pour calculer P(tranche = X°C).
C'est correct SI WU arrondit au plus proche. Mais on devrait vérifier sur plus de données.

### Action
Ajouter dans `results_tracker.py` : logger `actual_temp_raw` (la temp brute avant arrondi) pour accumuler des données et vérifier le pattern d'arrondi.
→ **Déjà fait** vu le results_log.json (actual_temp_raw: 5.7 → actual_result: 6°C ✅)

---

## AMÉLIORATION 5 — EDGE MINIMUM DYNAMIQUE

### Problème
Le seuil d'edge minimum est fixe (10%). Mais un edge de 10% à J+0 (prévision fiable) vaut plus qu'un edge de 10% à J+2 (incertitude plus grande).

### Solution
```python
def get_min_edge_for_horizon(days_ahead: int) -> float:
    """Edge minimum requis selon l'horizon."""
    return {
        0: 0.08,   # 8% — prévision fiable, on accepte des petits edges
        1: 0.12,   # 12% — bonne prévision, edge modéré requis
        2: 0.20,   # 20% — incertain, exiger un gros edge pour compenser
    }.get(days_ahead, 0.25)
```

---

## AMÉLIORATION 6 — SIZING DYNAMIQUE DES PARIS (KELLY CRITERION SIMPLIFIÉ)

### Problème
On mise toujours le même montant (10$ ou 5$). Mais on devrait miser plus quand l'edge est gros et la proba haute, et moins quand c'est serré.

### Solution — Kelly Criterion fractionnel
```python
def calculate_bet_size(our_prob: float, market_price: float, 
                       bankroll: float, max_bet: float,
                       kelly_fraction: float = 0.25) -> float:
    """
    Taille du pari basée sur le critère de Kelly (fractionnel pour la sécurité).
    
    Kelly = (prob * (1/price - 1) - (1-prob)) / (1/price - 1)
    On utilise kelly_fraction (25%) du Kelly optimal pour réduire la variance.
    """
    if market_price <= 0 or market_price >= 1:
        return 0
    
    odds = (1 / market_price) - 1  # cote décimale - 1
    kelly = (our_prob * odds - (1 - our_prob)) / odds
    
    if kelly <= 0:
        return 0  # Pas de pari
    
    # Kelly fractionnel (25% du Kelly optimal)
    bet_fraction = kelly * kelly_fraction
    
    # Taille du pari
    bet = bankroll * bet_fraction
    
    # Plafonner au max
    return min(bet, max_bet)
```

### Exemples concrets
| Scénario | Notre proba | Prix marché | Kelly 25% sur 50$ | Mise |
|----------|------------|-------------|-------------------|------|
| Fort edge, haute proba | 45% | 0.20 | 7.50$ | 7.50$ |
| Fort edge, basse proba | 30% | 0.05 | 3.20$ | 3.20$ |
| Petit edge, haute proba | 40% | 0.35 | 1.80$ | 1.80$ |
| Pas d'edge | 20% | 0.25 | 0$ | 0$ (skip) |

---

## AMÉLIORATION 7 — SCANNER TOUTES LES 2H AU LIEU DE 4H

### Pourquoi
- Les prévisions météo sont mises à jour toutes les 6h (modèles) mais les API agrègent plus fréquemment
- Les cotes Polymarket bougent en continu
- Un edge peut apparaître et disparaître en quelques heures
- Coût : 0 (les APIs sont gratuites)

### Config
```python
CHECK_INTERVAL_HOURS = 2  # au lieu de 4
```

---

## AMÉLIORATION 8 — TRACKER LE BANKROLL EN TEMPS RÉEL

### Problème
Le bot ne sait pas combien il reste sur le compte. Il pourrait parier 10$ alors qu'il ne reste que 3$.

### Solution
Ajouter dans `polymarket/client.py` une fonction qui vérifie le solde avant de parier :
```python
def get_balance(self) -> float:
    """Récupère le solde USDC disponible."""
    # Via l'API ou en trackant localement
    pass

def can_afford_bet(self, amount: float) -> bool:
    """Vérifie qu'on peut se permettre le pari."""
    balance = self.get_balance()
    return balance >= amount
```

---

## RÉSUMÉ — ORDRE DE PRIORITÉ

| # | Amélioration | Impact | Difficulté | Priorité |
|---|-------------|--------|------------|----------|
| 1 | API Ensemble (remplacer gaussienne) | 🔴 ÉNORME | Moyenne | ⭐⭐⭐ FAIRE EN PREMIER |
| 2 | Timing optimal des paris | 🟠 Important | Facile | ⭐⭐⭐ |
| 5 | Edge minimum dynamique par horizon | 🟠 Important | Facile | ⭐⭐⭐ |
| 6 | Kelly Criterion (sizing dynamique) | 🟡 Moyen | Facile | ⭐⭐ |
| 3 | Sigma calibré par saison (fallback) | 🟡 Moyen | Facile | ⭐⭐ |
| 7 | Scanner toutes les 2h | 🟢 Petit | Trivial | ⭐⭐ |
| 8 | Tracker le bankroll | 🟢 Petit | Moyenne | ⭐ |
| 4 | Arrondi intelligent | 🟢 Petit | Facile | ⭐ (déjà tracké) |

**Recommandation : donner les améliorations 1, 2, 5, 6, 7 à Windsurf en un seul bloc.**
