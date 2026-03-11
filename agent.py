"""
Agent IA autonome — surveillance et auto-correction du bot Polymarket Météo.
Se déclenche après chaque cycle de run_bot().
Utilise GPT pour analyser les logs et appliquer les corrections nécessaires.
"""

import json
import os
import subprocess
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("AGENT_MODEL", "gpt-4o")

PROJECT_ROOT = Path(__file__).parent.resolve()
BETS_HISTORY_FILE = PROJECT_ROOT / "bets_history.json"
RESULTS_LOG_FILE = PROJECT_ROOT / "results_log.json"
AGENT_LOG_FILE = PROJECT_ROOT / "logs" / "agent.log"
AGENT_DECISIONS_FILE = PROJECT_ROOT / "logs" / "agent_decisions.json"

SYSTEMD_SERVICE = "polymarket-bot"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYSTEM_PROMPT = """Tu es l'agent IA de surveillance et d'auto-correction d'un bot de trading de prédiction météo sur Polymarket.

Le bot parie sur la température maximale journalière à Londres (°C) sur les marchés Polymarket.
Il utilise les prévisions ensemble ECMWF (51 membres) avec une correction de biais de +1°C pour Londres.
Le bot tourne toutes les 2h et parie en dry run (simulation) pour l'instant.

Ton rôle :
1. Analyser les données fournies (historique paris, résultats, logs récents)
2. Détecter les problèmes : biais de prévision, seuils inadaptés, bugs, anomalies
3. Décider des corrections nécessaires
4. Retourner tes décisions en JSON structuré

Règles importantes :
- Ne modifie QUE ce qui est clairement justifié par les données
- Pour le biais de prévision : calcule la moyenne des forecast_error sur les 5 derniers jours
  Si moyenne > +1.5°C (bot trop froid) → augmente LONDON_BIAS_CORRECTION
  Si moyenne < -1.5°C (bot trop chaud) → diminue LONDON_BIAS_CORRECTION
  Si moyenne entre -1.5 et +1.5 → ne touche pas
- Pour MIN_EDGE_PERCENT : ne descends jamais sous 10, ne monte jamais au-dessus de 30
- Pour KELLY_FRACTION : ne descends jamais sous 0.1, ne monte jamais au-dessus de 0.5
- Si tu vois 3 pertes consécutives ou plus : recommande d'augmenter MIN_EDGE_PERCENT de 2 points
- Sois conservateur : "ne rien faire" est souvent la bonne décision

Format de réponse OBLIGATOIRE (JSON pur, aucun texte autour) :
{
  "action": "none" | "update_env" | "update_code" | "restart" | "alert",
  "reason": "explication courte en français",
  "analysis": "analyse détaillée des données en français",
  "env_changes": {"CLE": "nouvelle_valeur"},
  "code_changes": [{"file": "chemin/fichier.py", "description": "ce qui change", "old_code": "...", "new_code": "..."}],
  "telegram_message": "message court pour Telegram",
  "severity": "info" | "warning" | "critical"
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def agent_log(msg: str):
    AGENT_LOG_FILE.parent.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(AGENT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        agent_log(f"Telegram erreur: {e}")


def load_json_file(path: Path) -> dict | list:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json_file(path: Path, data: dict | list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_recent_systemd_logs(lines: int = 100) -> str:
    try:
        result = subprocess.run(
            ["journalctl", "-u", SYSTEMD_SERVICE, "-n", str(lines), "--no-pager", "--output=short"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout[-8000:] if result.stdout else "Logs non disponibles"
    except Exception as e:
        return f"Erreur récupération logs: {e}"


def get_recent_results(n: int = 10) -> list:
    results = load_json_file(RESULTS_LOG_FILE)
    if isinstance(results, list):
        return results[-n:]
    return []


def get_recent_bets(n: int = 10) -> dict:
    history = load_json_file(BETS_HISTORY_FILE)
    if isinstance(history, dict):
        items = list(history.items())[-n:]
        return dict(items)
    return {}


def read_env_file() -> dict:
    env_path = PROJECT_ROOT / ".env"
    env = {}
    if not env_path.exists():
        return env
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


PROTECTED_ENV_KEYS = {"AGENT_MODEL", "OPENAI_API_KEY", "POLYMARKET_PRIVATE_KEY", "TELEGRAM_BOT_TOKEN"}


def update_env_file(changes: dict):
    # Filtrer les clés protégées
    changes = {k: v for k, v in changes.items() if k not in PROTECTED_ENV_KEYS}
    if not changes:
        agent_log("⚠️ Toutes les modifications demandées concernent des clés protégées — ignorées")
        return

    env_path = PROJECT_ROOT / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in changes:
                new_lines.append(f"{key}={changes[key]}\n")
                updated_keys.add(key)
                agent_log(f"⚙️ .env: {key} → {changes[key]}")
                continue
        new_lines.append(line)

    # Ajouter les clés nouvelles qui n'existaient pas
    for key, val in changes.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")
            agent_log(f"⚙️ .env: ajout {key}={val}")

    with open(env_path, "w") as f:
        f.writelines(new_lines)


def apply_code_change(file: str, old_code: str, new_code: str) -> bool:
    filepath = PROJECT_ROOT / file
    if not filepath.exists():
        agent_log(f"❌ Fichier introuvable: {file}")
        return False
    try:
        content = filepath.read_text(encoding="utf-8")
        if old_code not in content:
            agent_log(f"❌ Code à remplacer non trouvé dans {file}")
            return False
        new_content = content.replace(old_code, new_code, 1)
        filepath.write_text(new_content, encoding="utf-8")
        agent_log(f"✅ Code modifié: {file}")
        return True
    except Exception as e:
        agent_log(f"❌ Erreur modification {file}: {e}")
        return False


def restart_bot():
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", SYSTEMD_SERVICE],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            agent_log("🔄 Bot redémarré avec succès")
            return True
        else:
            agent_log(f"❌ Erreur restart: {result.stderr}")
            return False
    except Exception as e:
        agent_log(f"❌ Erreur restart: {e}")
        return False


def save_decision(decision: dict):
    AGENT_DECISIONS_FILE.parent.mkdir(exist_ok=True)
    decisions = []
    if AGENT_DECISIONS_FILE.exists():
        try:
            with open(AGENT_DECISIONS_FILE, "r") as f:
                decisions = json.load(f)
        except Exception:
            decisions = []
    decision["timestamp"] = datetime.now().isoformat()
    decisions.append(decision)
    decisions = decisions[-100:]  # garder les 100 dernières
    save_json_file(AGENT_DECISIONS_FILE, decisions)


# ---------------------------------------------------------------------------
# Calcul biais récent (pour contexte GPT)
# ---------------------------------------------------------------------------

def compute_recent_bias_summary(results: list) -> str:
    errors = [r["forecast_error"] for r in results if r.get("forecast_error") is not None]
    if not errors:
        return "Pas encore de données d'écart prévision/réalité disponibles."
    mean_err = sum(errors) / len(errors)
    direction = "trop froid" if mean_err < 0 else "trop chaud" if mean_err > 0 else "exact"
    return (
        f"Écarts prévision/réalité sur {len(errors)} jours: "
        f"moyenne={mean_err:+.2f}°C ({direction}), "
        f"détail={[f'{e:+.1f}' for e in errors[-5:]]}"
    )


# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------

def run_agent():
    agent_log("🤖 Agent IA démarré")

    if not OPENAI_API_KEY:
        agent_log("❌ OPENAI_API_KEY manquante dans .env")
        return

    # Collecte des données
    recent_results = get_recent_results(10)
    recent_bets = get_recent_bets(10)
    systemd_logs = get_recent_systemd_logs(80)
    current_env = read_env_file()

    # Structure du projet pour que GPT sache quels fichiers existent
    project_structure = """
Fichiers modifiables du projet (chemins relatifs depuis la racine) :
- agent.py
- main.py
- config.py
- cities.py
- strategy/edge_calculator.py
- weather/analyzer.py
- weather/ensemble.py
- weather/open_meteo.py
- weather/wunderground.py
- results_tracker.py
- polymarket/client.py
- polymarket/markets.py
- polymarket/trader.py
- notifications/telegram.py
"""

    bias_summary = compute_recent_bias_summary(recent_results)

    # Statistiques rapides
    london_results = [r for r in recent_results if r.get("city_id") == "london"]
    wins = sum(1 for r in london_results if r.get("would_have_won"))
    total = len(london_results)
    winrate = f"{wins}/{total} ({wins/total:.0%})" if total > 0 else "aucun résultat"

    # Préparer le contexte pour GPT
    context = f"""
=== ÉTAT DU BOT — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===

STRUCTURE DU PROJET:
{project_structure}

CONFIG ACTUELLE (.env):
{json.dumps({k: v for k, v in current_env.items() if not 'KEY' in k and not 'TOKEN' in k and not 'CHAT' in k}, indent=2)}

WINRATE RÉCENT LONDON: {winrate}

BIAIS PRÉVISION:
{bias_summary}

DERNIERS RÉSULTATS ({len(recent_results)} entrées):
{json.dumps(recent_results, indent=2, ensure_ascii=False)}

DERNIERS PARIS ({len(recent_bets)} entrées):
{json.dumps(recent_bets, indent=2, ensure_ascii=False)}

LOGS SYSTEMD (dernières lignes):
{systemd_logs}
"""

    # Appel GPT
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        agent_log(f"📡 Appel {OPENAI_MODEL}...")
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            temperature=0.1,
            max_completion_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        agent_log(f"✅ Réponse reçue ({len(raw)} chars)")
    except Exception as e:
        agent_log(f"❌ Erreur OpenAI: {e}")
        return

    # Parser la décision
    try:
        # Nettoyer le JSON si GPT l'a entouré de backticks
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        decision = json.loads(raw)
    except json.JSONDecodeError as e:
        agent_log(f"❌ JSON invalide dans la réponse GPT: {e}\nRaw: {raw[:500]}")
        return

    action = decision.get("action", "none")
    reason = decision.get("reason", "")
    severity = decision.get("severity", "info")
    analysis = decision.get("analysis", "")

    agent_log(f"🧠 Décision: {action} | {severity} | {reason}")
    save_decision(decision)

    # Exécuter la décision
    restart_needed = False
    actions_done = []

    if action == "none":
        agent_log("✅ Aucune action nécessaire")

    elif action in ("update_env", "restart"):
        env_changes = decision.get("env_changes", {})
        if env_changes:
            update_env_file(env_changes)
            actions_done.append(f"Config mise à jour: {env_changes}")
            restart_needed = True

    elif action == "update_code":
        code_changes = decision.get("code_changes", [])
        for change in code_changes:
            file = change.get("file", "")
            old_code = change.get("old_code", "")
            new_code = change.get("new_code", "")
            desc = change.get("description", "")
            if file and old_code and new_code:
                success = apply_code_change(file, old_code, new_code)
                if success:
                    actions_done.append(f"Code modifié [{file}]: {desc}")
                    restart_needed = True

    elif action == "alert":
        agent_log(f"🚨 ALERTE: {reason}")

    # Ne redémarre que si modification de code, pas juste de config
    if restart_needed and action == "update_code":
        restart_bot()

    # Notification Telegram
    telegram_msg = decision.get("telegram_message", "")
    if telegram_msg or severity in ("warning", "critical") or actions_done:
        emoji_map = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        emoji = emoji_map.get(severity, "ℹ️")
        full_msg = f"{emoji} *Agent IA — {datetime.now().strftime('%H:%M')}*\n"
        if telegram_msg:
            full_msg += f"{telegram_msg}\n"
        if actions_done:
            full_msg += "\n*Actions effectuées:*\n" + "\n".join(f"• {a}" for a in actions_done)
        if analysis and severity != "info":
            full_msg += f"\n\n_{analysis[:300]}_"
        send_telegram(full_msg)

    agent_log(f"🏁 Agent terminé — action={action}, restart={restart_needed}")


# ---------------------------------------------------------------------------
# Entry point (peut aussi être appelé depuis main.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        run_agent()
    except Exception as e:
        agent_log(f"💀 CRASH agent: {e}\n{traceback.format_exc()}")
