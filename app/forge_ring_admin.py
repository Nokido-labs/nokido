"""forge_ring_admin.py — GUI réattribution ring LIVE (#10).

Lit/écrit le registre `config/agent_identities.json` (#10a : identité×canal×ring×
machine). Le hub le recharge sur mtime → changement de ring SANS restart. L'écriture
est GATED **ring-0** (réattribuer un ring = accorder un privilège) + AUDITÉE. Le rendu
HTML + l'endpoint sont loopback-only (gardé côté hub). Module séparé = anti-dup +
garde les edits du hub critiques minimes.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/rbac : reattribution des rings (GUI)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_STORE = ROOT / "config" / "agent_identities.json"
_AUDIT = ROOT / "logs" / "ring_admin_audit.log"


def load() -> dict:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "agents": {}}


def _audit(msg: str) -> None:
    try:
        _AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_ring_admin.py', 35, exc_info=True)


def set_ring(agent: str, new_ring, caller_ring: int, caller_agent: str = "") -> dict:
    """Réattribue le ring d'un agent dans le store live. GATED ring-0. Audité.
    Le hub recharge le store sur mtime -> effet SANS restart."""
    agent = (agent or "").upper().strip()
    if caller_ring != 0:
        _audit(f"DENY set_ring by {caller_agent}(ring={caller_ring}) {agent}->ring={new_ring} (ring-0 requis)")
        return {"ok": False, "error": "ring-0 requis pour réattribuer un ring"}
    try:
        new_ring = int(new_ring)
    except Exception:
        return {"ok": False, "error": "ring invalide (entier attendu)"}
    if new_ring < 0 or new_ring > 5:
        return {"ok": False, "error": "ring hors borne [0..5]"}
    data = load()
    agents = data.setdefault("agents", {})
    if agent not in agents or not isinstance(agents[agent], dict):
        return {"ok": False, "error": f"agent inconnu: {agent}"}
    old = agents[agent].get("ring")
    agents[agent]["ring"] = new_ring
    try:
        _STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"écriture store: {e}"}
    _audit(f"SET by {caller_agent}(ring=0) {agent} ring {old} -> {new_ring}")
    return {"ok": True, "agent": agent, "old": old, "new": new_ring}


def inscrire_client_oauth(identite: str, ring, note: str) -> dict:
    """3/11 (decision owner « ring choisi au tray + inscrit au registre ») : inscrit/met a jour le ring d'un CLIENT
    OAuth, decide par l'owner a la fenetre de consentement du tray (forge_ordres_bureau.decider ne l'admet que du
    consommateur prouve). Appele par le decideur du hub, jamais par une route.

    Bornes, et pourquoi elles sont etroites (set_ring exige le ring 0 pour TOUT agent) : identite OAUTH_* seulement
    -- aucun organe ni agent existant ne se reecrit par ici ; ring 1..3, jamais 0 ; motif dans l'entree + audit ;
    ecriture ATOMIQUE (le hub relit le store sur mtime et ne doit jamais lire un fichier tronque).
    NR : tests/nr/test_ring_client_oauth_au_registre_nr.py
    """
    ident = (identite or "").upper().strip()
    if not ident.startswith("OAUTH_") or len(ident) <= len("OAUTH_"):
        return {"ok": False, "error": "identite hors espace OAUTH_ : %r" % ident}
    try:
        ring = int(ring)
    except (TypeError, ValueError):
        return {"ok": False, "error": "ring invalide (entier attendu)"}
    if ring < 1 or ring > 3:
        return {"ok": False, "error": "ring hors borne [1..3] pour un client OAuth"}
    data = load()
    agents = data.setdefault("agents", {})
    ancien = agents.get(ident, {}).get("ring") if isinstance(agents.get(ident), dict) else None
    entree = dict(agents.get(ident) or {}) if isinstance(agents.get(ident), dict) else {}
    entree.update({"ring": ring, "kind": "oauth_client", "actor": ident, "surface": "interactive", "mailbox": ident,
                   "channel": "HTTP_DIRECT", "transport": "http", "machine": "local",
                   "_note": str(note or "")[:400]})
    agents[ident] = entree
    tmp = _STORE.with_name("%s.%d.tmp" % (_STORE.name, os.getpid()))
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _STORE)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "ecriture store: %s" % type(e).__name__}
    _audit("OAUTH-CONSENTEMENT %s ring %s -> %s (%s)" % (ident, ancien, ring, str(note or "")[:120]))
    return {"ok": True, "agent": ident, "old": ancien, "new": ring}


def retirer_client_oauth(identite: str, motif: str = "") -> dict:
    """3/11 : retire l'entree d'un CLIENT OAuth du registre (revocation decidee par l'owner au tray). OAUTH_* seulement
    -- aucun organe ni agent ne se retire par ici ; ecriture atomique ; audit. Sans entree, un jeton restant retombe
    au ring 3 (verification max(registre, jeton)). NR : tests/nr/test_oauth_revoquer_client_nr.py"""
    ident = (identite or "").upper().strip()
    if not ident.startswith("OAUTH_") or len(ident) <= len("OAUTH_"):
        return {"ok": False, "error": "identite hors espace OAUTH_ : %r" % ident}
    data = load()
    agents = data.setdefault("agents", {})
    if ident not in agents:
        return {"ok": True, "agent": ident, "retire": False, "note": "absente du registre (rien a retirer)"}
    ancien = agents.pop(ident)
    tmp = _STORE.with_name("%s.%d.tmp" % (_STORE.name, os.getpid()))
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _STORE)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "ecriture store: %s" % type(e).__name__}
    _audit("OAUTH-REVOCATION %s retire (ring %s) %s" % (ident, (ancien or {}).get("ring"), str(motif or "")[:120]))
    return {"ok": True, "agent": ident, "retire": True}


def render_page(caller_ring: int = 99) -> str:
    data = load()
    agents = data.get("agents", {})
    can_edit = caller_ring == 0
    rows = []
    for name, m in sorted(agents.items()):
        if not isinstance(m, dict):
            continue
        r = m.get("ring")
        ch = m.get("channel", "-")
        tr = m.get("transport", "-")
        mc = m.get("machine", "-")
        if can_edit:
            opts = "".join(
                f'<option value="{i}"{" selected" if i == r else ""}>{i}</option>' for i in range(6)
            )
            ctl = (f'<select data-agent="{name}">{opts}</select> '
                   f"<button onclick=\"setRing('{name}',this)\">set</button>")
        else:
            ctl = f"<b>{r}</b>"
        rows.append(f"<tr><td>{name}</td><td>{ch}</td><td>{tr}</td><td>{mc}</td><td>{ctl}</td></tr>")
    note = "" if can_edit else '<p style="color:#e74c3c">Lecture seule — réattribution réservée ring-0.</p>'
    return (
        "<!doctype html><html><head><meta charset=utf-8><title>Nokido — Rings</title>"
        # Sans icone declaree, le navigateur demande /favicon.ico -> 404 (campagne UI 25/09).
        "<link rel='icon' type='image/svg+xml' href='/static/nokido-favicon.svg'>"
        "<style>body{font-family:Consolas,monospace;background:#0d1117;color:#c9d1d9;padding:20px}"
        "table{border-collapse:collapse}td,th{border:1px solid #30363d;padding:6px 10px}"
        "th{background:#161b22}select,button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:3px}"
        "code{color:#a7c7e7}#msg{margin:10px 0;color:#58a6ff;min-height:1em}</style></head><body>"
        "<h2>Nokido — Réattribution ring (live, sans restart)</h2>"
        "<p>Édite le ring → écrit <code>config/agent_identities.json</code> → le hub recharge sur mtime. "
        "ring 0 = plus de droits.</p>"
        f"{note}<div id=msg></div>"
        "<table><tr><th>agent</th><th>canal</th><th>transport</th><th>machine</th><th>ring</th></tr>"
        f"{''.join(rows)}</table>"
        "<script>async function setRing(a,btn){const sel=btn.previousElementSibling;"
        "const r=await fetch('/api/rings/set',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({agent:a,ring:sel.value})});const j=await r.json();"
        "document.getElementById('msg').textContent=j.ok?('OK '+j.agent+': ring '+j.old+' -> '+j.new):('ERR: '+j.error);}"
        "</script></body></html>"
    )
