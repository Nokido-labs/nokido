"""Lanceur AUTOMATIQUE du secours de la synthese swarm (ring <= 3, identite du coffre via le client hub existant).

Justification (anti-dup) : forge_cli_swarm porte deja le depot (_deposer_tache), le statut (_statut_tache) et
l'integration gardee (_integrer_secours) ; il ne peut pas les lancer lui-meme (task assign/status refuses au ring 4,
garde CONSERVEE). Aucune brique existante ne balaie les JSON cli_swarm_ptr_* : ce module n'est que la colle,
il REUTILISE ces fonctions, sans contourner aucune garde. Un passage = un balayage du seul dossier sandbox/.
Mise en service (tache planifiee / service) : decision owner, rien n'est active ici.

Usage : python tools/forge_secours_lanceur.py [dossier]   (un passage ; a planifier par l'owner)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402

__FORGE_COLOR__ = "locomoteur-orchestration"

FENETRE_S = 24 * 3600
DELAI_EXECUTEUR_S = 600


AGENT = "SWARM_LANCEUR"
CLE_COFFRE = "FORGE_TOKEN_SWARM_LANCEUR"
MOTIF_IDENTITE = "identité SWARM_LANCEUR indisponible"


def _get_secret(cle: str):
    from nokido_agent.app.forge_secrets import get_secret  # coffre existant
    return get_secret(cle)


def _jeton_session(secret: str) -> str:
    """CapabilityToken de SWARM_LANCEUR par le guichet existant (login_agent, bail 30 min).
    Mesure 29/10 12 h 08 : le hub repond 401 au secret BRUT et 200 au CapabilityToken (sonde_jeton_swarm_lanceur.py)."""
    from nokido_agent.app.forge_auth_tokens import login_agent
    return login_agent(AGENT, secret_id=secret)


def _echange_job():
    """Voie RFC 8693 : jeton de job (env NOKIDO_JOB_SUBJECT_TOKEN + NOKIDO_JOB_ID) echange contre
    un jeton DPoP court. None si pas de jeton de job ou route muette -> l'ancien chemin sert."""
    import os
    try:
        from nokido_agent.app.forge_agent_credential import jeton_sujet_du_job
    except ImportError:  # repli checkout
        from forge_agent_credential import jeton_sujet_du_job
    sub, job = jeton_sujet_du_job(), os.environ.get("NOKIDO_JOB_ID")
    if not sub or not job:
        return None
    try:
        import urllib.parse
        import urllib.request
        from app import forge_dpop
        from app.forge_coffre_cloisonne import cle_ephemere
        from app.forge_mpc_executor import _HUB
        url, cle = "%s/oauth/token" % _HUB, cle_ephemere()
        corps = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": sub,
            "subject_token_type": "urn:nokido:params:oauth:token-type:job", "job_id": job,
            "audience": "hub", "scope": "task:status task:assign"}).encode()
        req = urllib.request.Request(url, data=corps, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "DPoP": forge_dpop.creer_preuve("POST", url, cle=cle)})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("access_token")
    except Exception:  # noqa: BLE001 -- route muette ou refus : ancien chemin
        return None


def _session_pour(secret: str) -> str:
    """Echange si la route repond, sinon ancien chemin login_agent INCHANGE."""
    return _echange_job() or _jeton_session(secret)


def _http(url: str, payload: bytes, headers: dict) -> str:
    import urllib.request
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    content = data.get("result", {}).get("content", [])
    return content[0].get("text", "") if content else str(data)


def _appel_identite(outil: str, arguments: dict) -> str:
    """Appel hub sous l'identite SWARM_LANCEUR (ring 3). Jeton absent -> erreur, JAMAIS de repli sur FORGE_MCP_TOKEN.

    29/10 (audit AGY du coffre) : l'echange RFC 8693 est tente AVANT toute lecture du coffre ; le secret de l'identite
    ring 3 n'est lu qu'en repli, faute de jeton de job. NR tests/nr/test_secours_lanceur_echange_avant_coffre_nr.py.
    """
    session = _echange_job()
    if not session:
        try:
            jeton = _get_secret(CLE_COFFRE)
        except Exception:  # noqa: BLE001
            jeton = None
        if not jeton:
            raise RuntimeError(MOTIF_IDENTITE)
        try:
            session = _jeton_session(jeton)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("identité SWARM_LANCEUR refusée au guichet (%s)" % type(e).__name__) from None
    from app.forge_mpc_executor import _HUB
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": outil, "arguments": arguments}}).encode()
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + session,
               "LaForge-Agent-Name": AGENT}
    return _http("%s/mcp" % _HUB, payload, headers)


def _ecrire(p: Path, res: dict) -> None:
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


TASKS_DB = _RACINE_DONNEES / "sandbox" / "tasks.db"


def _texte_complet(tid: str) -> str:
    """Texte COMPLET rendu par l'executeur, lu par cle primaire (lecture seule) APRES un statut termine lu au ring 3.

    29/10 : le `result_summary` du statut (tronque, porteur du verdict du juge) a ete integre comme synthese. Le champ
    `result` contient la sortie JSON du CLI (`{"type":"result","result":"<texte>"...}`) ; la ligne finale de verdict
    `{"intent": ...}` est retiree."""
    import re
    import sqlite3
    con = sqlite3.connect(f"file:{Path(TASKS_DB).as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT result FROM tasks WHERE id = ?", (tid,)).fetchone()
    finally:
        con.close()
    brut = str(row[0]) if row and row[0] else ""
    texte = brut
    i = brut.find("{")
    while i != -1:
        try:
            obj, _fin = json.JSONDecoder().raw_decode(brut[i:])
            if isinstance(obj, dict) and isinstance(obj.get("result"), str):
                texte = obj["result"]
                break
        except ValueError:  # muet-ok : balayage des « { » candidats, un morceau non JSON est attendu, on essaie le suivant
            pass
        i = brut.find("{", i + 1)
    return re.sub(r"\n*\{\s*\"intent\".*\}\s*$", "", texte.strip(), flags=re.S).strip()


def _statut_brut(tid: str) -> dict:
    return sw._json_hub(sw._appel_hub("task", {"action": "status", "task_id": tid}))


def _deposer(p: Path, res: dict, executeur: str, motifs: list) -> None:
    consigne = (res.get("demande_synthese") or {}).get("consigne") or ""
    try:
        tid = sw._deposer_tache(executeur, "Synthèse swarm", consigne)
    except Exception as e:  # noqa: BLE001
        motifs.append("dépôt impossible (%s): %s" % (executeur, str(e)[:120]))
        res["secours_motifs"] = motifs
        _ecrire(p, res)
        return
    res["secours_depose"] = {"task_id": tid, "agent": executeur, "ts": time.time()}
    if motifs:
        res["secours_motifs"] = motifs
    _ecrire(p, res)


def _suivant(demande: dict, agent: str) -> str | None:
    liste = list(demande.get("executeurs") or sw.EXECUTEURS_SECOURS)
    if "ANTIGRAVITY" not in liste:
        liste.append("ANTIGRAVITY")
    i = liste.index(agent) if agent in liste else -1
    return liste[i + 1] if i + 1 < len(liste) else None


def _traiter(p: Path, d: Path) -> None:
    res = json.loads(p.read_text(encoding="utf-8"))
    demande = res.get("demande_synthese")
    if not demande or res.get("secours_integre"):
        return
    motifs = list(res.get("secours_motifs") or [])
    dep = res.get("secours_depose")
    if not dep:
        _deposer(p, res, (demande.get("executeurs") or [sw.EXECUTEURS_SECOURS[0]])[0], motifs)
        return
    if dep.get("abandon"):
        return
    tid, agent = dep["task_id"], dep["agent"]
    try:
        st = _statut_brut(tid)
    except Exception as e:  # noqa: BLE001
        st = {"status": "", "_illisible": str(e)[:120]}
    etat = str(st.get("status") or "")
    if etat in sw._ETATS_FINIS:
        try:
            texte = _texte_complet(tid)
        except Exception as e:  # noqa: BLE001
            texte = ""
            print("secours_lanceur: texte complet de %s illisible (%s)" % (tid, type(e).__name__))
        if not str(texte).strip():
            motif = "tâche %s terminée sans texte" % tid
        else:
            f = d / "workspace" / ("secours_texte_%s.txt" % tid)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(texte), encoding="utf-8")
            if sw._integrer_secours(str(p), tid, agent, texte=str(f)) == 0:
                res = json.loads(p.read_text(encoding="utf-8"))
                if st.get("cout_usd") is not None and res.get("secours_integre"):
                    res["secours_integre"]["cout_usd"] = st["cout_usd"]
                _ecrire(p, res)
                return
            motif = "intégration refusée (tâche %s)" % tid
    elif etat in sw._ETATS_ECHEC:
        motif = "tâche %s en échec (%s)" % (tid, etat)
    elif time.time() - float(dep.get("ts") or 0) >= DELAI_EXECUTEUR_S:
        motif = "délai de %d s dépassé (tâche %s, état %s)" % (DELAI_EXECUTEUR_S, tid, etat or "inconnu")
    else:
        return
    motifs.append("%s : %s" % (agent, motif))
    suivant = _suivant(demande, agent)
    if suivant is None:
        dep["abandon"] = True
        res["secours_depose"] = dep
        res["secours_motifs"] = motifs
        _ecrire(p, res)
        return
    _deposer(p, res, suivant, motifs)


def _etat(avant: dict, apres: dict) -> str:
    """Une ligne lisible : deposé / intégré / attente / motif."""
    if apres.get("secours_integre") and not avant.get("secours_integre"):
        return "intégré"
    nb = len(apres.get("secours_motifs") or [])
    if nb > len(avant.get("secours_motifs") or []):
        return "motif : %s" % (apres["secours_motifs"][-1],)
    if apres.get("secours_depose") != avant.get("secours_depose"):
        return "déposé (%s)" % ((apres.get("secours_depose") or {}).get("agent"),)
    if apres.get("secours_integre"):
        return "déjà intégré"
    if not apres.get("demande_synthese") and not apres.get("secours_depose"):
        return "ignoré (pas de demande)"
    return "attente"


_APPEL_GENERIQUE = sw._appel_hub  # client hub du swarm au chargement (jeton generique, ring 4)
_NOM_RESULTAT = re.compile(r"^cli_swarm_ptr_[^.]+\.json$")  # un seul suffixe : exclut `.avant_reparation.json`


def passer(dossier=None) -> int:
    """Un passage ; glob du seul dossier (non recursif), JSON de moins de 24 h. Rend le nombre examine.

    29/10 12 h 40 : appele DEPUIS le swarm, le passage deposait sous le jeton generique (GATE_DENIED ring 4) : l'identite
    n'etait installee que dans `__main__`. Desormais installee ici, le temps du passage, si le client hub du module est
    encore le client generique (un faux hub de test est laisse en place). Copies (`.avant_reparation.json`) ignorees."""
    d = Path(dossier) if dossier else _RACINE_DONNEES / "sandbox"
    installe = sw._appel_hub is _APPEL_GENERIQUE
    if installe:
        sw._appel_hub = globals()["_appel_identite"]
    try:
        return _passer(d)
    finally:
        if installe:
            sw._appel_hub = _APPEL_GENERIQUE


def _passer(d: Path) -> int:
    n = 0
    for p in sorted(d.glob("cli_swarm_ptr_*.json")):
        if not _NOM_RESULTAT.match(p.name):
            continue
        try:
            if time.time() - p.stat().st_mtime > FENETRE_S:
                continue
            avant = json.loads(p.read_text(encoding="utf-8"))
            _traiter(p, d)
            n += 1
            print("secours_lanceur: %s %s" % (p.name, _etat(avant, json.loads(p.read_text(encoding="utf-8")))))
        except Exception as e:  # noqa: BLE001
            print("secours_lanceur: %s ignoré (%s)" % (p.name, type(e).__name__))
    return n


if __name__ == "__main__":
    passer(sys.argv[1] if len(sys.argv) > 1 else None)  # identite SWARM_LANCEUR installee par passer()
