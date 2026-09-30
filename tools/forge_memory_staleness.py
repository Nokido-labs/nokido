#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_memory_staleness.py — une memoire est-elle encore VRAIE ?

`forge_memory_forensics` dit OU vit une memoire (chaude, froide, orpheline,
perdue). Il ne dit RIEN de sa veracite : une memoire parfaitement indexee peut
affirmer depuis dix jours qu'un service est UP. Ce module repond a l'autre
question — cette memoire est-elle encore vraie AUJOURD'HUI ? — en confrontant
son CONTENU au reel, jamais en devinant.

Trois axes, chacun adosse a une mesure, zero cloud, zero quota :

  1. CHEMINS       les fichiers cites existent-ils encore ? Delegue a
                   `forge_memory_compactor.audit`, qui distingue deja renomme /
                   deplace en `_attic` / introuvable. Rien n'est redecoupe ici.
  2. ETAT          les ports affirmes repondent-ils ? Sonde a TROIS etats, jamais
                   deux : une sonde courte sur un backend lent fabrique des faux
                   morts (mesure 2026-08-11 : 21 des 24 « non-OK » d'un audit
                   etaient des artefacts de sonde). INDETERMINE est un verdict
                   legitime, pas un echec de mesure.
  3. RECOUVREMENT  une memoire PLUS RECENTE parle-t-elle du meme sujet ? La rarete
                   des termes est MESUREE sur ce corpus (document frequency), pas
                   supposee ; le vocabulaire banni vient de `forge_intent_verifier`,
                   dont le seuil de recouvrement (2 termes) s'est revele inadapte
                   ici — il marquait 341 memoires sur 593. Seuil retenu : 4 termes
                   partages ET un quart du vocabulaire rare de la memoire couverte.

Le recouvrement ne rend pas une memoire suspecte, il la rend REDONDANTE : il porte
son propre verdict (`RECOUVERTE`) pour que `A_VERIFIER` reste une liste d'actions
et non un inventaire. Mesure a la livraison : 35 A_VERIFIER, 13 RECOUVERTE,
545 FRAIS sur 593, en 3 s.

Le verdict ne dit JAMAIS « fausse ». Il dit `A_VERIFIER` et NOMME son motif : une
confrontation d'etat prouve un desaccord, pas une erreur — le monde a pu bouger
depuis, et c'est precisement l'information utile. LECTURE SEULE par defaut ;
`--marquer` prefixe `[A VERIFIER]` a la description du frontmatter.

    LAFORGE_PYTHON tools/forge_memory_staleness.py --json
    LAFORGE_PYTHON tools/forge_memory_staleness.py --marquer
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _sub in ("tools", "app"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # resolution robuste du dossier memoire (HOME ment sous compte de service)
    from nokido_agent.tools.forge_memory_ledger import DIR as _DEFAULT_DIR
except Exception:  # pragma: no cover - filet
    _DEFAULT_DIR = Path("%USERPROFILE%/.claude/projects/C--Users-user-Script-python-IA/memory")

_INDEX = {"MEMORY.md", "MEMORY_ARCHIVE.md", "MEMORY.md.bak"}
_RE_PORT = re.compile(r":(\d{4,5})\b")
_RE_ETAT_POS = re.compile(
    r"\b(UP|OK|actif|active|tourne|ecoute|joignable|repare|reparee|en service|repond)\b", re.I)
_RE_ETAT_NEG = re.compile(
    r"\b(DOWN|MORT|MORTE|KO|inactif|inactive|injoignable|hors service|ferme|fermee|"
    r"refuse|absent|absente)\b", re.I)
_RE_DATE_NOM = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_RE_TOK_LOCAL = re.compile(r"[a-z_][a-z0-9_]{4,}")
_DF_MAX = 3          # un terme porte par plus de 3 memoires n'est pas discriminant
_INTER_MIN = 4       # termes rares partages exiges pour parler de recouvrement
_INTER_RATIO = 0.25  # ... et part minimale du vocabulaire rare de la memoire couverte
_PORTS_CONNUS = {8766, 8765, 11434, 9200, 7500, 3210, 7777, 8080, 6333}
_CACHE_PORT: dict = {}

# Racine interrogee par l'axe d'ancrage. Alias de ROOT et non seconde constante :
# deux racines qui divergent, c'est un ancrage qui verifie le mauvais depot.
_RACINE = ROOT


def _sonde(port: int, timeout: float = 5.0) -> str:
    """OUVERT / FERME / INDETERMINE. Le troisieme etat n'est pas un aveu, c'est la mesure."""
    if port in _CACHE_PORT:
        return _CACHE_PORT[port]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        v = "OUVERT"
    except ConnectionRefusedError:
        v = "FERME"          # personne n'ecoute : refus explicite du noyau
    except OSError:
        v = "INDETERMINE"    # timeout, reset, filtrage : on ne SAIT pas
    finally:
        s.close()
    _CACHE_PORT[port] = v
    return v


def _date_memoire(txt: str, p: Path) -> float:
    """Date de la CONNAISSANCE, pas du fichier.

    `st_mtime` date la derniere resynchronisation du dossier : sur ce corpus il
    est quasi uniforme et RECENT, ce qui inverse la chronologie — une memoire du
    03/06 apparaissait alors « recouverte » par une du 01/06. On lit donc, dans
    l'ordre : le `modified:` du frontmatter, puis la date portee par le nom de
    fichier, et seulement en dernier recours le mtime.
    """
    m = re.search(r"^\s*modified:\s*(\S+)", txt, re.M)
    if m:
        try:
            return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass  # muet-ok : frontmatter mal forme -> on retombe sur la date du nom
    d = _RE_DATE_NOM.search(p.name)
    if d:
        try:
            return datetime(int(d.group(1)), int(d.group(2)), int(d.group(3))).timestamp()
        except ValueError:
            pass  # muet-ok : date impossible dans le nom -> repli sur le mtime
    return p.stat().st_mtime


def _age_jours(txt: str, p: Path) -> float:
    return max(0.0, (time.time() - _date_memoire(txt, p)) / 86400.0)


def _confrontation_ports(txt: str, sonder: bool) -> tuple:
    """Confronte ce que la memoire AFFIRME, ligne par ligne, a la mesure.

    Un port simplement CITE n'affirme rien (« l'incident touchait :8080 ») : le
    confronter fabriquerait une alerte par mention.

    Seul le sens POSITIF est confrontable. Mesure 2026-08-16 : le sens negatif
    produisait « :8766 affirme ferme — mesure OUVERT » sur toutes les memoires
    d'incident, alors qu'elles RACONTENT un port mort au passe. Une memoire est
    un recit date, pas un moniteur : « le hub etait mort » reste vrai meme hub
    vivant. Un port dit ouvert et mesure ferme, lui, est un vrai desaccord.
    """
    etats, motifs = {}, []
    if not sonder:
        return etats, motifs
    for ligne in txt.splitlines():
        ports = {int(x) for x in _RE_PORT.findall(ligne)} & _PORTS_CONNUS
        if not ports:
            continue
        if not _RE_ETAT_POS.search(ligne) or _RE_ETAT_NEG.search(ligne):
            continue
        for port in sorted(ports):
            v = _sonde(port)
            etats[port] = v
            if v == "FERME":
                m = f"port :{port} affirme ouvert — mesure FERME"
            elif v == "INDETERMINE":
                m = f"port :{port} affirme ouvert — sonde INDETERMINE (ni preuve ni dementi)"
            else:
                continue
            if m not in motifs:
                motifs.append(m)
    return etats, motifs


def _tokens(txt: str) -> set:
    """Tokens discriminants. Reutilise la liste de mots bannis du verificateur
    d'intention quand elle est disponible : les mots ubiquitaires du projet
    (`nokido`, `forge`, `hub`) matchent partout et fabriquent des recouvrements."""
    try:
        from nokido_agent.tools.forge_intent_verifier import _BANNIS, _RE_TOK
        return {t for t in _RE_TOK.findall(txt.lower()) if t not in _BANNIS}
    except Exception:
        return set(_RE_TOK_LOCAL.findall(txt.lower()))


def _recouvrement_fort(res: list) -> None:
    """Selection PLUS DURE que `_supersessions`, qui suffit a suggerer une piste
    mais pas a porter un verdict.

    Mesure 2026-08-16 : a deux termes rares partages, 341 memoires sur 593
    ressortaient « recouvertes » — 58 % du corpus, donc plus aucune
    discrimination. On exige ici un recouvrement ABSOLU (>= _INTER_MIN termes) ET
    RELATIF (>= _INTER_RATIO du vocabulaire rare de la memoire), et l'on retient
    le MEILLEUR candidat plutot que le premier rencontre.
    """
    for a in res:
        a["recouverte_fort_par"] = None
        sa = set(a.get("termes_rares") or [])
        if len(sa) < _INTER_MIN or not a.get("revu_le"):
            continue
        best, best_n = None, 0
        for b in res:
            if b is a or not b.get("revu_le") or b["revu_le"] <= a["revu_le"]:
                continue
            n = len(sa & set(b.get("termes_rares") or []))
            if n > best_n:
                best, best_n = b, n
        if best and best_n >= _INTER_MIN and best_n / len(sa) >= _INTER_RATIO:
            a["recouverte_fort_par"] = f"{best['texte']} ({best_n} termes rares partages)"


def _motifs_chemins(mdir: Path) -> dict:
    """Delegue au compactor : renommes, deplaces en _attic, citations introuvables."""
    out: dict = {}
    try:
        from nokido_agent.tools.forge_memory_compactor import audit as _audit
        a = _audit(mdir, ROOT)
    except Exception as exc:
        return {"_ERREUR_AUDIT": f"{type(exc).__name__}: {exc}"}
    for c in a.get("a_reviser") or []:
        out.setdefault(c["memoire"], []).append(f"chemin deplace: {c['cite']} -> {c['desormais']}")
    for c in a.get("renommes") or []:
        out.setdefault(c["memoire"], []).append(f"chemin renomme: {c['cite']} -> {c['desormais']}")
    for c in a.get("citations_introuvables") or []:
        out.setdefault(c["memoire"], []).append(f"chemin introuvable: {c['cite']}")
    return out


# ── AXE 4 : ANCRAGE — une memoire n'a pas plus d'autorite que sa preuve ───────
# Hierarchie figee avec l'owner le 2026-09-05, du plus fort au plus faible :
#   1. comportement mesure MAINTENANT · 2. code + NR · 3. SSoT du depot
#   4. memoire · 5. souvenir conversationnel
# Une memoire ne doit JAMAIS battre un NR vert ni un commit. Cas paye le meme jour :
# une fiche affirmait « axes[nom] ecrase l'antecedent, donc rejeu impossible » alors
# qu'un NR de huit tests prouvait le contraire depuis la veille — la fiche etait
# VRAIE a son ecriture et FAUSSE le lendemain, sans rien pour le signaler.
#
# Les trois axes precedents mesurent la peremption par l'AGE, les chemins morts et
# l'etat du monde. Aucun ne repond a « la source citee a-t-elle change depuis que
# cette memoire a ete verifiee ? ». C'est la seule question mecaniquement decidable,
# et c'est celle-la qu'on ajoute.
CLASSES = ("RULE", "DECISION", "POINTER", "NON_CLASSE")
ANCRAGE_ACTIF = "ACTIVE"
ANCRAGE_STALE = "STALE"
ANCRAGE_SUPERSEDED = "SUPERSEDED"
ANCRAGE_INCONNU = "UNKNOWN"


def frontmatter(txt: str) -> dict:
    """Champs du frontmatter, a plat. `{}` si absent — jamais d'exception."""
    if not txt.startswith("---"):
        return {}
    fin = txt.find("\n---", 3)
    if fin < 0:
        return {}
    champs = {}
    for ligne in txt[3:fin].splitlines():
        if ":" not in ligne:
            continue
        cle, _, val = ligne.partition(":")
        val = val.strip()
        if val:
            champs[cle.strip().lstrip("- ").lower()] = val
    return champs


def classe(fm: dict) -> str:
    """RULE (regle durable) · DECISION (choix en vigueur) · POINTER (fait ancre).

    Derivee de ce que la fiche PORTE, et non d'une taxonomie parallele a declarer :
    une fiche qui cite une source est un POINTER, qu'elle le dise ou non. Le reste
    sort `NON_CLASSE` — nomme, pour qu'une fiche sans ancrage ne se presente pas
    comme un fait courant.
    """
    dit = (fm.get("classe") or "").upper()
    if dit in CLASSES:
        return dit
    if fm.get("source"):
        return "POINTER"
    t = (fm.get("type") or "").lower()
    if t == "feedback":
        return "RULE"
    if t in ("project", "reference", "user"):
        return "DECISION"
    return "NON_CLASSE"


def _dernier_commit(source: str, racine: Path) -> tuple:
    """(sha, erreur) du dernier commit touchant `source`. `(None, motif)` si ILLISIBLE.

    « Je n'ai pas pu demander a git » n'est pas « la source n'a pas bouge » : le
    second acquitterait une fiche que personne n'a pu verifier.
    """
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(racine), "log", "-1",
             "--format=%H", "--", source],
            capture_output=True, text=True, errors="replace", timeout=30)
    except Exception as exc:  # noqa: BLE001
        return None, "git indisponible : %s" % type(exc).__name__
    if out.returncode != 0:
        return None, "git rc=%d" % out.returncode
    sha = (out.stdout or "").strip()
    return (sha, None) if sha else (None, "source inconnue de git : %s" % source)


def ancrage(fm: dict, racine: Path, dernier_commit=_dernier_commit) -> dict:
    """ACTIVE / STALE / SUPERSEDED / UNKNOWN — quatre etats, jamais deux.

    `dernier_commit` est injectable : le NR verrouille la LOGIQUE de verdict sans
    fabriquer un depot git, et la passe reelle interroge git.
    """
    if fm.get("superseded_by"):
        return {"etat": ANCRAGE_SUPERSEDED, "raison": "remplacee par %s"
                % fm["superseded_by"], "revalidable": False}
    src, vu = fm.get("source"), fm.get("valid_at")
    if not src:
        return {"etat": ANCRAGE_ACTIF, "raison": "aucune source citee : rien a "
                "revalider mecaniquement", "revalidable": False}
    if not vu:
        return {"etat": ANCRAGE_INCONNU, "raison": "source citee SANS commit de "
                "verification : l'ancrage est incomplet", "revalidable": False}
    sha, err = dernier_commit(src, racine)
    if err:
        return {"etat": ANCRAGE_INCONNU, "raison": err, "revalidable": True}
    if not sha.startswith(vu) and not vu.startswith(sha[:7]):
        return {"etat": ANCRAGE_STALE, "revalidable": True,
                "raison": "%s a change depuis la verification (vu %s, courant %s)"
                          % (src, vu[:12], sha[:12])}
    return {"etat": ANCRAGE_ACTIF, "raison": None, "revalidable": True}


def analyser(mdir: Path, seuil_jours: float = 7.0, sonder: bool = True) -> dict:
    mdir = Path(mdir)
    corpus = {}
    for p in sorted(mdir.glob("*.md")):
        if p.name in _INDEX:
            continue
        corpus[p.name] = p.read_text(encoding="utf-8", errors="replace")
    if not corpus:
        return {"ERREUR": f"{mdir} : aucune memoire"}

    chemins = _motifs_chemins(mdir)
    erreur_audit = chemins.pop("_ERREUR_AUDIT", None)

    # rarete MESUREE sur le corpus, pas supposee
    toks = {nom: _tokens(txt) for nom, txt in corpus.items()}
    df = Counter()
    for t in toks.values():
        df.update(t)

    res = []
    for nom, txt in corpus.items():
        p = mdir / nom
        age = _age_jours(txt, p)
        motifs = list(chemins.get(nom, []))

        etats, m_ports = _confrontation_ports(txt, sonder)
        motifs.extend(m_ports)
        if etats and age > seuil_jours:
            motifs.append(f"affirmation d'etat agee de {age:.0f} j (seuil {seuil_jours:.0f})")

        fm = frontmatter(txt)
        cls = classe(fm)
        anc = ancrage(fm, _RACINE)
        if anc["etat"] == ANCRAGE_STALE:
            motifs.append("ancrage PERIME : %s" % anc["raison"])
        elif anc["etat"] == ANCRAGE_INCONNU and anc.get("revalidable"):
            motifs.append("ancrage NON VERIFIABLE : %s" % anc["raison"])

        res.append({
            "memoire": nom,
            "classe": cls,
            "ancrage": anc["etat"],
            "ancrage_raison": anc["raison"],
            "age_jours": round(age, 1),
            "texte": nom,                                    # cle attendue par _supersessions
            "revu_le": _date_memoire(txt, p),
            "termes_rares": sorted(t for t in toks[nom] if df[t] <= _DF_MAX),
            "ports": etats,
            "motifs": motifs,
        })

    _recouvrement_fort(res)

    for a in res:
        fort = a.pop("recouverte_fort_par", None)
        # Le recouvrement ne rend pas une memoire suspecte, il la rend REDONDANTE :
        # verdict distinct, pour que `A_VERIFIER` reste une liste d'actions.
        a["verdict"] = "A_VERIFIER" if a["motifs"] else ("RECOUVERTE" if fort else "FRAIS")
        a["recouverte_par"] = fort
        for k in ("texte", "revu_le", "termes_rares"):
            a.pop(k, None)

    a_verifier = [a for a in res if a["verdict"] == "A_VERIFIER"]
    a_verifier.sort(key=lambda x: (-len(x["motifs"]), -x["age_jours"]))
    recouvertes = [f"{a['memoire']} <- {a['recouverte_par']}"
                   for a in res if a["verdict"] == "RECOUVERTE"]
    return {
        "memory_dir": str(mdir),
        "n_memoires": len(res),
        "n_a_verifier": len(a_verifier),
        "n_recouvertes": len(recouvertes),
        "n_frais": sum(1 for a in res if a["verdict"] == "FRAIS"),
        "par_classe": {c: sum(1 for a in res if a["classe"] == c) for c in CLASSES},
        "par_ancrage": {e: sum(1 for a in res if a["ancrage"] == e)
                        for e in (ANCRAGE_ACTIF, ANCRAGE_STALE, ANCRAGE_SUPERSEDED,
                                  ANCRAGE_INCONNU)},
        "ports_sondes": dict(sorted(_CACHE_PORT.items())),
        "avertissement": erreur_audit,
        "a_verifier": a_verifier,
        "recouvertes": recouvertes[:40],
    }


def marquer(mdir: Path, rapport: dict, dry_run: bool = True) -> dict:
    """Prefixe `[A VERIFIER]` a la description du frontmatter. Borne au maximum :
    la description seule, jamais le corps — le corps est la connaissance, et une
    reecriture de memoire doit rester inspectable d'un coup d'oeil."""
    faits, echecs = [], []
    for a in rapport.get("a_verifier") or []:
        p = Path(mdir) / a["memoire"]
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            echecs.append({"memoire": a["memoire"], "err": type(exc).__name__})
            continue
        m = re.search(r'^(\s*description:\s*)"?(.*?)"?\s*$', txt, re.M)
        if not m or "[A VERIFIER]" in m.group(2):
            continue
        neuf = txt[:m.start()] + f'{m.group(1)}"[A VERIFIER] {m.group(2)}"' + txt[m.end():]
        faits.append({"memoire": a["memoire"], "motifs": a["motifs"][:3]})
        if not dry_run:
            try:
                p.write_text(neuf, encoding="utf-8")
            except OSError as exc:
                faits.pop()
                echecs.append({"memoire": a["memoire"], "ECRITURE_REFUSEE": type(exc).__name__})
    return {"marquees": len(faits), "dry_run": dry_run, "echecs": echecs, "detail": faits[:20]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Detecteur de memoire perimee (confrontation au reel)")
    ap.add_argument("--memory-dir", default=str(_DEFAULT_DIR))
    ap.add_argument("--seuil-jours", type=float, default=7.0)
    ap.add_argument("--sans-sonde", action="store_true", help="n'ouvre aucun socket")
    ap.add_argument("--limite", type=int, default=25)
    ap.add_argument("--marquer", action="store_true", help="ecrit [A VERIFIER] dans le frontmatter")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()

    rap = analyser(Path(ns.memory_dir), ns.seuil_jours, sonder=not ns.sans_sonde)
    if ns.marquer and "ERREUR" not in rap:
        rap["marquage"] = marquer(Path(ns.memory_dir), rap, dry_run=ns.dry_run)
    if not ns.json:
        rap["a_verifier"] = rap.get("a_verifier", [])[: ns.limite]
    print(json.dumps(rap, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
