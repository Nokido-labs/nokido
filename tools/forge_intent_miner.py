#!/usr/bin/env python3
"""
forge_intent_miner.py — Ce que l'owner a DEMANDE, et qu'on ne retrouve nulle part.

POURQUOI CET OUTIL
==================
L'axe `demandes` de forge_regression_sweep n'extrait que des CHEMINS de fichiers
cites. Il ne voit pas « il faut que… », « je veux… », « n'oublie pas… », « ATTENTION,
plus jamais… ». Or c'est exactement la forme que prend une consigne owner, et
c'est ce qui se perd : le 2026-08-12, le montage V:, 35 sessions non indexees, AGY
jamais ingere et le skill `diagram-design` etaient tous des intentions ENONCEES
qu'aucun etat durable ne portait.

METHODE — deterministe, zero quota
==================================
1. Ne lire que les tours OWNER (`[user]` / `[human]`) des chunks conversationnels.
2. Y reperer les marqueurs d'intention (imperatif, obligation, interdiction).
3. Extraire la phrase porteuse, la normaliser, compter les RECURRENCES : une
   consigne repetee 5 fois est une consigne qu'on n'a pas tenue.
4. Recouper avec les messages de commit : si aucun mot distinctif de l'intention
   n'apparait jamais dans l'historique git, elle n'a probablement jamais ete traitee.

Aucun jugement automatique : la sortie est un CLASSEMENT a arbitrer. Une intention
non retrouvee dans un commit peut avoir ete traitee autrement (config, service,
decision orale). On signale, on ne condamne pas.

USAGE
=====
    LAFORGE_PYTHON tools/forge_intent_miner.py --top 25
    LAFORGE_PYTHON tools/forge_intent_miner.py --extract   # -> sandbox/intentions.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"
OUT = ROOT / "sandbox" / "intentions.json"

# CLASSIFICATION : on n'ecrit PAS de liste de marqueurs a la main. Nokido a deja son
# routeur d'intention — `app/forge_intent_parser.parse_intent` (le « Thalamus / NLU
# tri » de CLAUDE.md section 10), qui rend un `ParsedIntent` avec action, target,
# verbs, entities et confidence. Le premier jet dupliquait cette capacite avec 30
# regex francaises : moins bon (lexical au lieu de semantique) et hors doctrine
# (« reutiliser avant reconstruire »). Signale par l'owner le 2026-08-12.
_SEUIL_CONFIANCE = float(__import__("os").environ.get("LAFORGE_INTENT_MIN_CONF", "0.30"))
sys.path.insert(0, str(ROOT))  # sans ca : ModuleNotFoundError sur le routeur
try:
    from nokido_agent.app.forge_intent_parser import parse_intent as _parse_intent
except Exception as _e:  # noqa: BLE001
    _parse_intent = None
    print(f"[intents] routeur d'intention INDISPONIBLE ({type(_e).__name__}) "
          f"-- aucune extraction possible, ce n'est PAS une absence d'intentions", flush=True)
# Etiquettes de tour OWNER, mesurees le 2026-08-12 — une par famille de corpus :
#   conv_claude / conv_gemini  -> `[user]`
#   conv_claude_desktop        -> `[human]`
#   conv_agy (Antigravity)     -> `[USER_EXPLICIT]`   (ses autres roles : MODEL, SYSTEM)
#   conv_gemini_web            -> `## [user]`         (MarkdownChunker prefixe d'un H2)
# Le premier jet ne connaissait que user|human en debut de ligne : les 150 sessions AGY
# et les 17 Gemini web ressortaient a ZERO intention, sans que rien ne le signale.
# Une famille absente du decompte est le symptome a surveiller ici.
_RE_TOUR_OWNER = re.compile(
    r"^(?:#{1,6}\s*)?\[(user|human|user_explicit)\]\s*(.*)$", re.IGNORECASE)
# Tout autre marqueur de role ferme le bloc owner en cours.
_RE_AUTRE_ROLE = re.compile(
    r"^(?:#{1,6}\s*)?\[(assistant|model|system|gemini|agy|tool)\]", re.IGNORECASE)
_RE_PHRASE = re.compile(r"[^.!?\n]{12,300}")
# Mots vides : inutiles pour identifier une intention, et trop frequents pour
# servir de sonde dans l'historique git.
_VIDES = {
    "il", "faut", "que", "les", "des", "une", "pour", "avec", "dans", "sur", "pas",
    "plus", "tout", "tous", "cette", "cela", "mais", "donc", "car", "est", "sont",
    "ete", "etre", "avoir", "fait", "faire", "veux", "peux", "dois", "bien", "tres",
    "aussi", "comme", "quand", "alors", "sans", "sous", "leur", "nous", "vous",
    "toujours", "jamais", "attention", "important", "oublie", "pense", "arrete",
    "the", "and", "you", "your", "not", "for", "with", "this", "that",
}


def _log(m: str) -> None:
    print(f"[intents] {m}", flush=True)


# Un tour owner contient BEAUCOUP de matiere collee : sorties de terminal, JSON,
# diffs, logs git. `parse_intent` y voit des actions (il est fait pour classer des
# commandes, pas pour trier la parole du copier-coller) : sans ce filtre, le top du
# classement etait entierement du bruit machine. Ce filtre ne classe pas l'intention
# — il decide si la phrase est de la PAROLE adressee a l'agent.
_RE_MACHINE = re.compile(
    r'\t|":|\{"|\};|-->|0x[0-9a-f]|\d{4}-\d{2}-\d{2}T|\b[0-9a-f]{7,}\b|'
    r'\[OK\]|\brc=|##\[|\bCRLF\b|\bLF\b', re.IGNORECASE)
# Marqueur de PERSONNE : l'owner s'adresse a l'agent ou parle de lui-meme.
_RE_PAROLE = re.compile(
    r"\b(tu|t'|te|toi|je|j'|me|moi|on|nous|il faut|faudrait|merci de|stp|"
    r"s'il te pla[iî]t)\b", re.IGNORECASE)


# Signatures de CODE ou de sortie machine collee. Premier jet trop tolerant : il
# suffisait d'un « on » perdu dans une docstring pour qu'un module entier passe
# pour une intention longue — le classement s'est rempli de fichiers .py colles.
_RE_CODE = re.compile(
    r"(?m)^\s*(?:def |class |import |from \s*\w+\s+import|#!/)|```|\"\"\"|Traceback|"
    r"\bself\.|=>|\{\"|^\s*\d+\t|[═╭╰│┃└├]")


def _est_bloc_parole(bloc: str) -> bool:
    """Le PARAGRAPHE est-il de la parole owner, ou du contenu colle ?

    Plus tolerant que `_est_parole_owner` sur le detail (une spec peut citer un
    chemin), plus exigeant sur l'ensemble : pas de signature de code, et une
    DENSITE de marques de personne — une vraie consigne dit « tu », « je »,
    « il faut » plusieurs fois ; un module colle, une seule fois par accident.
    """
    if _RE_CODE.search(bloc):
        return False
    chiffres = sum(c.isdigit() for c in bloc)
    if chiffres / max(1, len(bloc)) > 0.12:
        return False
    return len(_RE_PAROLE.findall(bloc)) >= max(2, len(bloc) // 400)


def _est_parole_owner(phrase: str) -> bool:
    if _RE_MACHINE.search(phrase):
        return False
    chiffres = sum(c.isdigit() for c in phrase)
    if chiffres / max(1, len(phrase)) > 0.15:
        return False
    return bool(_RE_PAROLE.search(phrase))


def _mots_cles(phrase: str) -> list[str]:
    mots = re.findall(r"[a-zA-Z_][\w_]{3,}", phrase.lower())
    return [m for m in mots if m not in _VIDES][:6]


def _signature(phrase: str):
    """Signature SEMANTIQUE d'une intention, via le routeur souverain.

    Rend (signature, mots_pour_recoupement) ou None si le texte ne porte pas
    d'intention actionnable. La signature est `action:cible` — deux formulations
    differentes de la meme demande se regroupent, ce qu'un sac de mots ratait.
    """
    if _parse_intent is None:
        return None
    try:
        pi = _parse_intent(phrase, use_llm=False)
    except Exception:  # noqa: BLE001
        return None
    if not getattr(pi, "action", None) or getattr(pi, "confidence", 0.0) < _SEUIL_CONFIANCE:
        return None
    cible = getattr(pi, "target", None)
    if not cible:
        ents = [str(e) for e in (getattr(pi, "entities", None) or []) if str(e).strip()]
        cible = ents[0] if ents else ""
    sig = f"{pi.action}:{str(cible)[:40]}".strip(":")
    mots = set(_mots_cles(f"{pi.action} {cible} " + " ".join(
        str(v) for v in (getattr(pi, "verbs", None) or []))))
    return (sig, sorted(mots)) if sig else None


def _commits_git() -> list[set[str]]:
    """Un ensemble de mots PAR COMMIT (et non un bloc unique).

    Le premier jet concatenait tout l'historique en une seule chaine et cherchait si
    UN mot-cle y figurait « quelque part ». Sur des milliers de commits, presque
    n'importe quel mot apparait : le filtre ne filtrait RIEN (2 orphelines sur 703,
    et c'etaient deux messages d'agacement). Ce qui compte, c'est la CO-OCCURRENCE
    des mots d'une intention dans UN MEME commit -- c'est ca, « le sujet a ete traite ».
    """
    try:
        p = subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
             "log", "--pretty=%s %b%x00", "--no-merges"],
            capture_output=True, text=True, errors="replace", timeout=180,
        )
    except Exception as e:  # noqa: BLE001
        _log(f"historique git illisible ({type(e).__name__}) -- recoupement DESACTIVE")
        return []
    return [set(re.findall(r"[a-zA-Z_][\w_]{3,}", m.lower()))
            for m in (p.stdout or "").split("\x00") if m.strip()]


def extraire() -> dict:
    if not RAG_DB.exists():
        return {"ok": False, "raison": f"base absente ({RAG_DB})"}
    con = sqlite3.connect(f"file:{RAG_DB}?mode=ro", uri=True, timeout=60)
    lignes = con.execute(
        "SELECT source, text FROM rag_chunks WHERE domain = 'conv' AND text IS NOT NULL"
    ).fetchall()
    con.close()

    groupes: dict[str, dict] = defaultdict(
        lambda: {"phrases": [], "sources": set(), "n": 0})
    n_tours = 0
    for source, texte in lignes:
        # Lecture par BLOC, pas par ligne. `## [user]` est un titre markdown SEUL sur
        # sa ligne (chunker Gemini web) : scanner la ligne du marqueur ne voyait alors
        # qu'une etiquette vide, et le contenu qui suit etait perdu. Mesure du
        # 2026-08-12 : 150 sessions AGY et 17 Gemini web rendaient ZERO intention.
        # Un bloc owner court du marqueur jusqu'au marqueur de role suivant.
        blocs: list[str] = []
        courant: list[str] | None = None
        for ligne in str(texte).splitlines():
            nue = ligne.strip()
            m = _RE_TOUR_OWNER.match(nue)
            if m:
                if courant is not None:
                    blocs.append(" ".join(courant))
                courant = [m.group(2)]
                n_tours += 1
                continue
            if courant is not None:
                if _RE_AUTRE_ROLE.match(nue):  # fin du tour owner
                    blocs.append(" ".join(courant))
                    courant = None
                else:
                    courant.append(nue)
        if courant is not None:
            blocs.append(" ".join(courant))

        for corps in blocs:
            actions_bloc: list[str] = []
            mots_bloc: set[str] = set()
            for phrase in _RE_PHRASE.findall(corps):
                phrase = phrase.strip()
                res_b = _signature(phrase)
                if res_b is not None:
                    actions_bloc.append(res_b[0].split(":")[0])
                    mots_bloc.update(res_b[1])
                if not _est_parole_owner(phrase):
                    continue
                res = _signature(phrase)
                if res is None:
                    continue
                sig, mots = res
                g = groupes[sig]
                g.setdefault("mots", set()).update(mots)
                g["n"] += 1
                g["portee"] = "courte"
                g["sources"].add(str(source).split("/")[0])
                if len(g["phrases"]) < 3:
                    g["phrases"].append(phrase[:220])

            # INTENTION LONGUE : une consigne etalee sur un paragraphe. Le decoupage
            # en phrases de 300 caracteres la hachait en fragments juges separement,
            # et le sens global se perdait — c'est la que vivent les SPECS, pas les
            # ordres brefs (angle mort signale par l'owner le 2026-08-12). On regroupe
            # sur la combinaison des actions du bloc : cinq phrases liees decrivant une
            # meme architecture forment UNE intention, pas cinq.
            if len(corps) >= 320 and len(set(actions_bloc)) >= 2 and _est_bloc_parole(corps):
                sig = "long:" + "+".join(sorted(set(actions_bloc))[:3])
                g = groupes[sig]
                g.setdefault("mots", set()).update(mots_bloc)
                g["n"] += 1
                g["portee"] = "longue"
                g["sources"].add(str(source).split("/")[0])
                if len(g["phrases"]) < 3:
                    g["phrases"].append(corps[:220])

    commits = _commits_git()
    items = []
    for sig, g in groupes.items():
        cles = set(g.get("mots") or [])
        # Couverture = plus grande fraction des mots de l'intention reunis dans UN
        # SEUL commit. 1.0 = le sujet a clairement ete traite ; 0.0 = aucune trace.
        meilleure = 0.0
        if commits and cles:
            meilleure = max(len(cles & c) / len(cles) for c in commits)
        items.append({
            "signature": sig,
            "occurrences": g["n"],
            "familles": sorted(g["sources"]),
            "exemples": g["phrases"],
            "couverture_git": round(meilleure, 2),
            "portee": g.get("portee", "courte"),
            "jamais_dans_git": bool(commits) and meilleure < 0.5,
        })
    # Les plus repetees d'abord, et a recurrence egale les moins couvertes :
    # une consigne dite 8 fois dont rien ne se retrouve en commit est le pire cas.
    items.sort(key=lambda d: (-d["occurrences"], d["couverture_git"]))
    return {"ok": True, "tours_owner": n_tours, "chunks": len(lignes),
            "commits_scannes": len(commits),
            "intentions": items, "recoupement_git": bool(commits)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Intentions owner jamais retrouvees")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--extract", action="store_true", help="ecrit sandbox/intentions.json")
    ap.add_argument("--only-orphelines", action="store_true",
                    help="ne montrer que celles absentes de l'historique git")
    a = ap.parse_args()

    d = extraire()
    if not d.get("ok"):
        _log(f"INDETERMINE : {d.get('raison')}")
        return 2

    items = d["intentions"]
    _log(f"{d['chunks']} chunks conv, {d['tours_owner']} tours owner, "
         f"{len(items)} intentions distinctes"
         + ("" if d["recoupement_git"] else "  [recoupement git INDISPONIBLE]"))

    if a.extract:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"ecrit : {OUT}")

    montrables = [i for i in items if i["jamais_dans_git"]] if a.only_orphelines else items
    orphelines = sum(1 for i in items if i["jamais_dans_git"])
    _log(f"{orphelines} intention(s) dont AUCUN mot cle n'apparait dans l'historique git")
    par_famille = Counter(f for i in items for f in i["familles"])
    _log("  origine : " + " | ".join(f"{k}={v}" for k, v in par_famille.most_common()))
    # Garde anti-angle-mort : une famille ingeree mais absente du decompte signifie
    # que son etiquette de tour owner n'est pas reconnue -- pas qu'elle est muette.
    attendues = {"conv_claude", "conv_claude_desktop", "conv_agy",
                 "conv_gemini", "conv_gemini_web"}
    manquantes = sorted(attendues - set(par_famille))
    if manquantes:
        _log("  ⚠ AUCUNE intention extraite de : " + ", ".join(manquantes)
             + "  -> etiquette de tour owner non reconnue ? verifier avant de conclure")

    n_long = sum(1 for i in items if i.get("portee") == "longue")
    _log(f"  portee : {len(items) - n_long} courte(s) · {n_long} longue(s)")
    for i in montrables[:a.top]:
        _log(f"  [{i['occurrences']:>3}x] [{i.get('portee', '?')[:6]:<6}] "
             f"[git {int(i['couverture_git'] * 100):>3}%] {i['exemples'][0]}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
