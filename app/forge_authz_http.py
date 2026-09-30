"""forge_authz_http.py — ADAPTATEUR UNIQUE : requete HTTP -> decision d'autorisation attribuee.

Organe : immunitaire / garde HTTP (adaptateur vers decision d'autorisation, AUTH-3).

Chantier d'authentification (contrat du 2026-09-24, SSoT auth_contrat_de_fermeture_2026-09-24).
Le hub portait une quinzaine de facons de dire « autorise » ; ce module est le point ou une
requete HTTP devient une decision -- le hub ne fait que l'appeler a l'enregistrement de ses
routes. Premier usage : les MUTATIONS appelees depuis une page (interface du hub ou du
portail), qui n'ont pas de jeton de service et ne doivent JAMAIS en recevoir un dans le HTML.

Regle pour une mutation d'interface :
  - un jeton d'ADMINISTRATION valide (verifie PAR LE HUB, passe en argument) -> accepte ;
  - sinon une SESSION UI valide (cookie `lf_session` du portail :7400 : signature, audience,
    revocation de jti -- la verification EXISTANTE du portail, reutilisee telle quelle)
    ET une ORIGINE locale attendue (anti-CSRF : les cookies ne dependent pas du port) ;
  - sinon REFUS. Origine absente = refus (fail-closed, AUTH-4).
Le principal rendu vient de la preuve (sujet de la session, ou jeton admin), JAMAIS d'un
champ du corps de la requete (AUTH-6/7 : une attribution ne se declare pas).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

__FORGE_COLOR__ = "immunitaire/garde-http"

ORIGINES_LOCALES = frozenset({
    "http://127.0.0.1:8766", "http://localhost:8766",
    "http://127.0.0.1:7400", "http://localhost:7400",
})
_JOURNAL = Path(__file__).resolve().parents[1] / "sandbox" / "authz_http.jsonl"


def _journaliser(trace: Dict[str, Any]) -> None:
    try:
        _JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        if _JOURNAL.exists() and _JOURNAL.stat().st_size > 5_000_000:
            _JOURNAL.replace(_JOURNAL.with_suffix(".jsonl.1"))
        with _JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001  # muet-ok : un journal ne casse jamais une decision
        pass


def _registre_revocation() -> Path:
    """Le registre PERSISTE des deconnexions du portail (meme defaut que app/web_hub/app.py)."""
    import os

    return Path(os.environ.get("LAFORGE_JTI_DB") or (Path(__file__).resolve().parents[1] / "logs" / "hub_state.db"))


def jti_revoque_persiste(jti: str) -> Optional[bool]:
    """True/False lu dans le registre persiste ; None = ILLISIBLE (jamais lu comme « non revoque »).

    Le cache de revocation du portail est EN MEMOIRE de son processus ; le hub, autre processus,
    ne voit une deconnexion que par ce registre -- sans cette lecture, une session fermee sur
    :7400 resterait valable ici jusqu'a son expiration.
    """
    import sqlite3

    chemin = _registre_revocation()
    if not chemin.exists():
        return None
    try:
        cx = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=1.0)
        try:
            ligne = cx.execute("SELECT 1 FROM jwt_revocations WHERE jti = ? LIMIT 1", (jti,)).fetchone()
        finally:
            cx.close()
        return ligne is not None
    except sqlite3.Error:
        return None


def session_ui(headers, cookies) -> Optional[dict]:
    """Charge utile de la session UI du portail, ou None (absente, invalide, revoquee, illisible).

    COOKIE SEUL : une page ne porte pas d'en-tete Authorization, et un porteur de service
    se juge par le hub (`admin_ok`), pas ici.
    """
    try:
        from app.web_hub.auth import AuthConfig, extract_token, verify_token

        jeton = extract_token({}, cookies)
        if not jeton:
            return None
        charge = verify_token(AuthConfig.from_env(), jeton)
    except Exception:  # noqa: BLE001 -- verificateur indisponible : pas de session, jamais une ouverture
        return None
    if not charge:
        return None
    if jti_revoque_persiste(charge.get("jti") or "") is not False:
        return None   # revoquee OU registre illisible : UNKNOWN n'est pas NO
    return charge


def origine_locale(headers) -> bool:
    """Vrai si Origin (a defaut Referer) designe une page locale attendue. Absent = faux."""
    origine = (headers.get("origin") or "").rstrip("/")
    if origine:
        return origine in ORIGINES_LOCALES
    referer = headers.get("referer") or ""
    return any(referer.startswith(o + "/") for o in ORIGINES_LOCALES)


def autoriser_mutation_ui(request, capacite: str, admin_ok: bool = False) -> Dict[str, Any]:
    """-> {autorise, principal, via, raison}. Journalise chaque decision (sandbox/authz_http.jsonl)."""
    chemin = request.scope.get("path", "?")
    if admin_ok:
        d = {"autorise": True, "principal": "jeton_admin", "via": "jeton_admin", "raison": "jeton admin valide"}
    else:
        sess = session_ui(request.headers, request.cookies)
        if not sess:
            d = {"autorise": False, "principal": None, "via": "aucun",
                 "raison": "ni jeton d'administration ni session UI valide (se connecter au portail :7400)"}
        elif not origine_locale(request.headers):
            d = {"autorise": False, "principal": None, "via": "session_ui",
                 "raison": "origine absente ou non locale : mutation refusee (anti-CSRF)"}
        else:
            d = {"autorise": True, "principal": "ui:%s" % sess.get("sub"), "via": "session_ui",
                 "raison": "session UI valide, origine locale"}
    _journaliser({"ts": time.time(), "chemin": chemin, "capacite": capacite, **d})
    return d
