#!/usr/bin/env python3
"""hook_stop_attente_passive.py -- Hook Stop : un tour ne se termine pas sur une ATTENTE PASSIVE.

POURQUOI UN HOOK ET PAS UNE REGLE. Consigne owner donnee TROIS fois (09/10, 13/10, 14/10) : « continue sur d'autres
taches en attente, arrete de perdre du temps d'attente » -- la fiche memoire existait, et l'agent a quand meme rendu
la main deux fois de suite sur « le parcours tourne toujours, je reprends des son verdict ». Face a une recidive, la
question n'est pas « quelle regle ecrire » mais « qu'est-ce qui peut m'arreter » : ce hook.

CE QU'IL FAIT. Il lit le DERNIER message de l'agent (transcript_path). S'il annonce une attente (un job, une CI, un
parcours qui tourne, un verdict attendu) SANS demander un geste ou une decision a l'owner, il BLOQUE la fin du tour
une fois, avec la consigne : enchainer une autre tache du backlog. `stop_hook_active` vrai = il a deja relance ce
tour : il laisse passer (jamais de boucle).

CE QU'IL NE FAIT PAS. Il n'empeche jamais de rendre la main pour une raison legitime : geste owner, decision qui lui
revient, question posee -- le message le dit alors, et le hook se tait. Un faux positif coute UN segment de tour en
plus ; chaque declenchement est journalise (sandbox/hooks/stop_attente_passive.jsonl) pour mesurer ce bruit et
corriger aussitot un motif qui crie a faux.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "sandbox" / "hooks" / "stop_attente_passive.jsonl"

# Formes RELEVEES dans les fins de tour fautives (14/10) et leurs voisines directes.
_ATTENTE = re.compile(
    r"(\b(tourne|tournent)\s+(encore|toujours)\b"
    r"|\bje\s+reprends\s+d[eè]s\s+(son|le|la|leur|qu)"
    r"|\ben\s+attendant\s+(le|la|son|leur|que)\b"
    r"|\bj'attends\b"
    r"|\bje\s+serai\s+(pr[eé]venu|r[eé]veill[eé])"
    r"|\bd[eè]s\s+que\s+(la|le)\s+(mesure|job|ci|run|parcours|verdict)\b)",
    re.IGNORECASE)

# Rendre la main est LEGITIME quand l'owner a quelque chose a faire ou a trancher : le message le dit.
_RENDU_LEGITIME = re.compile(
    r"(\bil\s+te\s+reste\b|\bte\s+revient\b|\bton\s+accord\b|\bta\s+d[eé]cision\b|\b[aà]\s+toi\s+de\b"
    r"|\bgeste\s+owner\b|\bj'ai\s+besoin\s+de\s+toi\b|\bje\s+te\s+(soumets|demande)\b|\?\s*$)",
    re.IGNORECASE | re.MULTILINE)

CONSIGNE = ("Fin de tour sur une attente passive (« %s »). Consigne owner permanente : pendant un job, "
            "une CI ou un parcours, enchainer une autre tache du backlog -- le Monitor reveillera au verdict. "
            "Ne rendre la main que pour un geste owner ou irreversible, une decision qui lui revient, ou un backlog "
            "vide, et alors lister ce qui reste.")


def decider(texte: str, deja_relance: bool) -> str | None:
    """Rend la raison du blocage, ou None pour laisser finir le tour."""
    if deja_relance or not texte:
        return None
    m = _ATTENTE.search(texte)
    if not m or _RENDU_LEGITIME.search(texte):
        return None
    return CONSIGNE % m.group(0).strip()


def dernier_message(transcript: Path) -> str:
    """Texte du dernier message de l'agent (ses blocs texte apres la derniere entree de l'owner)."""
    textes: list = []
    for ligne in transcript.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
        try:
            entree = json.loads(ligne)
        except ValueError:  # muet-ok : derniere ligne du transcript en cours d'ecriture, relue au prochain arret
            continue
        role = (entree.get("message") or {}).get("role") or entree.get("type")
        contenu = (entree.get("message") or {}).get("content")
        parole = isinstance(contenu, str) or (isinstance(contenu, list) and any(
            isinstance(b, dict) and b.get("type") == "text" for b in contenu) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in contenu))
        if role == "user" and parole:
            textes = []                       # nouvelle parole de l'owner (chaine ou blocs texte) : on repart de zero
        elif role == "assistant" and isinstance(contenu, list):
            textes += [b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(t for t in textes if t)[-4000:]


def main() -> int:
    try:
        charge = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0                              # entree illisible : on ne bloque pas sur une lecture ratee
    chemin = charge.get("transcript_path")
    if not chemin or not Path(chemin).is_file():
        return 0
    raison = decider(dernier_message(Path(chemin)), bool(charge.get("stop_hook_active")))
    if raison:
        try:
            JOURNAL.parent.mkdir(parents=True, exist_ok=True)
            with JOURNAL.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "session": charge.get("session_id"), "raison": raison},
                                    ensure_ascii=False) + "\n")
        except OSError as exc:                # la mesure du bruit ne doit jamais empecher le rappel
            print("[stop_attente_passive] journal non ecrit (%s)" % type(exc).__name__, file=sys.stderr)
        # ASCII pur : l'encodage du tube varie (cp1252 sous Windows, UTF-8 cote lecteur) -- « » arrivaient en U+FFFD
        print(json.dumps({"decision": "block", "reason": raison}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
