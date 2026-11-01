"""Veilleur du journal OpenCode : une panne fournisseur (quota, AI_RetryError) n'est ecrite QUE dans son journal,
OpenCode ne renvoie rien par ACP -> sans ce veilleur, SilenceACP 300 s. Logique OpenCode ici, pas dans le client ACP.

Livraison CLAUDE_HEADLESS 1e801f164 (NR 4d58d4c21), integree par governed_edit (GO owner 28/10).
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

__FORGE_COLOR__ = "systeme_immunitaire/veilleur du journal OpenCode (panne fournisseur muette en ACP)"

log = logging.getLogger(__name__)

ENV_JOURNAL = "LAFORGE_OPENCODE_LOG"
JOURNAL_DEFAUT = Path(r"%USERPROFILE%\.local\share\opencode\log\opencode.log")
LECTURE_MAX_OCTETS = 65536
INTERVALLE_S = 1.0

_RE_PANNE = re.compile(r"Free usage limit reached|AI_RetryError", re.I)
_RE_NIVEAU_ERREUR = re.compile(r"level=ERROR|^\s*ERROR\b")
_RE_TS = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z)?")
_RE_SESSION = re.compile(r"session(?:\.id|ID|Id)=(\S+)")
_RE_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+|(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+)", re.I)

_dit_une_fois: set[str] = set()


class QuotaJournalOpenCode(RuntimeError):
    """Panne fournisseur lue dans le journal OpenCode ; le message porte la ligne caviardee."""


def chemin_journal() -> Path:
    return Path(os.environ.get(ENV_JOURNAL) or JOURNAL_DEFAUT)


def caviarder(texte: str, max_len: int = 400) -> str:
    return _RE_SECRET.sub("[REDACTED]", texte)[:max_len]


def lire_fin(chemin, max_octets: int = LECTURE_MAX_OCTETS) -> list[str]:
    """Lignes de la FIN du fichier, au plus max_octets lus ; jamais le fichier entier. Illisible -> []."""
    try:
        with open(chemin, "rb") as f:
            f.seek(0, os.SEEK_END)
            taille = f.tell()
            debut = max(0, taille - max_octets)
            f.seek(debut)
            brut = f.read(max_octets)
    except OSError:
        return []
    lignes = brut.decode("utf-8", errors="replace").splitlines()
    if debut > 0 and lignes:
        lignes = lignes[1:]  # premiere ligne probablement tronquee
    return lignes


def _en_utc(dt: datetime) -> datetime:
    """Naif = heure LOCALE (astimezone l'interprete ainsi) ; conscient = converti. Revue 28/10 : le vrai journal
    est en UTC (« ...Z »), l'appelant passe datetime.now() local -- comparer sans fuseau ratait toute panne reelle."""
    return dt.astimezone(timezone.utc)


def _une_fois(cle: str, msg: str) -> None:
    if cle not in _dit_une_fois:
        _dit_une_fois.add(cle)
        log.debug(msg)


def chercher_panne(chemin, depuis: datetime, session_id: str | None, quota_re) -> str | None:
    """Premiere ligne level=ERROR de panne fournisseur dont le timestamp est >= depuis (et session compatible)."""
    lignes = lire_fin(chemin)
    if not lignes:
        _une_fois(str(chemin), f"journal OpenCode absent/illisible/vide ({chemin}) : veille de silence seule")
        return None
    depuis = _en_utc(depuis).replace(microsecond=0)
    for ligne in lignes:
        if not _RE_NIVEAU_ERREUR.search(ligne):
            continue
        if not (_RE_PANNE.search(ligne) or (quota_re is not None and quota_re.search(ligne))):
            continue
        m = _RE_TS.search(ligne)
        if not m:
            continue  # sans horodatage on ne peut pas prouver qu'elle est posterieure
        try:
            ts = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:  # muet-ok : horodatage illisible = posteriorite non prouvable, ligne ecartee (UNKNOWN != OUI)
            continue
        ts = ts.replace(tzinfo=timezone.utc) if m.group(3) else _en_utc(ts)
        if ts < depuis:
            continue
        ms = _RE_SESSION.search(ligne)
        if ms and session_id and str(session_id).startswith("ses_") and ms.group(1).strip('"') != session_id:
            continue
        return caviarder(ligne.strip())
    return None


def prompt_avec_veilleur(client, sid, text, timeout, chemin=None, quota_re=None, intervalle_s: float = INTERVALLE_S):
    """client.prompt() dans un fil ; le fil appelant lit la fin du journal. Panne posterieure au debut -> leve
    QuotaJournalOpenCode (le client est ferme ensuite par l'appelant, ce qui libere le fil du prompt)."""
    chemin = Path(chemin) if chemin else chemin_journal()
    debut = datetime.now(timezone.utc)
    sortie: dict = {}

    def _prompt():
        try:
            sortie["res"] = client.prompt(sid, text, timeout=timeout)
        except BaseException as exc:  # noqa: BLE001 -- re-levee telle quelle dans le fil appelant
            sortie["exc"] = exc

    fil = threading.Thread(target=_prompt, name="opencode-prompt", daemon=True)
    fil.start()
    while True:
        fil.join(intervalle_s)
        if not fil.is_alive():
            break
        ligne = chercher_panne(chemin, debut, sid, quota_re)
        if ligne:
            raise QuotaJournalOpenCode(f"quota exceeded (journal OpenCode) : {ligne}")
    if "exc" in sortie:
        raise sortie["exc"]
    return sortie.get("res")
