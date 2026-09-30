"""forge_job_notify.py — Notification souveraine de fin de job aux clients dans la boucle.

Un job deporte (run_job) se termine -> Nokido EMET dans le canal que les clients
CLI pollent reellement : table `agent_messages` (base M2M, forge_db_path.m2m_path), status='unread'
(le défaut 'pending' n'est PAS vu par les poll-hooks). Chaque agent abonne (claude,
gemini, ...) recoit la ligne a son prochain tour via son inbox_tick.

Canal verifie : `tools/claude_inbox_tick.py` lit agent_messages WHERE to_agent=?
AND status='unread', prefere le champ `result`. Meme table que forge_coagulation_cascade.

Usage (in-process, depuis un script de job) :
    from forge_job_notify import notify_subscribers
    notify_subscribers(job_id, ["agt_claude", "agt_gemini"], result_text, method="job.complete")

CLI :
    LAFORGE_PYTHON tools/forge_job_notify.py --job JID --to agt_claude,agt_gemini --result "..."
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch
DB_PATH = Path(m2m_path())


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _mid(job_id: str, agent: str) -> str:
    raw = f"{job_id}|{agent}|{time.time()}"
    return "jobnotif_" + hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:20]


def _emit_event(kind: str, data: dict) -> None:
    """Best-effort : signale au systeme nerveux (non bloquant)."""
    try:
        import sys
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_postal import _emit  # type: ignore
        _emit(kind, data)
    except Exception:
        pass


def boite_de(nom: str) -> str:
    """Nom ou alias d'agent -> ADRESSE de boite `agt_<boite>`. '' si l'entree est vide.

    POURQUOI (mesure du 2026-09-09 dans la base M2M). `agent_messages` portait trois
    espaces de noms pour les memes acteurs -- `agt_claude` (1583) a cote de `CLAUDE`
    (12 non lus), `agt_gemini` a cote de `agt_agt_gemini` (14 non lus), `ANTIGRAVITY`
    en `pending` (11) a cote de `agt_antigravity`. Les tick de session lisent
    `WHERE to_agent=?`, UNE forme exacte : tout le reste dormait sans lecteur. Le
    destinataire etait insere BRUT, tel que l'appelant l'avait ecrit.

    On ne cree pas une cinquieme normalisation : le corps en a deja quatre et la
    mesure sur 1799 fichiers designe l'autorite -- `forge_postal.canonical`
    (29 appelants) rend la BOITE et connait les alias, `forge_videur.mailbox_de`
    (2 appelants) rend l'ADRESSE `agt_<boite>` depuis le MEME index. C'est cette
    seconde forme qu'attend la colonne `to_agent`, et il manquait seulement que les
    ECRIVAINS l'appellent.

    ⚠️ CE QUE CETTE FONCTION NE FAIT PAS, ET POURQUOI. Elle n'applique PAS le
    registre d'alias du videur (`mailbox_de`), bien qu'il soit la canonique du corps.
    Mesure du 2026-09-09 : `mailbox_de("agt_gemini")` rend **`agt_antigravity`** --
    le registre tient GEMINI et ANTIGRAVITY pour un SEUL acteur (`canonical` le dit :
    « agt_antigravity, AGY, GEMINI, AGY_DAEMON et GEMINI_RELAY designent tous la
    boite ANTIGRAVITY »). Or RULES_SHARED les distingue explicitement -- « DEUX files
    DISTINCTES : task assign agent=ANTIGRAVITY va dans tasks.db, draine par la
    surface Antigravity ; le postal GEMINI est draine par l'agent autonome » -- et la
    base porte du trafic REEL des deux cotes (agt_gemini 24, agt_antigravity 54).
    Router par le registre enverrait donc TOUT le courrier de Gemini chez Antigravity.

    Le registre et la doctrine divergent. Trancher lequel a raison est un arbitrage
    d'architecture, pas un effet de bord d'un correctif de notification : on s'en
    tient ici a la normalisation MECANIQUE (casse + prefixe), qui ne redirige le
    courrier de personne. Elle traite 26 des 37 messages orphelins mesures ce jour
    (12 sous `CLAUDE`, 14 sous `agt_agt_gemini`) ; les 11 d'`ANTIGRAVITY` en
    `pending` relevent de cet arbitrage, et restent DITS plutot que deplaces.
    """
    n = (nom or "").strip()
    if not n:
        return ""
    n = n.lower()
    while n.startswith("agt_agt_"):
        n = n[4:]
    return n if n.startswith("agt_") else "agt_" + n


def notify_subscribers(
    job_id: str,
    subscribers: list[str],
    result: str,
    *,
    method: str = "job.complete",
    from_agent: str = "agt_laforge",
    payload: dict | None = None,
) -> dict:
    """Insere une ligne unread dans agent_messages pour chaque abonne. Idempotence souple
    par id horodaté. Retourne {ok, delivered:[...], errors:[...]}."""
    delivered, errors = [], []
    pl = json.dumps(payload or {"job_id": job_id}, ensure_ascii=False)
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        for agent in subscribers:
            # La BOITE, pas le nom tel qu'on nous l'a donne : c'est la seule forme
            # que les tick interrogent.
            boite = boite_de(agent) or agent
            try:
                conn.execute(
                    "INSERT INTO agent_messages"
                    "(id, from_agent, to_agent, correlation_id, method, payload, result, status, created_at) "
                    "VALUES (?,?,?,?,?,?,?, 'unread', ?)",
                    (_mid(job_id, boite), from_agent, boite, job_id, method, pl, result, _now()),
                )
                # On rapporte la boite REELLEMENT ecrite, pas l'alias demande : sinon
                # le journal dit « notified ['CLAUDE'] » pour une ligne posee ailleurs.
                delivered.append(boite)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{agent}: {type(e).__name__}: {e}")
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        errors.append(f"db: {type(e).__name__}: {e}")
    _emit_event("job_complete", {"job_id": job_id, "subscribers": delivered, "method": method})
    return {"ok": not errors, "delivered": delivered, "errors": errors}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--to", required=True, help="csv: agt_claude,agt_gemini")
    ap.add_argument("--result", required=True)
    ap.add_argument("--method", default="job.complete")
    ap.add_argument("--from-agent", default="agt_laforge")
    a = ap.parse_args()
    subs = [x.strip() for x in a.to.split(",") if x.strip()]
    out = notify_subscribers(a.job, subs, a.result, method=a.method, from_agent=a.from_agent)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
