#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_roadmap_keeper.py — OrganAgent : TENUE + PRÉSENTATION de la ROADMAP vivante.

Directive user : un AGENT DÉDIÉ tient (maintient à jour) ET présente la roadmap.
Sous contrat OrganAgent (cf. blackboard architecture_rules:organ_agent_contract).

FÉDÈRE l'existant (anti-dup, ne réimplémente RIEN) :
  - TENUE / regen   -> forge_roadmap_synth (collecte RAG+docs anchors -> buckets ->
                       reduce -> ROADMAP.md). Override groq quand l'iGPU local est lent.
  - PRÉSENTATION    -> rend le doc canon en VUES : full / terse / prio / status / delta.
  - STATUT          -> parse les items P0/P1/P2 + état (done/wip/open) du markdown.

ANTI-DUP justifié : forge_roadmap_synth = GÉNÉRATION de contenu (un script one-off, pas
un owner) ; forge_cowork (secrétaire) = lifecycle de PROJETS-docs, PAS la roadmap
stratégique. Ce keeper = l'OWNER + presenter dédié de docs/ROADMAP.md, sous contrat
OrganAgent. Pattern keeper repris de forge_docker_keeper / forge_watch_agent_worker.

CLI :
  --regen [--fast groq] [--ctx run_job|trusted]   TENUE (régénère le doc, déportable)
  --present [full|terse|prio|status|delta]         PRÉSENTATION (lecture, ~instantané)
  --status                                         compteurs P0/P1/P2 × état
  --contract                                       expose le contrat OrganAgent (JSON)
  (sans argument) = --regen --fast groq            défaut quand lancé détaché (run_job)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT))

CANON = ROOT / "docs" / "ROADMAP.md"                       # source de vérité (git)
GEN = ROOT / "docs" / "ROADMAP.gen.md"                     # nom de regen (évite la race)
WORKSPACE_GEN = ROOT / "sandbox" / "workspace" / "ROADMAP.gen.md"  # redirect run_job
PREV = ROOT / "sandbox" / "workspace" / "roadmap_prev.md"  # snapshot pour --delta

# Contrat OrganAgent (organisme d'agents). Le keeper est un AGENT (état+proactif+autonome).
CONTRACT = {
    "agent": "ROADMAP_KEEPER",
    "organ": "observability/governance",          # gouvernance de trajectoire (SNP)
    "modalities": ["text", "markdown"],
    "proactive_triggers": ["post_commit", "new_anchor", "schedule_daily", "on_request"],
    "poolable": False,                            # keeper UNIQUE (single source de vérité)
    "connects_to": ["forge_roadmap_synth", "forge_knowledge_concierge(portier)",
                    "forge_postal(facteur)", "RAG(domain=reference)", "blackboard"],
    "owns": "docs/ROADMAP.md",
    "verbs": ["regen", "present", "status", "contract"],
}

# Marqueurs d'état tolérés dans le markdown (robuste aux variantes de rendu).
_DONE = ("✅", "[x]", "[X]", "(done)", "DONE", "LIVRÉ", "FAIT")
_WIP = ("🔄", "[~]", "[/]", "(wip)", "WIP", "EN COURS", "IN-PROGRESS")
_OPEN = ("⬜", "[ ]", "(open)", "TODO", "RESTE", "OUVERT")
_PRIOS = ("P0", "P1", "P2", "P3")


def _doc_path() -> Path:
    """Chemin du doc à présenter : canon (git) d'abord, sinon la regen déportée."""
    for p in (CANON, GEN, WORKSPACE_GEN):
        if p.exists() and p.stat().st_size > 0:
            return p
    return CANON


# ── TENUE ────────────────────────────────────────────────────────────────────
def regen(fast: str = "groq", ctx: str | None = None) -> dict:
    """Régénère la roadmap via forge_roadmap_synth (FÉDÉRATION). Override `fast` (groq)
    quand l'iGPU est trop lent ; le local reste le défaut souverain du synth. Écrit sous
    un nom distinct (ROADMAP.gen.md) pour ne PAS entrer en collision avec un autre run."""
    import os
    os.environ["LAFORGE_SYNTH_FAST"] = fast or ""
    if ctx:
        os.environ["LAFORGE_CTX"] = ctx
    from nokido_agent.tools import forge_roadmap_synth as synth
    synth.OUT = GEN  # nom de regen distinct (writable_path redirige en sandbox si déporté)
    try:
        from nokido_agent.app.forge_resolver import writable_path
        eff, _red = writable_path(GEN, context=os.environ.get("LAFORGE_CTX", "run_job"))
    except Exception:  # noqa: BLE001
        eff = GEN
    rc = synth.main()
    return {"rc": rc, "written": str(eff), "fast": fast}


def promote() -> dict:
    """Promeut la regen (ROADMAP.gen.md) vers le canon docs/ROADMAP.md. À exécuter EN
    contexte inscriptible-repo (trusted/user) ; le sandbox déporté ne peut pas écrire docs/."""
    src = GEN if GEN.exists() else WORKSPACE_GEN
    if not (src.exists() and src.stat().st_size > 0):
        return {"ok": False, "reason": f"aucune regen à promouvoir ({src})"}
    if CANON.exists():
        PREV.parent.mkdir(parents=True, exist_ok=True)
        PREV.write_text(CANON.read_text("utf-8", "ignore"), encoding="utf-8")  # snapshot delta
    CANON.write_text(src.read_text("utf-8", "ignore"), encoding="utf-8")
    return {"ok": True, "promoted_from": str(src), "canon": str(CANON)}


# ── PRÉSENTATION ──────────────────────────────────────────────────────────────
def _classify_state(line: str) -> str:
    u = line.upper()
    if any(m.upper() in u for m in _DONE):
        return "done"
    if any(m.upper() in u for m in _WIP):
        return "wip"
    if any(m.upper() in u for m in _OPEN):
        return "open"
    return "item"


def _render(text: str, view: str = "terse") -> str:
    """Fonction PURE de rendu (testable sans I/O). Vues sur le markdown roadmap."""
    if not text.strip():
        return "[roadmap vide — lancer `--regen`]"
    lines = text.splitlines()
    if view == "full":
        return text
    if view in ("terse", "prio"):
        keep = [ln for ln in lines
                if ln.lstrip().startswith("#")
                or any(p in ln for p in _PRIOS) or "⭐" in ln]
        if view == "terse":
            return "\n".join(keep) if keep else text[:1500]
        # prio : regroupe par priorité
        buckets = {p: [] for p in _PRIOS}
        other = []
        for ln in keep:
            hit = next((p for p in _PRIOS if p in ln), None)
            (buckets[hit] if hit else other).append(ln.strip())
        out = []
        for p in _PRIOS:
            if buckets[p]:
                out.append(f"### {p}")
                out.extend(f"  {x}" for x in buckets[p])
        return "\n".join(out) if out else "\n".join(keep)
    if view == "status":
        return json.dumps(_status(text), ensure_ascii=False, indent=2)
    if view == "delta":
        prev = PREV.read_text("utf-8", "ignore") if PREV.exists() else ""
        cur_set = {ln.strip() for ln in lines if ln.strip()}
        prev_set = {ln.strip() for ln in prev.splitlines() if ln.strip()}
        added = sorted(cur_set - prev_set)[:40]
        removed = sorted(prev_set - cur_set)[:40]
        return ("## Δ depuis le dernier snapshot\n+ "
                + "\n+ ".join(added) + ("\n- " + "\n- ".join(removed) if removed else ""))
    return text


def _status(text: str) -> dict:
    """Compteurs : items (bullets) par priorité × état. La priorité vient de la SECTION
    courante (header `## P0…`) ou, à défaut, d'un token prio inline dans le bullet."""
    counts = {p: {"done": 0, "wip": 0, "open": 0, "item": 0} for p in _PRIOS}
    total = {"done": 0, "wip": 0, "open": 0, "item": 0}
    cur = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            cur = next((p for p in _PRIOS if p in ln), None)  # section prio (ou None)
            continue
        if not (s.startswith("-") or s.startswith("*") or s.startswith("+")):
            continue
        prio = next((p for p in _PRIOS if p in ln), cur)  # inline > section
        st = _classify_state(ln)
        total[st] += 1
        if prio:
            counts[prio][st] += 1
    return {"by_priority": counts, "total": total,
            "doc": str(_doc_path()), "exists": _doc_path().exists()}


def present(view: str = "terse") -> str:
    if view == "verified":
        v = verify()
        return ("## Registre intent VÉRIFIÉ — " + json.dumps(v["counts"], ensure_ascii=False)
                + f"\n\n### 🔴 DEAD (intention → module ABSENT = stub/oublié) [{len(v['dead'])}]\n"
                + "\n".join(f"- {x['src']}:{x['line']} {x['refs']} — {x['text']}" for x in v["dead"][:60])
                + f"\n\n### 🟡 DONE? (réf existe → clore l'intention) [{len(v['done_to_close'])}]\n"
                + "\n".join(f"- {x['src']}:{x['line']} {x['refs']}" for x in v["done_to_close"][:60]))
    p = _doc_path()
    if not (p.exists() and p.stat().st_size > 0):
        return "[roadmap absente — lancer `forge_roadmap_keeper --regen`]"
    return _render(p.read_text("utf-8", "ignore"), view)


def status() -> dict:
    p = _doc_path()
    if not (p.exists() and p.stat().st_size > 0):
        return {"exists": False, "doc": str(p)}
    return _status(p.read_text("utf-8", "ignore"))


def finalize() -> dict:
    """Clôt la TENUE en contexte inscriptible-repo (trusted) : promeut la regen vers le
    canon -> INTERNALISE dans le substrat souverain (RAG) -> ANNONCE aux agents (facteur).
    Sépare l'écriture-repo (ici) de la regen déportée-sandbox (qui ne peut pas écrire docs/)."""
    out = {"promote": promote()}
    try:
        from nokido_agent.app.forge_keeper_base import internalize, announce
        body = CANON.read_text("utf-8", "ignore") if CANON.exists() else ""
        out["internalize"] = internalize("roadmap", body, domain="reference")
        out["announce"] = announce("roadmap", "tenue", "ROADMAP régénérée + internalisée")
    except Exception as e:  # noqa: BLE001
        out["internalize"] = {"ok": False, "error": str(e)}
    return out


# ── VÉRIFICATION (directive user 2026-06-17 : centraliser + VÉRIFIER l'intention,
# ne plus nourrir stub & code mort / intention oubliée). Confronte au code réel. ──
import re as _re

# CREATE-intent = intention de CRÉER/CÂBLER un module (signal actionnable), distincte du
# descriptif ("stub dans X", "reste à X" = déjà câblé). On ne tracke QUE les create-intents
# = anti-bruit (sinon stub-délégation + RESTE descriptif polluent le registre).
_CREATE = _re.compile(r"(à cr[ée]er|à coder|à c[âa]bler|next[- ]step|\bTODO\b|à faire|\bbacklog\b)", _re.I)
_FORGE_REF = _re.compile(r"\b((?:la)?forge_[a-z0-9_]+)\b")


# Objets du corps qui portent un nom `forge_*` SANS etre des fichiers .py : triggers,
# tables, vues. Mesure du 2026-09-18 : `forge_tier_guard` est un TRIGGER SQLite, et
# `--verify` le declarait « dead (stub/oublie) » parce qu'aucun `.py` ne porte ce nom.
# Un instrument de CLOTURE qui compte des morts imaginaires fait fermer des chantiers
# qui n'existent pas et perdre la confiance dans les vrais.
#
# Lecture du CATALOGUE seulement (`sqlite_master`, quelques centaines de lignes) --
# jamais `rag_chunks`, dont le balayage a couche ce depot six fois. Cache de process :
# la reponse ne change pas pendant un run.
_OBJETS_SQL: set | None = None


def _objets_sql() -> set:
    """Noms des objets SQL du corps, ou un ENSEMBLE VIDE si la base est illisible.

    ILLISIBLE n'est PAS « aucun objet » : dans ce cas on ne requalifie rien et le
    comportement d'origine s'applique — mieux vaut un faux mort signale qu'un vrai
    mort masque par une base qu'on n'a pas pu lire.
    """
    global _OBJETS_SQL
    if _OBJETS_SQL is not None:
        return _OBJETS_SQL
    _OBJETS_SQL = set()
    try:
        import sqlite3 as _sq
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "app"))
        from forge_db_path import DB_PATH as _DB  # noqa: PLC0415

        with _sq.connect(str(_DB), timeout=5) as _c:
            _OBJETS_SQL = {r[0] for r in _c.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'forge\\_%' ESCAPE '\\'")}
    except Exception:  # noqa: BLE001 — muet-ok : base absente = aucune requalification
        _OBJETS_SQL = set()
    return _OBJETS_SQL


def _module_exists(name: str) -> bool:
    """Le module (la)forge_* existe-t-il dans le code ? Anti faux-positif : app/, tools/,
    sous-dirs (ctf…), + variante nokido_ (forge_hub→nokido_hub)."""
    cands = {name}
    if name.startswith("forge_"):
        cands.add("la" + name)             # forge_hub -> nokido_hub
        cands.add(name[len("forge_"):])    # forge_api_facade -> api_facade (naming-drift)
    elif name.startswith("nokido_"):
        cands.add(name[len("nokido_"):])
    for n in cands:
        for d in (ROOT / "app", ROOT / "tools"):
            if (d / f"{n}.py").exists() or list(d.rglob(f"{n}.py")):
                return True
    # Pas un fichier : l'objet existe peut-etre sous une AUTRE FORME dans le corps.
    return name in _objets_sql()


# GELE n'est pas MORT — distinction arretee par l'owner (« geler, jamais supprimer »)
# et payee le 2026-09-18. `docs/roadmap_event_mesh_neural.md` etait compte « dead »
# alors qu'il DIT lui-meme, en tete : « NON IMPLEMENTE — backlog (audit 2026-08-21) »,
# qu'il nomme correctement les trois bus existants, et qu'il porte une decision
# explicite « PAUSE » assortie de son critere de reprise (« si event throughput
# < 100/s actuel, pas de besoin urgent »).
#
# Un document qui a DEJA instruit sa dette n'est pas un oubli : c'est une decision.
# Les confondre fait deux degats opposes — on « decouvre » un chantier que quelqu'un
# a deja tranche, et on noie les VRAIS oublis dans le bruit.
#
# On lit l'EN-TETE du document (les marqueurs de gel s'y posent, pas sur la ligne de
# l'intention), borne a 2000 caracteres : au-dela ce n'est plus une annonce de statut.
_GEL = re.compile(
    r"(NON[\s_-]?IMPLEMENT|NON[\s_-]?IMPLÉMENT|BACKLOG|PRE[\s_-]?DECISION|PRÉ[\s_-]?DÉCISION"
    r"|PAUSE|GEL[EÉ]|PERIM|PÉRIM|ABANDONN|REPORTE|REPORTÉ|OBSOLET)", re.I)
# LA BORNE EST EN LIGNES, PAS EN CARACTERES — defaut trouve par le NR le 2026-09-18.
# Une borne de 2 000 caracteres couvrait l'INTEGRALITE d'un document court : un mot
# « backlog » ecrit n'importe ou dans un fichier de 60 caracteres gelait TOUT le
# fichier, et une vraie intention disparaissait sous une fausse instruction. Un en-tete
# est une notion STRUCTURELLE — titre, puis annonce de statut — donc on lit les
# premieres LIGNES, ce qui ne depend pas de la taille du document.
_EN_TETE_LIGNES = 8
_EN_TETE_CHARS = 2000        # plafond de securite sur un en-tete tres verbeux


# GEL PORTE PAR LA LIGNE ELLE-MEME — motif STRICT, et la difference compte.
#
# `docs/ROADMAP_GLOBALE_2026-09-06.md:23` etait compte « mort » alors que sa ligne dit
# « **NON DEMONTREE** » dans un tableau de statuts : l'auteur a instruit sa dette, mais
# a la ligne et non en tete, la ou `_document_gele` regarde.
#
# Ce motif-ci est VOLONTAIREMENT plus etroit que celui de l'en-tete : il exclut
# « backlog » et « pre-decision », qui sont trop courants pour qualifier une ligne
# isolee. Sans cette restriction, « TODO : vider le backlog » serait lu comme un gel,
# et on ferait disparaitre une vraie intention sous une fausse instruction -- le
# defaut exactement symetrique de celui qu'on corrige.
_GEL_LIGNE = re.compile(
    r"(NON[\s_-]?IMPLEMENT|NON[\s_-]?IMPLÉMENT|NON[\s_-]?DEMONTR|NON[\s_-]?DÉMONTR"
    r"|PERIM[EÉ]|PÉRIM[EÉ]|ABANDONN|OBSOLET|\bGEL[EÉ]\b|\bPAUSE\b)", re.I)


def _document_gele(txt: str, avant_ligne: int | None = None) -> str:
    """Motif de gel trouve dans l'EN-TETE, ou chaine vide. Sert a NE PAS crier au mort.

    L'en-tete est ce qui PRECEDE l'intention qualifiee : une annonce de statut est
    posee en tete d'un document et vaut pour ce qui suit, jamais pour ce qui la
    precede. Sans `avant_ligne`, un document de trois lignes etait integralement lu
    comme son propre en-tete, si bien qu'un mot ecrit DANS l'intention la gelait
    elle-meme -- defaut trouve par le NR, pas par la relecture.
    """
    lignes = txt.splitlines()[:_EN_TETE_LIGNES]
    if avant_ligne is not None:
        lignes = lignes[:max(0, avant_ligne - 1)]
    m = _GEL.search("\n".join(lignes)[:_EN_TETE_CHARS])
    return m.group(0) if m else ""


def _ligne_gelee(ligne: str) -> str:
    """Motif de gel porte par la LIGNE, ou chaine vide. Motif strict, cf. ci-dessus."""
    m = _GEL_LIGNE.search(ligne)
    return m.group(0) if m else ""


# « backlog » EST DANS `_CREATE` — et c'est aussi un mot du METIER (2026-09-18).
#
# Mesure : sur 394 intentions dites « ouvertes », 196 (50 %) etaient declenchees par ce
# seul mot, dont 169 dans du CODE `.py` et seulement 31 portaient un `#` ou un `TODO`.
# Les autres sont des colonnes SQL, des parametres et des variables :
#
#     backlog TEXT NOT NULL DEFAULT '[]'              <- une colonne
#     def create_project(goal, backlog: list[dict])   <- un parametre
#     backlog = _backlog()                            <- une variable
#
# Un instrument qui compte ces lignes annonce 138 chantiers qui n'existent pas. Le
# defaut est le meme que « un instrument ne lit jamais son propre vocabulaire »,
# elargi : ici il confond un TERME METIER avec un marqueur de statut, et le chiffre
# qu'il publie inquiete sans servir.
#
# Regle : dans du CODE, `backlog` ne vaut comme intention que s'il est accompagne d'un
# marqueur de commentaire ou de tache. Dans un `.md`, il reste un marqueur legitime --
# un plan qui ecrit « backlog » parle bien de travail a faire.
_MARQUEUR_TACHE = re.compile(r"(#|//|\bTODO\b|\bFIXME\b|\bXXX\b|- \[ \])")
_SEUL_BACKLOG = re.compile(r"(à cr[ée]er|à coder|à c[âa]bler|next[- ]step|\bTODO\b|à faire)", re.I)


# `todo` MINUSCULE EST UN NOM DE VARIABLE — mesure du 2026-09-18, tri par agent local.
#
# `_CREATE` teste `\bTODO\b` avec IGNORECASE, si bien que ces lignes comptaient comme
# des chantiers :
#
#     for todo in lots:              /  todo = _restant()  /  print(f"{len(todo)} …")
#
# La convention est universelle et c'est elle qui porte le sens : un marqueur de tache
# s'ecrit TODO en MAJUSCULES. En minuscules dans du code, c'est un identifiant.
# On ne filtre que si AUCUNE majuscule n'est presente ET qu'aucun marqueur de
# commentaire n'accompagne le mot -- « # todo: brancher X » reste une intention.
_TODO_MAJ = re.compile(r"\bTODO\b")
_TODO_MIN = re.compile(r"\btodo\b")


def _todo_identifiant(ligne: str) -> bool:
    """Le mot `todo` est-il un identifiant plutot qu'un marqueur de tache ?"""
    if _TODO_MAJ.search(ligne):
        return False                      # convention respectee : c'est un marqueur
    if not _TODO_MIN.search(ligne):
        return False                      # pas de `todo` du tout, rien a dire ici
    return not re.search(r"(#|//)[^\n]*\btodo\b", ligne, re.I)


def _bruit_lexical(ligne: str) -> bool:
    """Vrai si la ligne n'est retenue que par du vocabulaire, sans marqueur de tache.

    On ne filtre jamais une ligne portant un VRAI declencheur : « à créer », « TODO »
    en majuscules, « à câbler »… restent des intentions, ou qu'elles soient.
    """
    if _todo_identifiant(ligne) and not re.search(
            r"(à cr[ée]er|à coder|à c[âa]bler|next[- ]step|à faire)", ligne, re.I):
        return True                       # `todo` variable, et rien d'autre
    if _SEUL_BACKLOG.search(ligne):
        return False                      # un vrai marqueur est present : on garde
    return not _MARQUEUR_TACHE.search(ligne)


# UN MARQUEUR CITE N'EST PAS UNE INTENTION — 5e occurrence du meme motif (2026-09-18).
#
# Apres le filtre sur « backlog », les lignes restantes contenaient encore :
#
#     if re.match(r"#\s*(TODO|FIXME|HACK)\b", s)     <- du code qui DETECTE des TODO
#     # 3. Verification TODO/FIXME                   <- un commentaire qui DECRIT
#     > Marqueurs : ✅ fait · 🔄 en cours · ⬜ à faire  <- une LEGENDE
#
# Et le fichier le plus « charge en intentions » du depot etait `forge_roadmap_keeper.py`
# lui-meme, avec 15 -- parce que la prose de cet instrument cite les mots qu'il traque.
# C'est « un instrument ne lit jamais son propre vocabulaire », pris au pied de la lettre.
#
# Deux regles, et elles sont volontairement etroites : un marqueur enferme dans une
# EXPRESSION REGULIERE ou une CHAINE de detection appartient au vocabulaire du code,
# pas a son plan de travail ; et un fichier dont le METIER est de traquer ces marqueurs
# ne se compte pas lui-meme.
_CITATION = re.compile(r"(re\.(match|search|compile|findall|sub)|r\"|r'|\bregex\b|Marqueurs\s*:)")
_TRAQUEURS = ("forge_roadmap_keeper", "forge_intent_audit", "forge_intent_verifier",
              "forge_deadzone_scan", "forge_commit_guard", "forge_quality_gate",
              "forge_code", "forge_symptom_index")


def _marqueur_cite(ligne: str) -> bool:
    """Le marqueur est-il CITE (regex, chaine de detection, legende) plutot que POSE ?"""
    return bool(_CITATION.search(ligne))


def _fichier_traqueur(rel: str) -> bool:
    """Ce fichier a-t-il pour METIER de traquer les marqueurs ? Alors il s'exclut."""
    base = rel.replace("\\", "/").rsplit("/", 1)[-1]
    return any(base.startswith(t) for t in _TRAQUEURS)


# REGISTRE D'INSTRUCTION — ce qui a ete REGARDE une fois ne se represente plus.
#
# Apres six correctifs, l'instrument reperait encore 192 lignes « ouvertes ». Un tri
# SEMANTIQUE delegue a des agents LOCAUX (109 items, deux lots disjoints) a montre que
# quatre sur cinq n'etaient pas des chantiers : des DESCRIPTIONS de mecanismes
# existants, des RECITS d'incidents passes, des DONNEES (valeurs, cles, libelles).
#
# Ces lignes ne peuvent pas etre filtrees par une regex sans effacer de vraies
# intentions : la difference est de SENS, pas de forme. On les INSTRUIT donc une fois,
# avec leur motif, sur le patron de `forge_body_regulation_audit.INSTRUITS` pour les
# zones mortes -- « ZONE_MORTE n'autorise aucune suppression : c'est un signal a
# INSTRUIRE ». Ici non plus on ne supprime rien : on cesse de re-decouvrir.
#
# LA CLEF PORTE UNE EMPREINTE DU TEXTE. Une ligne qui se DEPLACE reste instruite ; une
# ligne REECRITE redevient OUVERTE. C'est voulu : l'instruction vaut pour un texte
# precis, pas pour un emplacement, et un texte modifie merite d'etre relu.
INSTRUITS = ROOT / "docs" / "roadmap_instruits.json"
_INSTRUITS_CACHE: dict | None = None


def _instruits() -> dict:
    """{clef: categorie}, ou VIDE si le registre est illisible — jamais une exception.

    Un registre absent ne doit pas faire disparaitre l'instrument : dans ce cas tout
    redevient simplement ouvert, ce qui est bruyant mais JUSTE. L'inverse -- masquer
    des intentions parce qu'un fichier manque -- serait un faux calme.
    """
    global _INSTRUITS_CACHE
    if _INSTRUITS_CACHE is None:
        try:
            _INSTRUITS_CACHE = json.loads(INSTRUITS.read_text(encoding="utf-8")).get("entrees", {})
        except (OSError, ValueError, AttributeError):  # noqa: BLE001 — muet-ok, cf. docstring
            _INSTRUITS_CACHE = {}
    return _INSTRUITS_CACHE


def _clef_instruction(rel: str, texte: str) -> str:
    """Clef stable d'une intention : chemin normalise + empreinte du texte normalise."""
    import hashlib

    t = re.sub(r"\s+", " ", texte).strip()
    return "%s#%s" % (rel.replace("\\", "/"),
                      hashlib.sha1(t.encode("utf-8")).hexdigest()[:10])


def _scan_intent_source(path: Path, rel: str) -> list[dict]:
    if "archive" in rel.replace("\\", "/").lower():
        return []  # docs/archive/ = historique, hors registre vivant
    try:
        txt = path.read_text("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    if _fichier_traqueur(rel):
        return []       # un traqueur de marqueurs ne se compte pas lui-meme
    gel = _document_gele(txt)
    est_code = rel.lower().endswith(".py")
    out = []
    for i, ln in enumerate(txt.splitlines(), 1):
        if not _CREATE.search(ln):  # ne tracke QUE les create-intents (anti-bruit descriptif)
            continue
        if est_code and _bruit_lexical(ln):
            continue
        if _marqueur_cite(ln):
            continue
        refs = sorted({r for r in _FORGE_REF.findall(ln)})
        # Le gel de l'en-tete ne vaut que s'il PRECEDE cette intention-ci.
        gel_ici = (gel if _document_gele(txt, i) else "") or _ligne_gelee(ln)
        if not refs:
            verdict = "open"               # TODO sans module nommé
        elif any(not _module_exists(r) for r in refs):
            # Le document a-t-il DEJA instruit sa dette ? Alors c'est un GEL, pas un oubli.
            verdict = "gele" if gel_ici else "dead"
        elif gel_ici:
            # LE GEL PRIME SUR L'EXISTENCE DU FICHIER — mesure du 2026-09-18.
            #
            # `docs/specs/orchestrator_patterns_spec.md` etait classe `done?`, donc
            # « intention a clore », parce que `app/forge_orchestrator.py` existe
            # (34 595 octets, 8 importeurs). Or le document ecrit, en tete :
            #
            #     NON IMPLEMENTE — backlog (audit 2026-08-21). Aucune des 4 methodes
            #     (adversarial_verify, loop_until_dry, pipeline, completeness_critic)
            #     n'existe dans app/forge_orchestrator.py (0 def).
            #
            # VERIFIE : 0 def et 0 mention pour les trois premieres. Le document disait
            # vrai, l'instrument disait le contraire. `done?` ne prouve QUE l'existence
            # d'un fichier, jamais la realisation d'une intention -- c'est la confusion
            # « mecanisme present vs effet reel » que ce depot combat partout ailleurs.
            #
            # Clore sur ce signal fermerait des chantiers NON FAITS. Quand l'auteur a
            # pris la peine d'ecrire que ce n'est pas fait, on le croit lui, pas une
            # heuristique de nom de fichier.
            verdict = "gele"
        else:
            # `done?` = la reference EXISTE. Ce n'est PAS « c'est fait » : le point
            # d'interrogation est la pour cela, et l'instruction reste a faire.
            verdict = "done?"
        # Instruit ? Alors la ligne a DEJA ete regardee et qualifiee : on ne la
        # represente pas comme un chantier. La categorie est conservee pour que le
        # comptage reste verifiable.
        # PORTEE DU REGISTRE — corrigee le 2026-09-18, apres l'avoir payee.
        #
        # La condition etait `verdict == "open"` SEULE. Consequence mesuree : un tri
        # semantique de 26 lignes `done?` a ete mene par un agent local, 23 categories
        # ecrites au registre... et AUCUN compteur n'a bouge. Les entrees etaient sur
        # le disque (94 lues), les clefs recalculaient a l'identique, et elles restaient
        # INERTES -- parce qu'un item classe `done?` n'atteignait jamais cette ligne.
        #
        # C'est precisement « un mecanisme present dont l'effet n'existe pas », que ce
        # depot traque partout ailleurs : le registre se relisait comme une decision
        # appliquee alors qu'il ne gouvernait qu'un seau sur trois.
        #
        # `done?` entre donc dans la portee : ce verdict signifie « la reference existe »,
        # et il est PRESENTE comme un chantier (« clore l'intention »). Une ligne dont un
        # tri a etabli qu'elle n'est pas une intention -- B mecanisme, C recit, D donnee --
        # ne doit plus etre proposee a l'arbitrage : elle a DEJA ete arbitree.
        #
        # `gele` reste HORS portee, volontairement : un gel porte le motif cite depuis le
        # document lui-meme (`motif_gel`), ce qui est strictement plus informatif qu'une
        # lettre de categorie. On ne remplace pas une preuve par une etiquette.
        cat = _instruits().get(_clef_instruction(rel, ln.strip()[:160]))
        if cat and verdict in ("open", "done?"):
            out.append({"src": rel, "line": i, "text": ln.strip()[:160], "refs": refs,
                        "verdict": "instruit", "categorie": cat})
            continue
        item = {"src": rel, "line": i, "text": ln.strip()[:160], "refs": refs,
                "verdict": verdict}
        if verdict == "gele":
            item["motif_gel"] = gel_ici    # la PREUVE du gel, citee depuis le document
        out.append(item)
    return out


def verify(limit: int = 5000) -> dict:
    """AGRÈGE l'intention éparpillée (ROADMAP canon + COMMUNICATIONS.md + marqueurs code
    app/+tools/ + docs) et la CONFRONTE au code réel. Verdict/item : dead (réf forge_*
    ABSENTE = stub/oublié) / done? (réf existe = intention à clore) / open. Alimente la purge."""
    items: list[dict] = []
    for f, rel in ((CANON, "docs/ROADMAP.md"), (ROOT / "COMMUNICATIONS.md", "COMMUNICATIONS.md")):
        if f.exists():
            items += _scan_intent_source(f, rel)
    for base, pat in ((ROOT / "app", "forge_*.py"), (ROOT / "tools", "forge_*.py"),
                      (ROOT / "docs", "*.md"), (ROOT / "sandbox" / "skill_proposals", "*.md")):
        if not base.exists():
            continue
        for f in list(base.rglob(pat))[:limit]:
            sp = str(f)
            if "_attic" in sp or "node_modules" in sp or ".git" in sp:
                continue
            items += _scan_intent_source(f, str(f.relative_to(ROOT)))
    dead = [x for x in items if x["verdict"] == "dead"]
    done = [x for x in items if x["verdict"] == "done?"]
    gele = [x for x in items if x["verdict"] == "gele"]
    # LES OUVERTES SONT RENDUES, ELLES AUSSI. Elles etaient seulement COMPTEES : on
    # savait qu'il y en avait 394 et on ne pouvait pas les traiter, ce qui est la
    # definition d'un chiffre qui inquiete sans servir. Une ventilation par fichier
    # accompagne la liste, pour attaquer par famille plutot qu'au hasard.
    ouvertes = [x for x in items if x["verdict"] == "open"]
    instruits = [x for x in items if x["verdict"] == "instruit"]
    par_fichier: dict = {}
    for x in ouvertes:
        par_fichier[x["src"]] = par_fichier.get(x["src"], 0) + 1
    return {"total": len(items), "dead": dead, "done_to_close": done, "gele": gele,
            "open": ouvertes,
            "open_par_fichier": dict(sorted(par_fichier.items(),
                                            key=lambda kv: -kv[1])),
            "instruits": instruits,
            "counts": {"dead": len(dead), "done_to_close": len(done), "gele": len(gele),
                       "instruit": len(instruits), "open": len(ouvertes)},
            # La purge ne vise QUE les vrais oublis : un gel instruit n'y entre jamais.
            "purge_candidates": sorted({f"{x['src']}:{x['line']} -> {x['refs']}" for x in dead})}


# Auto-enregistrement dans le registre central des keepers (intégration portier/gate).
try:
    from nokido_agent.app.forge_keeper_base import register as _register
    _register("roadmap", owns=CONTRACT["owns"], present=present, status=status,
              regen=regen, contract=CONTRACT, source="module")
except Exception:  # noqa: BLE001 - base indispo -> keeper autonome quand même
    pass


# ── CLI ───────────────────────────────────────────────────────────────────────
def _main() -> int:
    ap = argparse.ArgumentParser(description="ROADMAP keeper — tenue + présentation")
    ap.add_argument("--regen", action="store_true", help="régénère le doc (tenue)")
    ap.add_argument("--promote", action="store_true", help="promeut la regen vers le canon")
    ap.add_argument("--finalize", action="store_true", help="promote + internalise + annonce")
    ap.add_argument("--present", nargs="?", const="terse",
                    choices=["full", "terse", "prio", "status", "delta"])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--contract", action="store_true")
    ap.add_argument("--fast", default="groq", help="provider rapide pour regen (défaut groq)")
    ap.add_argument("--ctx", default=None, help="contexte d'exécution (run_job|trusted)")
    ap.add_argument("--verify", action="store_true",
                    help="registre intent VÉRIFIÉ (dead/done/open : intention confrontée au code réel)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    try:  # console Windows = cp1252 ; le registre vérifié contient →/emoji/unicode
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    if a.selftest:
        return _selftest()
    if a.contract:
        print(json.dumps(CONTRACT, ensure_ascii=False, indent=2))
        return 0
    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if a.verify:
        print(json.dumps(verify(), ensure_ascii=False, indent=1))
        return 0
    if a.present:
        print(present(a.present))
        return 0
    if a.finalize:
        print(json.dumps(finalize(), ensure_ascii=False))
        return 0
    if a.promote:
        print(json.dumps(promote(), ensure_ascii=False))
        return 0
    # défaut (aucun arg, ex. lancé détaché en run_job) = TENUE via groq.
    r = regen(fast=a.fast, ctx=a.ctx)
    print(json.dumps(r, ensure_ascii=False))
    return int(r.get("rc", 1) or 0)


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    fixture = (
        "# ROADMAP LaForge\n\n"
        "## P0 — socle\n"
        "- ✅ canal postal LIVRÉ\n"
        "- 🔄 LMSTUDIO_TOKEN vault EN COURS\n"
        "- ⬜ nssm AppKillProcessTree RESTE\n\n"
        "## P1 — autonomie\n"
        "- ⭐ forge_gemini_autonomous_agent\n"
        "- [ ] Contract Net Protocol\n"
    )
    terse = _render(fixture, "terse")
    chk("P0" in terse and "P1" in terse, f"terse garde les priorités ({len(terse)} ch)")
    prio = _render(fixture, "prio")
    chk("### P0" in prio and "### P1" in prio, "prio regroupe par P0/P1")
    st = _status(fixture)
    chk(st["total"]["done"] >= 1 and st["total"]["wip"] >= 1 and st["total"]["open"] >= 1,
        f"status compte done/wip/open: {st['total']}")
    chk(st["by_priority"]["P0"]["done"] == 1, f"P0 done=1: {st['by_priority']['P0']}")
    chk(_render("", "terse").startswith("[roadmap vide"), "doc vide -> message clair")
    chk(set(CONTRACT["verbs"]) == {"regen", "present", "status", "contract"}
        and CONTRACT["poolable"] is False, "contrat OrganAgent bien formé")
    chk(callable(regen) and callable(present) and callable(promote), "verbes callables")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_main())
