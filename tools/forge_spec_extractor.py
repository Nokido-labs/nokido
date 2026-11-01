"""forge_spec_extractor.py — retro-specification FACTUELLE de Nokido (docs/specs/), du code mesure vers la cible.

Owner 26/10 : Schema / TRD / PRD / Plan rediges APRES lancement doivent sortir du code, pas de la memoire d'un
agent -- un document ecrit a la main se perime au commit suivant, et un collage externe en a affirme une dizaine
de faux le jour meme (Ollama absent, juge en worktree, verdict SURVIT_AVEC_GAIN, 28 outils...). Ce module COMPOSE
les sources canoniques ; il n'en recode aucune :
  - schema MCP   : tests/schemas_mcp_structure.json (instantane fige par la CI) + bareme forge_tools(min_ring,
                   is_active), lu la ou le registre le lit (_get_ring_needed) ;
  - bases        : forge_db_path (db_path, tasks_path, m2m_path, authority_path, journaux) ouvertes en mode=ro,
                   sqlite_master SEUL -- jamais de balayage de rag_chunks (interdit owner 24/10) ;
  - constantes   : lues par AST dans leur module (aucun import du hub) ;
  - verdicts     : litteraux du juge (forge_mutation_judge) ;
  - roadmap      : docs/roadmap_arbre.json (forge_roadmap_keeper --arbre).
Trois etats, jamais deux : une source illisible est DITE (ILLISIBLE / ABSENTE), jamais omise ni remplacee.

Usage : trusted_script tools/forge_spec_extractor.py [--ecrire]   (sans --ecrire : resume, rien n'est ecrit)
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/retro-specification"

import argparse
import ast
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (module, constante, role) -- la valeur et la ligne sont LUES, jamais recopiees ici.
CONSTANTES = [
    ("app/forge_lane_admission.py", "MAX_RAM_PCT", "seuil RAM d'admission des jobs (%)"),
    ("app/forge_lane_admission.py", "RESERVE_GB", "reserve RAM libre exigee (Go)"),
    ("app/forge_lane_admission.py", "RAM_ECART_PTS", "ecart entre observateurs qui declenche une remesure (pts)"),
    ("app/forge_resource_manager.py", "_VETO_SOMMEIL_MAX_S", "borne d'un veto de sommeil (s)"),
    ("tools/forge_epistemic_daemon.py", "VETO_EXAMEN_S", "veto de sommeil pose pendant l'examen de la soif (s)"),
    ("tools/forge_self_patcher.py", "PASSES_MAX", "passes de generation sur une proposition REL"),
    ("tools/forge_self_patcher.py", "VERDICTS_RETENUS", "verdicts du juge qui laissent le candidat (attente commit owner)"),
    ("tools/forge_self_patcher.py", "_REJETS_RAFFINABLES", "verdicts qui ouvrent la seconde passe"),
    ("tools/forge_bfcl_runner.py", "CANARI_N", "cas temoins avant une passe BFCL"),
    ("tools/forge_humaneval_runner.py", "CANARI_N", "cas temoins avant une passe HumanEval"),
]
JUGE = "app/forge_mutation_judge.py"
INSTANTANE_MCP = "tests/schemas_mcp_structure.json"
ARBRE = "docs/roadmap_arbre.json"
_RE_VERDICT = re.compile(r"""["']verdict["']\s*(?:\]\s*=|:)\s*["']([A-Z][A-Z_]+)["']""")
_RE_OWNER = re.compile(r"owner|geste|decision|d[ée]rogation", re.I)


def lire_constante(racine: Path, rel: str, nom: str) -> dict:
    """Valeur d'une affectation de MODULE `nom = <litteral>` et sa ligne ; ABSENTE / ILLISIBLE sinon."""
    try:
        arbre = ast.parse((racine / rel).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError) as e:
        return {"etat": "ILLISIBLE", "raison": type(e).__name__}
    for n in arbre.body:
        cibles = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if any(isinstance(c, ast.Name) and c.id == nom for c in cibles) and getattr(n, "value", None) is not None:
            try:
                return {"etat": "LU", "valeur": ast.literal_eval(n.value), "ligne": n.lineno}
            except ValueError:
                return {"etat": "LU", "valeur": ast.unparse(n.value), "ligne": n.lineno, "expression": True}
    return {"etat": "ABSENTE"}


def verdicts_du_juge(racine: Path) -> list[str] | None:
    """Verdicts que le juge ECRIT (litteraux affectes a « verdict ») ; None si le juge est illisible."""
    try:
        return sorted(set(_RE_VERDICT.findall((racine / JUGE).read_text(encoding="utf-8", errors="replace"))))
    except OSError:
        return None


def outils_mcp(racine: Path) -> list[dict] | None:
    try:
        d = json.loads((racine / INSTANTANE_MCP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [{"nom": nom, "requis": sorted((s or {}).get("required") or []),
             "parametres": sorted(((s or {}).get("properties") or {}).keys())} for nom, s in sorted(d.items())]


def _ouvrir_ro(chemin: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % Path(chemin).as_posix(), uri=True, timeout=3)


def bareme_rings(chemin: Path) -> dict | None:
    """forge_tools(tool_name, min_ring, is_active) : petite table de configuration, pas le corpus."""
    try:
        con = _ouvrir_ro(chemin)
        try:
            return {r[0]: {"min_ring": r[1], "actif": bool(r[2])}
                    for r in con.execute("SELECT tool_name, min_ring, is_active FROM forge_tools")}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def schema_base(chemin: Path) -> dict:
    """DDL et mode de journal d'une base, par sqlite_master SEUL (aucune lecture de donnees)."""
    if not Path(chemin).exists():
        return {"etat": "ABSENTE", "chemin": str(chemin)}
    try:
        con = _ouvrir_ro(chemin)
        try:
            mode = con.execute("PRAGMA journal_mode").fetchone()[0]
            objets = [{"type": t, "nom": n, "sql": s} for t, n, s in con.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name")]
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"etat": "ILLISIBLE", "chemin": str(chemin), "raison": "%s: %s" % (type(e).__name__, e)}
    return {"etat": "LU", "chemin": str(chemin), "journal_mode": mode, "objets": objets}


def bases_canoniques() -> dict:
    """Chemins rendus par l'organe proprietaire (forge_db_path), jamais par balayage du disque."""
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_db_path as dbp

    out = {"rag (db_path)": dbp.db_path(), "taches (tasks_path)": dbp.tasks_path(),
           "m2m (m2m_path)": dbp.m2m_path(), "bareme (authority_path)": dbp.authority_path()}
    for nom in dbp.journaux_connus():
        out["journal %s" % nom] = dbp.journal_path(nom)
    return {k: Path(str(v)) for k, v in out.items()}


def regrouper(chemins: dict) -> dict:
    """{chemin reel: [noms]} : une base vue sous plusieurs noms (authority_path et les journaux rendent la base RAG
    tant que leur interrupteur n'est pas pose) n'est decrite qu'UNE fois -- mesure 26/10 : DDL triple, 170 000 car."""
    out: dict = {}
    for nom, p in chemins.items():
        try:
            cle = Path(p).resolve()
        except OSError:
            cle = Path(p)
        out.setdefault(cle, []).append(nom)
    return out


def roadmap(racine: Path) -> dict | None:
    try:
        d = json.loads((racine / ARBRE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = d.get("items") or []
    comptes: dict = {}
    for i in items:
        comptes[i.get("etat")] = comptes.get(i.get("etat"), 0) + 1
    restants = [{"cle": i.get("cle"), "etat": i.get("etat"), "priorite": i.get("priorite") or "--",
                 "reste": (i.get("reste") or "").strip(),
                 "owner": i.get("etat") in ("DECISION_OWNER", "OWNER_PLANIFIE")
                 or bool(_RE_OWNER.search(i.get("reste") or ""))}
                for i in items if i.get("etat") not in ("CLOS", "GELE")]
    clos = [{"cle": i.get("cle"), "priorite": i.get("priorite") or "--"} for i in items if i.get("etat") == "CLOS"]
    return {"total": len(items), "comptes": comptes, "restants": restants, "clos": clos}


def _entete(titre: str, sha: str, quand: str) -> str:
    return ("# %s\n\n> Genere par `tools/forge_spec_extractor.py` (introspection, aucune valeur recopiee a la main) "
            "-- commit `%s`, %s. Ne pas editer : relancer l'extracteur.\n\n" % (titre, sha, quand))


def rendre_trd(constantes: list, verdicts: list | None, sha: str, quand: str) -> str:
    l = [_entete("02 — TRD : invariants mesures dans le code", sha, quand),
         "## Constantes de regulation et d'evolution\n\n| Constante | Valeur | Source | Role |\n|---|---|---|---|"]
    for (rel, nom, role), m in constantes:
        val = "`%r`" % (m["valeur"],) if m["etat"] == "LU" else "**%s**" % m["etat"]
        src = "`%s:%s`" % (rel, m.get("ligne", "?")) if m["etat"] == "LU" else "`%s`" % rel
        l.append("| `%s` | %s | %s | %s |" % (nom, val, src, role))
    l.append("\n## Litteraux « verdict » ecrits par le juge (`%s`)\n\nVerdicts finaux ET sous-jugements (gain : "
             "NEUTRE / DEGRADE, held-out : TENU / PROPRE...) : la liste dit ce que le code ECRIT, pas sa hierarchie.\n"
             % JUGE)
    l.append("**ILLISIBLE**" if verdicts is None else ", ".join("`%s`" % v for v in verdicts))
    return "\n".join(l) + "\n"


def rendre_schema(bases: dict, outils: list | None, bareme: dict | None, sha: str, quand: str) -> str:
    l = [_entete("01 — Schema : bases et contrats MCP mesures", sha, quand), "## Bases (organe proprietaire : `forge_db_path`)\n"]
    for _chemin, (noms, s) in bases.items():
        nom = " = ".join(noms)
        if s["etat"] != "LU":
            l.append("### %s\n`%s` : **%s** %s\n" % (nom, s["chemin"], s["etat"], s.get("raison", "")))
            continue
        tables = [o for o in s["objets"] if o["type"] == "table"]
        l.append("### %s\n`%s` -- journal `%s`, %d table(s), %d objet(s)\n" % (
            nom, s["chemin"], s["journal_mode"], len(tables), len(s["objets"])))
        l.append("```sql\n%s\n```\n" % "\n".join((o["sql"] or "-- %s %s" % (o["type"], o["nom"])) + ";"
                                               for o in s["objets"] if o["type"] in ("table", "index")))
    l.append("## Outils MCP (`%s`)\n" % INSTANTANE_MCP)
    if outils is None:
        l.append("**ILLISIBLE**\n")
    else:
        l.append("%d outil(s) dans l'instantane de la CI. Ring minimal lu dans `forge_tools` (petit = plus de "
                 "privilege ; -99 = outil coupe) %s.\n" % (len(outils), "" if bareme is not None else "-- **bareme ILLISIBLE**"))
        l.append("| Outil | Requis | Parametres | Ring min | Actif |\n|---|---|---|---|---|")
        for o in outils:
            b = (bareme or {}).get(o["nom"]) or {}
            l.append("| `%s` | %s | %d | %s | %s |" % (o["nom"], ", ".join(o["requis"]) or "--", len(o["parametres"]),
                                                    b.get("min_ring", "repli code"), b.get("actif", "?")))
    return "\n".join(l) + "\n"


def rendre_plan(rm: dict | None, sha: str, quand: str) -> str:
    l = [_entete("06 — Plan : items restants de la roadmap", sha, quand)]
    if rm is None:
        return l[0] + "**ILLISIBLE** : `%s` absent ou illisible (lancer forge_roadmap_keeper --arbre).\n" % ARBRE
    clos = rm["comptes"].get("CLOS", 0)
    l.append("%d / %d CLOS (%.1f %%) ; etats : %s.\n" % (clos, rm["total"], 100.0 * clos / max(1, rm["total"]),
                                                        ", ".join("%s %d" % kv for kv in sorted(rm["comptes"].items(), key=str))))
    for titre, owner in (("Bloques par un geste ou une decision owner", True), ("Realisables sans l'owner", False)):
        sel = [r for r in rm["restants"] if r["owner"] is owner]
        l.append("## %s (%d)\n\n| Item | Etat | Prio | Reste |\n|---|---|---|---|" % (titre, len(sel)))
        for r in sorted(sel, key=lambda r: (r["priorite"], r["cle"] or "")):
            l.append("| `%s` | %s | %s | %s |" % (r["cle"], r["etat"], r["priorite"],
                                                 (r["reste"][:220] or "(non dit)").replace("|", "/").replace("\n", " ")))
        l.append("")
    # Les cles CLOS (26/10) : docs/roadmap_arbre.json n'est pas versionne ; sans cette liste, le 04_PRD ne pouvait
    # relier aucune capacite a son item clos.
    clos = rm.get("clos") or []
    l.append("## Clos (%d)\n" % len(clos))
    for prio in sorted({c["priorite"] for c in clos}):
        cles = sorted(c["cle"] or "" for c in clos if c["priorite"] == prio)
        l.append("- **%s** (%d) : %s" % (prio, len(cles), ", ".join("`%s`" % k for k in cles)))
    l.append("")
    return "\n".join(l) + "\n"


def _sha() -> str:
    try:
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=20).stdout.strip() or "INCONNU"
    except (OSError, subprocess.SubprocessError):
        return "INCONNU"


# 31/10 (choix owner « gate qui signale + nuit ») : specs REDIGEES par des agents, que l'extracteur ne sait pas produire --
# le gate les DIT non couvertes (avec leur age) au lieu de les juger.
NON_COUVERTS = ("03_APPFLOW.md", "04_PRD.md", "05_UX_AX.md")
_ENTETE_VOLATILE = "> Genere par `tools/forge_spec_extractor.py`"


def _normaliser(txt: str) -> list:
    """Lignes comparables : l'en-tete (sha, date du rendu) est volatile par construction."""
    return [l.rstrip() for l in txt.splitlines() if not l.startswith(_ENTETE_VOLATILE)]


def verifier(rendus: dict, dossier) -> dict:
    """{spec: {etat, ...}} : FRAIS / PERIME (lignes_changees) / ABSENT pour les specs generees ; NON_COUVERT (age_j)
    ou ABSENT pour les specs redigees. Lecture seule."""
    import difflib
    d = Path(dossier)
    out = {}
    for nom, txt in rendus.items():
        p = d / nom
        if not p.is_file():
            out[nom] = {"etat": "ABSENT"}
            continue
        a, b = _normaliser(p.read_text(encoding="utf-8", errors="replace")), _normaliser(txt)
        n = sum(1 for l in difflib.ndiff(a, b) if l[:2] in ("- ", "+ "))
        out[nom] = {"etat": "FRAIS"} if n == 0 else {"etat": "PERIME", "lignes_changees": n}
    for nom in NON_COUVERTS:
        p = d / nom
        out[nom] = ({"etat": "NON_COUVERT", "age_j": round((time.time() - p.stat().st_mtime) / 86400.0, 1)}
                    if p.is_file() else {"etat": "ABSENT"})
    return out


def rendre_tout() -> dict:
    """Les specs GENEREES, rendues depuis le code et les sources canoniques (aucune ecriture)."""
    sha, quand = _sha(), time.strftime("%Y-%m-%d %H:%M")
    try:
        chemins = bases_canoniques()
    except Exception as e:  # noqa: BLE001 - organe proprietaire illisible : on le DIT
        chemins = {}
        print("[spec] forge_db_path ILLISIBLE (%s) : section bases vide" % type(e).__name__)
    bases = {chemin: (noms, schema_base(chemin)) for chemin, noms in regrouper(chemins).items()}
    bareme_src = chemins.get("bareme (authority_path)")
    return {
        "01_SCHEMA.md": rendre_schema(bases, outils_mcp(ROOT), bareme_rings(bareme_src) if bareme_src else None, sha, quand),
        "02_TRD.md": rendre_trd([(c, lire_constante(ROOT, c[0], c[1])) for c in CONSTANTES], verdicts_du_juge(ROOT), sha, quand),
        "06_PLAN.md": rendre_plan(roadmap(ROOT), sha, quand),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ecrire", action="store_true", help="ecrit docs/specs/01_SCHEMA.md, 02_TRD.md, 06_PLAN.md")
    ap.add_argument("--verifier", action="store_true",
                    help="compare docs/specs au code (FRAIS/PERIME/ABSENT, NON_COUVERT pour les specs redigees) ; "
                         "n'ecrit rien ; rc 1 si une spec GENEREE est perimee ou absente (le gate CI est non "
                         "bloquant : blocking=False), rc 0 sinon")
    a = ap.parse_args(argv)
    docs = rendre_tout()
    if a.verifier:
        v = verifier(docs, ROOT / "docs" / "specs")
        for nom in sorted(v):
            e = v[nom]
            print("[spec] %-16s %-12s %s" % (nom, e["etat"], ", ".join("%s=%s" % kv for kv in e.items()
                                                                         if kv[0] != "etat")))
        perimes = sorted(n for n, e in v.items() if e["etat"] in ("PERIME", "ABSENT"))
        generees = [n for n in perimes if n not in NON_COUVERTS]
        print("BILAN spec_verifier : %d perimee(s)/absente(s) %s" % (len(perimes), perimes))
        return 1 if generees else 0
    for nom, txt in docs.items():
        print("[spec] %-12s %6d car. %s" % (nom, len(txt), "ILLISIBLE present" if "ILLISIBLE" in txt else "ok"))
        if a.ecrire:
            (ROOT / "docs" / "specs").mkdir(parents=True, exist_ok=True)
            (ROOT / "docs" / "specs" / nom).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
