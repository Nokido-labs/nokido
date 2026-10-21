"""Exports officiels de conversations (Claude claude.ai, ChatGPT, Grok) : lecture AU FIL DE L'EAU, un fragment
par MESSAGE (identite stable d'un export a l'autre), en-tete titre + date, insertion par lots.

Pourquoi un fragment par message : les fenetres de deux tours indexees `.../<idx>` changent de texte quand un fil
grandit -> quasi-doublon de la derniere fenetre a chaque nouvel export. Ici l'identite d'un fragment depend de
(plateforme, fil, role, date, texte) : un export plus recent re-produit EXACTEMENT les memes fragments pour les
messages deja vus, et INSERT OR IGNORE les ignore. Un message long est DECOUPE, jamais tronque.
Google Takeout (Gemini) : format a lire sur un VRAI export avant d'ecrire l'analyseur (jamais devine).
"""
from __future__ import annotations

__FORGE_COLOR__ = 'digestif/ingestion : lecture au fil de l\'eau des exports officiels de conversations, un fragment par message'

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Iterator

CHUNK_MAX = 2000
CHUNK_MIN = 40
LOT = 2000
_BOM = chr(0xFEFF)   # marque d'ordre d'octets en tete de fichier : ecrite par son code, jamais en clair

# ── lecture au fil de l'eau ───────────────────────────────────────────────────
def iter_tableau_json(chemin: Path, cle: str | None = None, bloc: int = 1 << 20) -> Iterator[object]:
    """Elements d'un tableau JSON, un par un (stdlib). `cle` : tableau sous `{"<cle>": [...]}` en tete d'objet."""
    dec = json.JSONDecoder()
    with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
        tampon, i = "", 0

        def remplir():
            nonlocal tampon, i
            plus = fh.read(bloc)
            tampon, i = tampon[i:] + plus, 0
            return bool(plus)

        def sauter(car=" \t\r\n" + _BOM):
            nonlocal i
            while True:
                while i < len(tampon) and tampon[i] in car:
                    i += 1
                if i < len(tampon) or not remplir():
                    return

        sauter()
        if cle is not None:                           # {"conversations": [ ...
            motif = re.compile(r'\{\s*"%s"\s*:\s*' % re.escape(cle))
            while not motif.match(tampon, i) and len(tampon) - i < 4096 and remplir():
                pass
            m = motif.match(tampon, i)
            if not m:
                raise ValueError("%s : pas d'enveloppe {\"%s\": [...]} en tete" % (chemin.name, cle))
            i = m.end()
        if i >= len(tampon) or tampon[i] != "[":
            raise ValueError("%s : pas un tableau JSON a l'endroit attendu" % chemin.name)
        i += 1
        while True:
            sauter(" \t\r\n,")
            if i >= len(tampon):
                raise ValueError("%s : tableau non ferme (fichier tronque ?)" % chemin.name)
            if tampon[i] == "]":
                return
            while True:
                try:
                    obj, fin = dec.raw_decode(tampon, i)
                    break
                except json.JSONDecodeError:
                    if not remplir():
                        raise
            yield obj
            i = fin
            if i > bloc:
                tampon, i = tampon[i:], 0

def _tete(chemin: Path, n: int = 8192) -> str:
    with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read(n).lstrip(_BOM + " \t\r\n")

def conversations(chemin: Path) -> Iterator[object]:
    """Toutes les conversations d'un export, quelle que soit l'enveloppe (tableau, ou objet Grok)."""
    tete = _tete(chemin)
    if tete.startswith("["):
        yield from iter_tableau_json(chemin)
    elif re.match(r'\{\s*"conversations"\s*:', tete):
        yield from iter_tableau_json(chemin, cle="conversations")
    else:                                             # une conversation seule : petite par nature
        yield json.loads(Path(chemin).read_text(encoding="utf-8", errors="replace"))

# ── formes ────────────────────────────────────────────────────────────────────
def plateforme(conv: object) -> str:
    """Par la FORME, jamais par le nom du fichier."""
    if not isinstance(conv, dict):
        return "INCONNU"
    if "chat_messages" in conv:
        return "claude"
    if "mapping" in conv:
        return "chatgpt"
    if "responses" in conv or ("conversation" in conv and "responses" in conv) or "messages" in conv:
        return "grok"
    return "INCONNU"

def _epoch(v) -> float | None:
    """ISO, nombre (ms si > 1e12), ou Mongo {"$date": {"$numberLong": ms}} -> secondes ; None si illisible."""
    if isinstance(v, dict):
        d = v.get("$date")
        v = d.get("$numberLong") if isinstance(d, dict) else d
    if v is None or v == "":
        return None
    if isinstance(v, str):
        try:
            return _dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                v = float(v)
            except ValueError:
                return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 1000.0 if x > 1e12 else x

# ── messages normalises : (role, texte, epoch|None) ──────────────────────────
def messages_claude(conv: dict) -> tuple[str, str, list]:
    msgs = []
    for m in conv.get("chat_messages") or []:
        role = str(m.get("sender", "")).lower()
        role = "humain" if role == "human" else role or "inconnu"
        blocs = m.get("content")
        texte = "\n".join(b.get("text", "") for b in blocs if isinstance(b, dict) and b.get("type") == "text") \
            if isinstance(blocs, list) and blocs else str(m.get("text") or "")
        msgs.append((role, texte.strip(), _epoch(m.get("created_at"))))
    return str(conv.get("uuid") or "inconnu"), str(conv.get("name") or ""), msgs

def messages_chatgpt(conv: dict) -> tuple[str, str, list]:
    """Fil AFFICHE : de `current_node` a la racine (les branches abandonnees ne sont pas melangees au fil)."""
    mapping = conv.get("mapping") or {}
    chaine, n, vus = [], conv.get("current_node"), set()
    while n and n in mapping and n not in vus:
        vus.add(n)
        chaine.append(mapping[n])
        n = mapping[n].get("parent")
    msgs = []
    for nd in reversed(chaine):
        m = nd.get("message") or {}
        role = (m.get("author") or {}).get("role")
        c = m.get("content") or {}
        if role not in ("user", "assistant") or c.get("content_type") != "text":
            continue
        texte = "\n".join(p for p in (c.get("parts") or []) if isinstance(p, str)).strip()
        msgs.append(("humain" if role == "user" else "assistant", texte, _epoch(m.get("create_time"))))
    return str(conv.get("conversation_id") or conv.get("id") or "inconnu"), str(conv.get("title") or ""), msgs

def messages_grok(conv: dict) -> tuple[str, str, list]:
    entete = conv.get("conversation") if isinstance(conv.get("conversation"), dict) else conv
    msgs = []
    for r in conv.get("responses") or []:
        r = r.get("response", r) if isinstance(r, dict) else {}
        role = str(r.get("sender") or "inconnu").lower()
        msgs.append(("humain" if role in ("human", "user") else role, str(r.get("message") or "").strip(),
                     _epoch(r.get("create_time"))))
    for m in conv.get("messages") or []:
        role = str(m.get("role") or m.get("sender") or "inconnu").lower()
        msgs.append(("humain" if role in ("human", "user") else role,
                     str(m.get("content") or m.get("text") or "").strip(),
                     _epoch(m.get("created_at") or m.get("timestamp") or m.get("createdAt"))))
    return str(entete.get("id") or entete.get("conversationId") or "inconnu"), \
        str(entete.get("title") or entete.get("name") or ""), msgs

_LECTEURS = {"claude": messages_claude, "chatgpt": messages_chatgpt, "grok": messages_grok}

# ── fragments ─────────────────────────────────────────────────────────────────
def _morceaux(texte: str, taille: int) -> list:
    from nokido_agent.app.forge_utils import decouper_sans_perte  # noqa: PLC0415 -- corps partage (cliquet clones, 18/10)

    return decouper_sans_perte(texte, taille)

def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()

def fragments(plat: str, conv: dict) -> Iterator[tuple[str, str]]:
    """(source, texte) par message ; source = conv_<plat>/<fil16>/<id_message12>[.k] -- stable d'un export a
    l'autre ; en-tete « [role] titre — date » pour situer le souvenir."""
    fil, titre, msgs = _LECTEURS[plat](conv)
    fil16 = fil[:16]
    for role, texte, ts in msgs:
        if len(texte) < CHUNK_MIN:
            continue
        ident = hashlib.sha256("|".join([plat, fil, role, str(int(ts or 0)), _norm(texte)]).encode()).hexdigest()[:12]
        date = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d") if ts else "date ?"
        entete = "[%s] %s — %s\n" % (role, titre[:80] or "(sans titre)", date)
        parts = _morceaux(texte, CHUNK_MAX - len(entete))
        for k, p in enumerate(parts):
            yield ("conv_%s/%s/%s%s" % (plat, fil16, ident, ".%d" % k if len(parts) > 1 else ""), entete + p)

def indexer_export(chemin: Path, inserer) -> dict:
    """Insertion par lots ; rapporte ce qui est ecarte (forme inconnue)."""
    lot, compte = [], {"claude": 0, "chatgpt": 0, "grok": 0, "INCONNU": 0, "fragments": 0, "inseres": 0}
    for conv in conversations(chemin):
        plat = plateforme(conv)
        compte[plat] = compte.get(plat, 0) + 1
        if plat == "INCONNU":
            continue
        for frag in fragments(plat, conv):
            lot.append(frag)
            compte["fragments"] += 1
            if len(lot) >= LOT:
                compte["inseres"] += inserer(lot)
                lot = []
    if lot:
        compte["inseres"] += inserer(lot)
    return compte
