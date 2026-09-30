#!/usr/bin/env python
"""forge_recurrence_audit.py — POURQUOI LES MEMES ERREURS REVIENNENT. Lecture seule.

MANDAT OWNER (2026-07-29)
    « Trop de problemes identiques reviennent sans cesse, il faut te corriger une
    fois pour toutes. » Ce module ne cherche PAS des incidents : il cherche des
    RECIDIVES. Un incident isole est un accident ; le meme motif trois fois est un
    defaut de methode, et c'est le seul qui merite un garde-fou.

CE QUE LA MOULINETTE MESURE
    Pour chaque MOTIF d'echec du catalogue ci-dessous :
      - occurrences dans le corpus de conversations (rag, depuis mars) ;
      - occurrences dans les memoires (une memoire = une lecon DEJA payee) ;
      - la date de la memoire qui documente le motif ;
      - **RECIDIVES = occurrences POSTERIEURES a cette memoire.**

    C'est la derniere colonne qui compte. Un motif consigne puis jamais revu est
    corrige. Un motif consigne et qui RECIDIVE prouve que la consignation ne
    suffit pas : il lui faut un garde-fou executable (hook, gate, capteur), pas
    une ligne de plus dans un fichier de notes.

    Le score de priorite est donc `recidives`, pas `total` : reparer d'abord ce
    qui resiste a sa propre lecon.

HONNETETE DU CAPTEUR (regle maison, et le motif n°1 du catalogue)
    Le compte du bac a sable ne voit PAS toujours le profil owner. Une source
    illisible est rapportee `ILLISIBLE`, JAMAIS fusionnee avec `0 occurrence` :
    « je ne peux pas voir » n'est pas « il n'y a rien ». Le rapport imprime
    toujours ce qu'il n'a pas pu lire.

USAGE
    LAFORGE_PYTHON tools/forge_recurrence_audit.py
    LAFORGE_PYTHON tools/forge_recurrence_audit.py --json
    LAFORGE_PYTHON tools/forge_recurrence_audit.py --memoires <dossier>
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/anti-recidive"

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
_PROJET = Path.home() / ".claude" / "projects" / "C--Users-user-Script-python-IA"
MEMOIRES_DEFAUT = _PROJET / "memory"
# RACINE des projets, pas UN projet (corrige le 2026-07-30). Scanner un seul
# repertoire faisait conclure « mars a mai absent du disque » alors que
# `C--Users-user-Script-python-IA-LaForge` contient des sessions d'AVRIL.
SESSIONS_DEFAUT = Path.home() / ".claude" / "projects"

# ── MESURE PRINCIPALE : LE TAUX DE RECADRAGE ──────────────────────────────
# Pourquoi celle-ci et pas le catalogue de motifs : le catalogue compte ce que
# l'agent a ECRIT sur ses erreurs (memoires) — donc il se note lui-meme, et il
# fragmente en 12 motifs ce qui est UNE racine (agir sur une lecture sans demander
# ce qu'elle ne peut pas montrer). Le seul juge non contournable est l'OWNER : le
# nombre de fois ou il doit recadrer, par session, dans le temps. Un agent qui
# progresse fait BAISSER ce taux. C'est la seule metrique qui puisse contredire
# l'agent qui la calcule — donc la seule qui vaille.
# BIAIS ASSUME (mesure 2026-07-30) : ce lexique a ete recolte dans les sessions
# RECENTES, donc il sous-detecte mecaniquement le passe — un detecteur calibre sur
# le present fabrique une degradation. C'est pourquoi la metrique de reference est
# `repetitions` plus bas, qui ne depend d'AUCUN mot choisi par l'agent.
# `arrete` exige une negation absente : « ne t'arrete pas » est une INSTRUCTION,
# pas un reproche, et il comptait a tort (faux positif vu dans la sortie du 29-07).
MARQUEURS: dict[str, list[str]] = {
    "recadrage": [
        "n'importe quoi", "n importe quoi", "tu racontes", "c'est faux", "c est faux",
        "tu te trompes", "je t'ai dit", "je t ai dit",
        "combien de fois", "tu as tort", "faux !", "mais non",
    ],
    "repetition": [
        "toujours pas", "tjrs pas", "encore une fois", "comme d'habitude",
        "commence a bien faire", "commence à bien faire", "de pire en pire",
        "recurrent", "récurrent", "a nouveau", "à nouveau", "systematiquement",
        "systématiquement", "chaque fois",
    ],
    "doute_impose": [
        "verifie", "vérifie", "tu es sur", "tu es sûr", "prouve", "mesure d'abord",
        "es tu sur", "es-tu sûr", "vraiment ?",
    ],
}

# ── CATALOGUE DES MOTIFS ──────────────────────────────────────────────────
# Chaque entree vient d'incidents REELS, pas d'une taxonomie theorique.
# `termes` sert au FTS5 (OR de phrases) ; `regex` affine sur le texte des memoires.
MOTIFS: list[dict] = [
    {
        "cle": "invisible_lu_comme_absent",
        "titre": "« je ne peux pas voir » lu comme « ca n'existe pas »",
        "termes": ["cmdline", "acces refuse", "je ne peux pas voir", "illisible",
                   "introuvable depuis", "silence"],
        "regex": r"(?i)ne peux pas voir|acc[eè]s refus|cmdline inaccessible|"
                 r"lu comme (?:un )?(?:succ[eè]s|absence)|0 fichier|scanner qui",
        "garde": "tri-etat obligatoire : vrai / faux / illisible",
    },
    {
        "cle": "statut_declare_vs_reel",
        "titre": "un statut DECLARE pris pour la realite",
        "termes": ["pid mort", "already_running", "job_status", "stale",
                   "registre", "uptime"],
        "regex": r"(?i)pid (?:stale|mort|perim)|already[_ ]running|status.{0,12}running|"
                 r"registre ment|le disque dit vrai|d[eé]clar[eé].{0,20}r[eé]el",
        "garde": "croiser le registre avec le reel (tasklist / listener / heartbeat)",
    },
    {
        "cle": "sonde_ponctuelle_fait_temporel",
        "titre": "un fait TEMPOREL refute par une lecture a l'instant t",
        "termes": ["intermittence", "chronique", "log de l organe", "instantane",
                   "oscille"],
        "regex": r"(?i)sonde.{0,30}preuve|LOG (?:de l'organe|l'est)|lecture unique|"
                 r"instant t|oscill",
        "garde": "sonde de meme DIMENSION que l'affirmation ; le LOG avant la sonde",
    },
    {
        "cle": "capteur_neuf_pris_pour_temoin",
        "titre": "la sortie d'un capteur qu'on vient d'ecrire prise pour verite",
        "termes": ["capteur neuf", "faux positif", "auto empoisonnement",
                   "sa propre sortie"],
        "regex": r"(?i)capteur neuf|faux positif|sa propre (?:sortie|trace)|"
                 r"auto[- ]empoisonn",
        "garde": "capteur neuf = SUSPECT : croiser avec le journal de l'organe",
    },
    {
        "cle": "seuil_invente",
        "titre": "un seuil INVENTE alors que le systeme declarait l'attendu",
        "termes": ["seuil", "heartbeat_tier", "attendu", "calibrage", "moyenne"],
        "regex": r"(?i)seuil (?:invent|arbitraire|fixe)|attendu (?:d[eé]clar|appris)|"
                 r"heartbeat_tier|calibr",
        "garde": "lire l'attendu DANS le systeme (config/tier/interval) avant de juger",
    },
    {
        "cle": "wrapper_vs_enfant",
        "titre": "le pid du LANCEUR pris pour celui du worker",
        "termes": ["wrapper", "launcher", "runAs", "enfant", "ppid"],
        "regex": r"(?i)wrapper|launcher|runAs=interactive|remonter l'arbre|enfant bind",
        "garde": "remonter/descendre l'arbre des process avant d'accuser",
    },
    {
        "cle": "mauvaise_cible_ecriture",
        "titre": "ecrire au bon format mais dans la MAUVAISE cible",
        "termes": ["rag_fts", "rag_chunks_fts", "mauvaise table", "chemin",
                   "trigger"],
        "regex": r"(?i)mauvaise (?:table|cible|voie)|rag_fts|contenu externe|"
                 r"sans trigger|n'indexe rien",
        "garde": "verifier par une LECTURE via le chemin de consommation reel",
    },
    {
        "cle": "borne_trop_serree",
        "titre": "une borne/limite qui EFFACE la mesure au lieu de la borner",
        "termes": ["timeout", "borne", "limite", "tronque", "cap"],
        "regex": r"(?i)borne trop|timeout.{0,20}(?:trop|systematique)|"
                 r"lent.{0,15}jamais|tronqu|silencieusement",
        "garde": "une borne doit dire COMBIEN, pas seulement TROP",
    },
    {
        "cle": "chemin_erreur_muet",
        "titre": "un chemin d'erreur MUET rend le defaut indiagnosticable",
        "termes": ["except pass", "muet", "zone morte", "silencieux", "avale"],
        "regex": r"(?i)except\s*(?:Exception)?\s*:\s*pass|muet|silencieu|zone morte|"
                 r"aval[eé] en silence",
        "garde": "aucun chemin d'erreur sans trace ; journaliser AVANT d'optimiser",
    },
    {
        "cle": "reinvente_ce_qui_existe",
        "titre": "recoder une primitive qui existait deja",
        "termes": ["anti-dup", "existait deja", "reinvent", "deja en place",
                   "personne ne l utilisait"],
        "regex": r"(?i)anti-?dup|existait d[eé]j[aà]|r[eé]invent|d[eé]j[aà] en place|"
                 r"personne ne l'utilisait|primitive",
        "garde": "rag_fts + memoire + module existant AVANT toute creation",
    },
    {
        "cle": "declare_non_livre",
        "titre": "declare fait, pas reellement livre",
        "termes": ["commit local", "push", "pending", "drain", "depose"],
        "regex": r"(?i)commit local|angle mort.{0,15}push|reste pending|"
                 r"v[eé]rifier le drain|d[eé]clar[eé].{0,20}pas livr",
        "garde": "mesurer l'effet, jamais l'intention (push, drain, reload)",
    },
    {
        "cle": "cause_commune_vs_chemin",
        "titre": "corriger le chemin au lieu de l'EFFET commun",
        "termes": ["meme panne", "autre chemin", "effet commun", "recidive"],
        "regex": r"(?i)m[eê]me panne|autre chemin|effet commun|3[×x] en un jour|"
                 r"r[eé]cidiv",
        "garde": "3e occurrence par un 3e chemin => corriger l'effet, pas le chemin",
    },
]

DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _fts_query(termes: list[str]) -> str:
    return " OR ".join('"%s"' % t.replace('"', "") for t in termes)


def scan_corpus(conn: sqlite3.Connection) -> dict:
    """Occurrences par motif dans les transcripts de conversation (via rag_fts)."""
    out = {}
    for motif in MOTIFS:
        try:
            rows = conn.execute(
                "SELECT c.created_at, c.ingested_at FROM rag_fts f "
                "JOIN rag_chunks c ON c.id = f.chunk_id "
                # Union de deux GLOB, et non `GLOB 'conv_*'` seul : en LIKE, '_' est un
                # JOKER, si bien que `LIKE 'conv_%'` attrape aussi les 9 sources
                # `conv://...` (mesure 2026-09-04 : 47796 = 47787 + 9). Un GLOB unique
                # les aurait perdues en silence -- ce sont des conversations de proxy
                # et de research_agent, exactement la matiere de cet audit.
                "WHERE f.rag_fts MATCH ? AND (c.source GLOB 'conv_*' OR c.source GLOB 'conv:*') LIMIT 4000",
                (_fts_query(motif["termes"]),),
            ).fetchall()
        except Exception as e:  # FTS indisponible != 0 occurrence
            out[motif["cle"]] = {"etat": "ILLISIBLE", "raison": str(e)[:100]}
            continue
        dates = []
        for created, ingested in rows:
            m = DATE_RE.search(str(created or ingested or ""))
            if m:
                dates.append(m.group(0))
        out[motif["cle"]] = {
            "etat": "ok",
            "occurrences": len(rows),
            "premiere": min(dates) if dates else None,
            "derniere": max(dates) if dates else None,
        }
    return out


def scan_memoires(dossier: Path) -> dict:
    """Occurrences par motif dans les memoires = lecons DEJA payees, avec leur date."""
    if not dossier.exists():
        return {"__etat__": "ILLISIBLE", "__raison__": f"dossier absent/interdit: {dossier}"}
    fichiers = sorted(dossier.glob("*.md"))
    if not fichiers:
        return {"__etat__": "ILLISIBLE", "__raison__": f"aucun .md lisible dans {dossier}"}
    textes = {}
    for f in fichiers:
        try:
            textes[f.name] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    if not textes:
        return {"__etat__": "ILLISIBLE", "__raison__": "lecture refusee sur tous les .md"}
    res: dict = {"__etat__": "ok", "__n_fichiers__": len(textes)}
    for motif in MOTIFS:
        rx = re.compile(motif["regex"])
        touches = []
        for nom, txt in textes.items():
            if rx.search(txt):
                m = DATE_RE.search(nom) or DATE_RE.search(txt[:400])
                touches.append({"memoire": nom, "date": m.group(0) if m else None})
        dates = sorted(t["date"] for t in touches if t["date"])
        res[motif["cle"]] = {
            "memoires": len(touches),
            "premiere_consignation": dates[0] if dates else None,
            "derniere_consignation": dates[-1] if dates else None,
            "mois_distincts": sorted({d[:7] for d in dates}),
            "fichiers": [t["memoire"] for t in touches[:6]],
        }
    return res


def croiser(corpus: dict, memoires: dict) -> list[dict]:
    """RECIDIVE = le motif reapparait APRES la memoire qui le documente."""
    """RECIDIVE = le motif a ete consigne PLUSIEURS FOIS, a des dates differentes.

    La chronologie vient des MEMOIRES, pas du corpus. Mesure du 2026-07-29 : les
    chunks `conv_*` portent tous la meme date (2026-07-04) — c'est la date
    d'INGESTION des transcripts, pas celle des evenements. Comparer une date
    d'ingestion a une date de consignation declarait « recidive » pour presque
    tout : un artefact, pas une mesure. Une memoire, elle, est datee du jour ou
    l'erreur a ete PAYEE : deux memoires du meme motif a deux mois differents
    prouvent que la premiere lecon n'a pas tenu. Le corpus ne sert plus qu'a
    classer la SALIENCE (mentions), ce qui n'est pas un compte d'incidents.
    """
    lignes = []
    for motif in MOTIFS:
        c = corpus.get(motif["cle"], {})
        m = memoires.get(motif["cle"], {}) if memoires.get("__etat__") == "ok" else {}
        premiere, derniere = m.get("premiere_consignation"), m.get("derniere_consignation")
        mois = m.get("mois_distincts") or []
        recidive = bool(premiere and derniere and derniere > premiere and len(mois) >= 2)
        lignes.append({
            "cle": motif["cle"],
            "titre": motif["titre"],
            "garde_attendu": motif["garde"],
            "salience_corpus": (c.get("occurrences") if c.get("etat") == "ok"
                                else c.get("etat")),
            "memoires": m.get("memoires"),
            "premiere_lecon": premiere,
            "derniere_lecon": derniere,
            "mois_touches": len(mois),
            "RECIDIVE": recidive,
            "fichiers_memoire": m.get("fichiers", []),
        })
    # priorite : recidive, puis etalement dans le temps, puis volume de lecons
    lignes.sort(key=lambda x: (not x["RECIDIVE"], -x["mois_touches"],
                               -(x["memoires"] or 0)))
    return lignes


# Artefact depose par `forge_directive_audit` au SessionStart, c'est-a-dire du cote
# ou les transcripts SONT lisibles. Cet audit-ci tourne sous le compte du hub, qui
# n'y a pas acces : le refus est CORRECT et ne doit pas etre contourne en forcant
# des droits. Mais « je n'ai pas pu voir » peut au moins dire OU quelqu'un a vu.
ARTEFACT_VOLUMETRIE = Path(__file__).resolve().parents[1] / "sandbox" / "persona_directives.json"


def _illisible_avec_suppleant(raison: str) -> dict:
    """ILLISIBLE, plus la volumetrie si un suppleant l'a deposee — et rien de plus.

    PRECAUTION QUI FAIT TOUT L'INTERET DE CETTE FONCTION : l'artefact porte le
    DENOMINATEUR (evenements par session), il ne porte NI les recadrages NI les
    motifs. On expose donc le volume et on laisse le taux de recadrage explicitement
    NON MESURE. Servir un suppleant partiel comme s'il repondait a la question
    d'origine serait pire que le refus : ce depot appelle cela un faux calme.
    """
    out = {"etat": "ILLISIBLE", "raison": raison,
           "taux_recadrage": "NON MESURE — le suppleant ne porte pas cette grandeur"}
    try:
        charge = json.loads(ARTEFACT_VOLUMETRIE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # noqa: BLE001
        out["suppleant"] = {"etat": "ABSENT", "raison": type(exc).__name__,
                            "attendu": str(ARTEFACT_VOLUMETRIE)}
        return out
    vol = charge.get("volumetrie")
    if not isinstance(vol, list) or not vol:
        out["suppleant"] = {"etat": "SANS_VOLUMETRIE",
                            "raison": "artefact present mais sans le champ `volumetrie` — "
                                      "depose par une version anterieure de "
                                      "forge_directive_audit ; il sera rempli au "
                                      "prochain demarrage de session",
                            "genere_ts": charge.get("genere_ts")}
        return out
    out["suppleant"] = {
        "etat": "ok", "source": str(ARTEFACT_VOLUMETRIE),
        # L'AGE est expose : une volumetrie dont on ignore la fraicheur se lit
        # comme une mesure de l'instant.
        "genere_ts": charge.get("genere_ts"),
        "age_s": (round(time.time() - float(charge["genere_ts"]))
                  if charge.get("genere_ts") else None),
        "n_sessions": len(vol),
        "volumetrie": vol,
    }
    return out


def scan_sessions(dossier: Path) -> dict:
    """Taux de recadrage owner par session, en ORDRE CHRONOLOGIQUE reel.

    Source : les transcripts `*.jsonl`, qui portent de vraies dates — contrairement
    aux chunks `conv_*` du RAG, tous estampilles a la date d'INGESTION (piege paye
    le 2026-07-29 : le premier verdict de cet outil etait un artefact).

    Ne lit QUE les messages de l'owner, ligne a ligne (un transcript pese des Mo).
    """
    if not dossier.exists():
        return _illisible_avec_suppleant(f"dossier absent/interdit: {dossier}")
    # Racine des projets OU projet unique ; `*/*.jsonl` ne ramasse pas les
    # `*/subagents/*.jsonl`, qui ne sont pas des conversations owner.
    fichiers = sorted(set(dossier.glob("*.jsonl")) | set(dossier.glob("*/*.jsonl")))
    if not fichiers:
        return _illisible_avec_suppleant(f"aucun .jsonl sous {dossier}")

    sessions = []
    for f in fichiers:
        n_owner, hits, extraits = 0, {k: 0 for k in MARQUEURS}, []
        # AH1 : attribution du MOTIF a la session qui le porte, dans la meme
        # passe. Sans cet axe (motif x date), « recidive » n'est pas calculable :
        # on ne sait que COMBIEN de recadrages, jamais LEQUEL revient.
        motifs_vus: dict[str, int] = {}
        premier_ts = None
        textes_owner: list[str] = []
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                for ligne in fh:
                    if '"user"' not in ligne:
                        continue
                    try:
                        ev = json.loads(ligne)
                    except Exception:
                        continue
                    if ev.get("type") != "user":
                        continue
                    ts = str(ev.get("timestamp") or "")
                    if ts and premier_ts is None:
                        premier_ts = ts
                    msg = ev.get("message") or {}
                    contenu = msg.get("content")
                    if isinstance(contenu, list):
                        # Les RESULTATS D'OUTIL arrivent aussi en type "user". Les
                        # compter gonflerait le denominateur et ferait paraitre le
                        # taux minuscule — l'agent se fabriquerait un bon score.
                        # Seuls les blocs de texte reellement tapes comptent.
                        if any(isinstance(b, dict) and b.get("type") == "tool_result"
                               for b in contenu):
                            continue
                        txt = " ".join(
                            str(b.get("text", "")) for b in contenu
                            if isinstance(b, dict) and b.get("type") in (None, "text")
                        )
                    else:
                        txt = str(contenu or "")
                    if not txt.strip() or "<system-reminder>" in txt[:200]:
                        continue
                    if ev.get("isMeta") or txt.lstrip().startswith("<"):
                        continue
                    n_owner += 1
                    textes_owner.append(txt.strip())
                    bas = txt.lower()
                    for cat, mots in MARQUEURS.items():
                        if any(m in bas for m in mots):
                            hits[cat] += 1
                            if cat != "doute_impose" and len(extraits) < 3:
                                extraits.append(txt.strip()[:90])
                    for _cle, _re_motif in _motifs_compiles()[0]:
                        if _re_motif.search(txt):
                            motifs_vus[_cle] = motifs_vus.get(_cle, 0) + 1
        except OSError as e:
            sessions.append({"session": f.stem[:8], "etat": "ILLISIBLE",
                             "raison": str(e)[:60]})
            continue
        if n_owner < 5:  # session trop courte : un ratio n'y a pas de sens
            continue
        # ── INDICATEUR DE REFERENCE, SANS LEXIQUE ────────────────────────
        # « je te dis quelque chose, EXECUTE » : quand l'owner doit REDIRE la meme
        # consigne, c'est que le premier passage n'a pas abouti. Aucun mot choisi
        # par l'agent n'intervient, donc aucun biais de vocabulaire possible.
        import difflib
        repets = 0
        longs = [t for t in textes_owner if len(t) >= 25]
        for i in range(1, len(longs)):
            for j in range(max(0, i - 6), i):
                if difflib.SequenceMatcher(None, longs[i][:400].lower(),
                                           longs[j][:400].lower()).ratio() >= 0.80:
                    repets += 1
                    break
        m = DATE_RE.search(premier_ts or "") or DATE_RE.search(
            __import__("time").strftime("%Y-%m-%d", __import__("time").localtime(f.stat().st_mtime))
        )
        recadrages = hits["recadrage"] + hits["repetition"]
        sessions.append({
            "session": f.stem[:8],
            "date": m.group(0) if m else None,
            "messages_owner": n_owner,
            "recadrages": recadrages,
            "dont_repetition": hits["repetition"],
            "doute_impose": hits["doute_impose"],
            "consignes_redites": repets,
            "messages_eligibles": len(longs),
            "motifs": motifs_vus,
            "taux_pct": round(100.0 * recadrages / n_owner, 1),
            "taux_redites_pct": round(100.0 * repets / max(1, len(longs)), 1),
            "extraits": extraits,
        })
    sessions = [s for s in sessions if s.get("date")]
    sessions.sort(key=lambda s: s["date"])
    return {"etat": "ok", "n_sessions": len(sessions), "sessions": sessions}


# ── AH1 (2026-09-12) : la RECIDIVE, par motif ────────────────────────────────
# `tendance()` agrege TOUS les recadrages : un motif eteint et un motif qui
# explose se compensent exactement dans le total. Le catalogue MOTIFS existait
# depuis le debut, ses regex aussi — rien ne les appliquait a l'axe du TEMPS.
#
# Les quatre etats ci-dessous ne sont pas des nuances de style : ils appellent
# des remedes differents. Une RECIDIVE dit qu'on a cru le defaut mort (donc que
# la remediation n'a pas tenu) ; un CHRONIQUE dit qu'on ne l'a jamais traite.

_MOTIFS_RE = None


def _motifs_compiles():
    """Compile une fois les regex du catalogue. Un motif dont la regex est
    invalide est NOMME et ecarte — jamais avale, sinon sa disparition se lirait
    comme une guerison."""
    global _MOTIFS_RE
    if _MOTIFS_RE is None:
        ok, casses = [], []
        for m in MOTIFS:
            try:
                ok.append((m["cle"], re.compile(m["regex"])))
            except re.error as exc:
                casses.append({"cle": m.get("cle"), "motif": str(exc)[:80]})
        _MOTIFS_RE = (ok, casses)
    return _MOTIFS_RE


def recidive(sessions: list[dict]) -> dict:
    """Par motif : revient-il APRES un silence, ou n'a-t-il jamais cesse ?

    RECIDIVE    : reapparu apres >= 2 mois observes sans lui. On l'a cru mort.
    CHRONIQUE   : present sur tous les mois observes. Dette jamais traitee.
    ETEINT      : vu, puis absent des 2 derniers mois observes. Pas « resolu » :
                  on constate une absence, on n'en connait pas la cause.
    INTERMITTENT: vu par intervalles, sans silence assez long pour trancher.
    VU_UNE_FOIS : une seule occurrence — un point ne fait pas une serie.
    JAMAIS_VU   : absent des donnees. ⚠️ Ce n'est PAS un motif corrige : un
                  detecteur muet rend exactement la meme chose.
    INDETERMINE : moins de deux mois observes — aucune tendance calculable.
    """
    mois_observes = sorted({s["date"][:7] for s in sessions if s.get("date")})
    _, casses = _motifs_compiles()
    # ⚠️ L'AXE DU TEMPS N'EST PAS CONTINU. Mesure du 2026-09-12 : 45 sessions
    # reparties sur juin, aout et septembre — JUILLET est vide. Le silence se
    # compte donc en mois OBSERVES, jamais en mois calendaires : sans cela, un
    # mois ou personne n'a travaille se lirait comme un mois sans defaut.
    # `UNKNOWN != NO`, applique a l'axe du temps.
    mois_sans_donnees = []
    if mois_observes:
        a, b = mois_observes[0], mois_observes[-1]
        an, mo = int(a[:4]), int(a[5:7])
        while "%04d-%02d" % (an, mo) <= b:
            cle = "%04d-%02d" % (an, mo)
            if cle not in mois_observes:
                mois_sans_donnees.append(cle)
            mo += 1
            if mo > 12:
                an, mo = an + 1, 1
    par_motif = []
    for m in MOTIFS:
        cle = m["cle"]
        mois_vus = sorted({s["date"][:7] for s in sessions
                           if s.get("date") and (s.get("motifs") or {}).get(cle)})
        total = sum((s.get("motifs") or {}).get(cle, 0) for s in sessions)
        if not mois_vus:
            etat, silence = "JAMAIS_VU", None
        elif total <= 1:
            etat, silence = "VU_UNE_FOIS", None
        elif len(mois_observes) < 2:
            etat, silence = "INDETERMINE", None
        else:
            dernier = mois_vus[-1]
            i_dernier = mois_observes.index(dernier)
            precedents = [x for x in mois_vus if x < dernier]
            i_prec = mois_observes.index(precedents[-1]) if precedents else -1
            silence = i_dernier - i_prec - 1
            apres = mois_observes[i_dernier + 1:]
            if silence >= 2:
                etat = "RECIDIVE"
            elif len(mois_vus) == len(mois_observes):
                etat = "CHRONIQUE"
            elif len(apres) >= 2:
                etat = "ETEINT"
            else:
                etat = "INTERMITTENT"
        par_motif.append({
            "cle": cle, "titre": m.get("titre"), "garde": m.get("garde"),
            "etat": etat, "occurrences": total,
            "mois_vus": mois_vus, "dernier_mois": mois_vus[-1] if mois_vus else None,
            "mois_de_silence": silence,
        })
    ordre = {"RECIDIVE": 0, "CHRONIQUE": 1, "INTERMITTENT": 2, "ETEINT": 3,
             "VU_UNE_FOIS": 4, "INDETERMINE": 5, "JAMAIS_VU": 6}
    par_motif.sort(key=lambda x: (ordre.get(x["etat"], 9), -x["occurrences"]))
    return {
        "mois_observes": mois_observes,
        "mois_sans_donnees": mois_sans_donnees,
        "motifs": par_motif,
        "motifs_ILLISIBLES": casses,
        "rappel": "JAMAIS_VU ne veut pas dire corrige : un detecteur muet rend "
                  "la meme chose. Classer par liste BLANCHE.",
    }


def _mois_complet(mois: str) -> bool:
    """Le mois est-il termine ? Un mois EN COURS compare a des mois pleins sans
    le dire, c'est comparer deux choses qui ne se comparent pas."""
    import datetime as _dt

    return mois < _dt.date.today().strftime("%Y-%m")


def tendance(sessions: list[dict]) -> dict:
    """Le taux BAISSE-t-il ? PENTE sur tous les mois complets, pas deux points."""
    par_mois: dict[str, list[dict]] = {}
    for s in sessions:
        par_mois.setdefault(s["date"][:7], []).append(s)
    lignes = []
    for mois in sorted(par_mois):
        grp = par_mois[mois]
        msg = sum(s["messages_owner"] for s in grp)
        rec = sum(s["recadrages"] for s in grp)
        red = sum(s["consignes_redites"] for s in grp)
        # DENOMINATEUR DERIVE, PAS CHOISI (defaut corrige le 2026-07-30) : les
        # redites se comptent sur les messages ELIGIBLES (>=25 car.), pas sur tous.
        # Divise par le total, un mois riche en « go » / « ok » voyait son taux
        # baisser MECANIQUEMENT — et ce biais flattait l'agent. Par session le bon
        # denominateur etait deja utilise ; l'incoherence n'existait qu'a l'agregat.
        elig = sum(s["messages_eligibles"] for s in grp)
        lignes.append({
            "mois": mois, "sessions": len(grp), "messages_owner": msg,
            "messages_eligibles": elig,
            # AH1 : le dernier mois est presque toujours PARTIEL. Il reste
            # affiche — le masquer serait pire — mais il sort du verdict, et
            # son incompletude est DITE au lieu d'etre supposee connue.
            "mois_complet": _mois_complet(mois),
            "recadrages": rec, "consignes_redites": red,
            "taux_pct": round(100.0 * rec / msg, 1) if msg else None,
            "taux_redites_pct": round(100.0 * red / elig, 1) if elig else None,
        })

    # AH1 : PENTE des moindres carres sur tous les mois complets, au lieu du
    # premier contre le dernier. Sur N mois de donnees, l'ancien verdict en
    # ignorait N-2 — meme famille que « la moyenne all-time ment sur les
    # rafales », en plus brutal.
    retenus = [l for l in lignes if l["mois_complet"] and l["taux_pct"] is not None]
    verdict = None
    if len(retenus) >= 3:
        n = len(retenus)
        xs = list(range(n))
        ys = [l["taux_pct"] for l in retenus]
        mx = sum(xs) / n
        my = sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        pente = (sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
                 if denom else 0.0)
        verdict = {
            "mois_retenus": n,
            "premier_mois": retenus[0]["mois"], "taux_debut": retenus[0]["taux_pct"],
            "dernier_mois": retenus[-1]["mois"], "taux_fin": retenus[-1]["taux_pct"],
            "pente_points_par_mois": round(pente, 2),
            "sens": ("EMPIRE" if pente > 0.3
                     else ("AMELIORE" if pente < -0.3 else "STABLE")),
            "mois_exclus_car_partiels": [l["mois"] for l in lignes
                                         if not l["mois_complet"]],
        }
    elif lignes:
        verdict = {
            "mois_retenus": len(retenus),
            "sens": "INDETERMINE",
            "raison": "moins de 3 mois COMPLETS : une pente n'y aurait pas de sens",
            "mois_exclus_car_partiels": [l["mois"] for l in lignes
                                         if not l["mois_complet"]],
        }
    return {"par_mois": lignes, "verdict": verdict}


def collect(dossier_memoires: Path) -> dict:
    if not DB.exists():
        corpus = {m["cle"]: {"etat": "ILLISIBLE", "raison": f"DB absente: {DB}"}
                  for m in MOTIFS}
    else:
        conn = sqlite3.connect(f"file:{str(DB).replace(chr(92), '/')}?mode=ro", uri=True)
        corpus = scan_corpus(conn)
        conn.close()
    memoires = scan_memoires(dossier_memoires)
    illisible = [k for k, v in corpus.items()
                 if isinstance(v, dict) and v.get("etat") == "ILLISIBLE"]
    return {
        "motifs": croiser(corpus, memoires),
        "sources_illisibles": {
            "corpus": illisible,
            "memoires": (memoires.get("__raison__")
                         if memoires.get("__etat__") == "ILLISIBLE" else None),
        },
        "n_memoires_lues": memoires.get("__n_fichiers__"),
    }


def main() -> int:
    # Console Windows en cp1252 : un seul caractere hors table tuait le rapport
    # ENTIER, et il est tombe pile sur la section « ce que je n'ai pas pu lire ».
    # Un outil de diagnostic ne meurt pas sur son propre affichage.
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--memoires", default=str(MEMOIRES_DEFAUT))
    ap.add_argument("--sessions", default=str(SESSIONS_DEFAUT))
    ap.add_argument("--motifs", action="store_true",
                    help="affiche aussi le catalogue de motifs (mesure SECONDAIRE)")
    args = ap.parse_args()

    # ── MESURE PRINCIPALE ────────────────────────────────────────────────
    sess = scan_sessions(Path(args.sessions))
    print("=== TAUX DE RECADRAGE OWNER (la seule metrique qui peut me contredire) ===")
    if sess.get("etat") != "ok":
        print(f"  ILLISIBLE : {sess.get('raison')}")
    else:
        t = tendance(sess["sessions"])
        print("  %-9s %8s %9s %8s %10s %6s %8s %6s %s" % (
            "mois", "sessions", "msg owner", "elig.", "recadrages", "taux",
            "redites", "taux", "etat"))
        for l in t["par_mois"]:
            print("  %-9s %8d %9d %8d %10d %5s%% %8d %5s%% %s" % (
                l["mois"], l["sessions"], l["messages_owner"],
                l["messages_eligibles"], l["recadrages"], l["taux_pct"],
                l["consignes_redites"], l["taux_redites_pct"],
                "" if l["mois_complet"] else "MOIS EN COURS (hors verdict)"))
        v = t["verdict"]
        if v and v.get("sens") == "INDETERMINE":
            print(f"\n  VERDICT : INDETERMINE — {v.get('raison')}")
        elif v:
            print(f"\n  VERDICT (lexical, BIAISE vers la degradation) : {v['sens']}  "
                  f"pente {v['pente_points_par_mois']:+} point/mois sur "
                  f"{v['mois_retenus']} mois COMPLETS "
                  f"({v['premier_mois']} {v['taux_debut']}%  ->  "
                  f"{v['dernier_mois']} {v['taux_fin']}%)")
            if v.get("mois_exclus_car_partiels"):
                print(f"  mois ecartes car non termines : "
                      f"{', '.join(v['mois_exclus_car_partiels'])}")
        print("  Ne conclure QUE si la colonne `redites` bouge dans le meme sens :")
        print("  elle ne depend d'aucun mot choisi par l'agent, donc elle n'est pas")
        print("  biaisable par le lexique. Divergence des deux = lexique en cause.")
        pires = sorted(sess["sessions"], key=lambda s: -s["taux_pct"])[:5]
        print("\n  sessions les plus recadrees :")
        for s in pires:
            print(f"    {s['date']} {s['session']}  {s['taux_pct']}% "
                  f"({s['recadrages']}/{s['messages_owner']})")
            for e in s["extraits"][:2]:
                print(f"       « {e} »")
        print(f"\n  {sess['n_sessions']} sessions retenues (>=5 messages owner)")

        # ── AH1 : LA RECIDIVE, PAR MOTIF ─────────────────────────────────
        # L'agregat ci-dessus annule les mouvements opposes : un motif eteint
        # et un motif qui explose s'y compensent. Ici chaque motif porte son
        # propre verdict, et un RECIDIVE dit ce que le total ne dit jamais —
        # la remediation n'a pas tenu.
        r = recidive(sess["sessions"])
        print("\n=== RECIDIVE PAR MOTIF (sur %d mois observes) ===" % len(r["mois_observes"]))
        if r["mois_sans_donnees"]:
            print("  ⚠ axe du temps NON CONTINU — aucune session en %s. Le silence "
                  "est compte en mois OBSERVES : un mois sans donnee n'est pas un "
                  "mois sans defaut." % ", ".join(r["mois_sans_donnees"]))
        for m in r["motifs"]:
            if m["etat"] in ("JAMAIS_VU",):
                continue
            sil = "" if m["mois_de_silence"] in (None, 0) else \
                  "  apres %d mois de silence" % m["mois_de_silence"]
            print("  %-12s %-34s x%-4d dernier=%s%s"
                  % (m["etat"], m["cle"], m["occurrences"],
                     m["dernier_mois"] or "-", sil))
            if m["etat"] == "RECIDIVE":
                print("        GARDE ATTENDU : %s" % m["garde"])
        jamais = [m["cle"] for m in r["motifs"] if m["etat"] == "JAMAIS_VU"]
        if jamais:
            print("\n  JAMAIS_VU (%d) — ⚠ PAS 'corrige' : un detecteur muet rend "
                  "exactement la meme chose :" % len(jamais))
            print("    " + ", ".join(jamais))
        if r["motifs_ILLISIBLES"]:
            print("\n  motifs ECARTES car regex invalide : %s" % r["motifs_ILLISIBLES"])

    if not args.motifs:
        print("\n(catalogue de motifs : --motifs ; c'est une mesure SECONDAIRE,")
        print(" elle compte ce que j'ai ECRIT sur mes erreurs, donc je m'y note moi-meme)")
        return 0

    rapport = collect(Path(args.memoires))
    rapport["recadrage"] = sess
    if args.json:
        print(json.dumps(rapport, indent=1, ensure_ascii=False))
        return 0

    ill = rapport["sources_illisibles"]
    print("=== RECIDIVES : lecon consignee PLUSIEURS FOIS a des dates differentes ===")
    print("    (chronologie = dates des memoires ; le corpus ne donne que la salience)")
    recidives = [m for m in rapport["motifs"] if m["RECIDIVE"]]
    if not recidives:
        print("  aucune — ou une source est illisible, voir plus bas")
    for m in recidives:
        print(f"\n  [{m['cle']}] {m['titre']}")
        print(f"     re-consigne {m['memoires']}x sur {m['mois_touches']} mois "
              f"({m['premiere_lecon']} -> {m['derniere_lecon']})")
        print(f"     salience corpus : {m['salience_corpus']} mentions")
        print(f"     GARDE ATTENDU : {m['garde_attendu']}")

    print("\n=== motifs consignes une seule fois (lecon tenue, ou trop recente) ===")
    for m in rapport["motifs"]:
        if not m["RECIDIVE"]:
            print(f"  {m['cle']:<34} memoires={m['memoires']} "
                  f"mois={m['mois_touches']} salience={m['salience_corpus']}")

    print("\n=== CE QUE JE N'AI PAS PU LIRE (n'est PAS 'rien trouve') ===")
    print(f"  memoires: {ill['memoires'] or 'ok (%s fichiers)' % rapport['n_memoires_lues']}")
    print(f"  corpus  : {ill['corpus'] or 'ok'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
