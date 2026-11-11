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
         "<!-- nokido:statique -->",
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
    l = [_entete("01 — Schema : bases et contrats MCP mesures", sha, quand),
         "<!-- nokido:dynamique -->",
         "## Bases (organe proprietaire : `forge_db_path`)\n"]
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
    l.append("<!-- nokido:statique -->")
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
    l = [_entete("06 — Plan : items restants de la roadmap", sha, quand), "<!-- nokido:dynamique -->"]
    if rm is None:
        return l[0] + "**ILLISIBLE** : `%s` absent ou illisible (lancer forge_roadmap_keeper --arbre).\n" % ARBRE
    clos = rm["comptes"].get("CLOS", 0)
    l.append("%d / %d CLOS (%.1f %%) ; etats : %s (`%s`).\n" % (
        clos, rm["total"], 100.0 * clos / max(1, rm["total"]),
        ", ".join("%s %d" % kv for kv in sorted(rm["comptes"].items(), key=str)), ARBRE))
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


def _entete_statique(titre: str, sha: str) -> str:
    return ("# %s\n\n> Genere par `tools/forge_spec_extractor.py` (introspection deterministe, aucun horodatage) "
            "-- commit `%s`. Ne pas editer : relancer l'extracteur.\n\n" % (titre, sha))


def _fonctions_module(racine: Path, rel: str, noms: tuple[str, ...] = ()) -> list[tuple[str, int]] | None:
    try:
        arbre = ast.parse((racine / rel).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    vues: dict[str, int] = {}
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not noms or n.name in noms):
            vues.setdefault(n.name, n.lineno)
    if noms:
        return [(nom, vues[nom]) for nom in noms if nom in vues]
    return sorted(vues.items(), key=lambda x: (x[1], x[0]))


def _services_toml(racine: Path) -> list[dict] | None:
    cfg = racine / "proxy_deno" / "core" / "services.toml"
    try:
        lignes = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    blocs: list[dict] = []
    courant: dict | None = None
    for ligne in lignes:
        s = ligne.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[[service"):
            courant = {}
            blocs.append(courant)
            continue
        if s.startswith("["):
            courant = None
            continue
        if courant is not None and "=" in s:
            m = re.match(r"([\w.]+)\s*=\s*(.+)", s)
            if m:
                val = m.group(2).strip()
                if not val.startswith(('"', "'", "[")):
                    val = val.split(" #", 1)[0].split("\t#", 1)[0].strip()
                courant[m.group(1)] = val.strip('"')
    res = [b for b in blocs if b.get("name")]
    return res or None


def _pyproject_info(racine: Path) -> dict | None:
    pj = racine / "pyproject.toml"
    try:
        txt = pj.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    nom = re.search(r'(?m)^name\s*=\s*"([^"]+)"', txt)
    lic = re.search(r'(?m)^license\s*=\s*\{text\s*=\s*"([^"]+)"\}', txt)
    bloc = re.search(r"\[project\.scripts\]\s*(.*?)(?:\n\[|\Z)", txt, re.S)
    scripts = []
    if bloc:
        for l in bloc.group(1).splitlines():
            m = re.match(r'\s*([\w.-]+)\s*=\s*"([\w.:]+)"', l)
            if m:
                scripts.append((m.group(1), m.group(2)))
    if not nom and not scripts:
        return None
    return {"name": nom.group(1) if nom else "INCONNU", "license": lic.group(1) if lic else "INCONNU",
            "scripts": sorted(scripts)}


def _organes_census(racine: Path) -> list[tuple[str, list[str]]] | None:
    m = lire_constante(racine, "tools/forge_module_census.py", "ORGANS")
    if m.get("etat") != "LU" or not isinstance(m.get("valeur"), list):
        return None
    groupes: dict[str, list[str]] = {}
    for entree in m["valeur"]:
        if isinstance(entree, tuple) and len(entree) == 2:
            org, kws = entree
            lst = groupes.setdefault(str(org), [])
            for k in kws:
                if str(k) not in lst:
                    lst.append(str(k))
    return sorted(groupes.items()) or None


def _acteurs_identites(racine: Path) -> list[dict] | None:
    p = racine / "config" / "agent_identities.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    agents = d.get("agents") if isinstance(d, dict) else None
    if not isinstance(agents, dict) or not agents:
        return None
    out = []
    for nom, cfg in sorted(agents.items()):
        if not isinstance(cfg, dict):
            continue
        wp = cfg.get("write_paths") or []
        out.append({
            "nom": nom,
            "kind": str(cfg.get("kind") or "--"),
            "ring": str(cfg.get("ring", "--")),
            "surface": str(cfg.get("surface") or "--"),
            "write_paths": ", ".join(f"`{w}`" for w in wp[:5]) + ("..." if len(wp) > 5 else "") if wp else "--",
        })
    return out or None


def _routes_web(racine: Path, rel: str) -> list[tuple[str, str, str, int]] | None:
    try:
        arbre = ast.parse((racine / rel).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    routes = []
    for n in ast.walk(arbre):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in n.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                verbe = dec.func.attr.upper()
                if verbe in ("GET", "POST", "PUT", "DELETE", "PATCH") and dec.args:
                    arg0 = dec.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        routes.append((verbe, arg0.value, n.name, n.lineno))
    return sorted(routes, key=lambda r: (r[1], r[0], r[3]))


_FLUX_APPFLOW = (
    ("(a) Admission d'un job", "app/forge_job_runner.py", ("admettre_lancement",), ()),
    ("(a-bis) Regulateur de lanes et ressources", "app/forge_lane_admission.py",
     ("check_ressources", "current", "admit"), ("MAX_RAM_PCT", "RAM_ECART_PTS")),
    ("(b) Cycle de la soif et du soin", "tools/forge_epistemic_daemon.py",
     ("run_once", "_interoceptive_split", "effecteur_enquete", "_decision_examen"), ("VETO_EXAMEN_S",)),
    ("(c) Auto-amelioration (self-patcher)", "tools/forge_self_patcher.py",
     ("run_once", "_essayer_patch", "_submit_to_judge"), ("PASSES_MAX", "VERDICTS_RETENUS")),
    ("(c-bis) Juge de mutation et held-out", "app/forge_mutation_judge.py",
     ("evolution_autorisee", "mutable", "juger_module", "juger_gain", "juger_held_out", "juger_module_avec_gain"), ()),
    ("(d) Bancs BFCL / HumanEval", "tools/forge_bfcl_runner.py", ("run",), ("CANARI_N",)),
    ("(e) Garde d'ingestion de contenu de tiers", "app/forge_prompt_guard.py",
     ("analyser_contenu_tiers", "admis_a_l_ingestion"), ()),
    ("(f) Publication publique et caviardage", "tools/forge_dist_publish.py",
     ("sync_snapshot", "_sans_motifs", "_caviarder_sujets", "_verifier_sujets_prives"), ()),
    ("(g) Regulation RAM et eviction/reprise", "app/forge_resource_manager.py",
     ("_reveiller_les_evinces", "_admettre_reprises"), ("_VETO_SOMMEIL_MAX_S", "_SUPERVISOR_WAKE_RAM_THRESHOLD")),
)


def rendre_appflow(racine: Path | None = None, sha: str = "INCONNU", _quand: str = "") -> str:
    """03_APPFLOW.md : machines d'etat et topologie declarative (statique) + pointeurs vivants (dynamique)."""
    r = ROOT if racine is None else Path(racine)
    l = [
        _entete_statique("03 — AppFlow : machines d'etat et flux mesures", sha),
        "## 1. ETAT STATIQUE — Machines d'etat et topologie (genere au commit)\n",
        "> Chaque machine d'etat et chaque service declare est extrait par AST ou lecture deterministe du depot.\n",
        "### 1.1 Machines d'etat et transitions du coeur\n",
    ]
    for titre, rel, fns, cstes in _FLUX_APPFLOW:
        f_lu = _fonctions_module(r, rel, fns)
        if f_lu is None:
            l.append("- **%s** (`%s`) : **ILLISIBLE** (fichier absent ou syntaxe invalide)" % (titre, rel))
            continue
        f_txt = ", ".join("`%s` (`%s:%d`)" % (nom, rel, ln) for nom, ln in f_lu) or "**ILLISIBLE**"
        c_parts = []
        for c in cstes:
            mc = lire_constante(r, rel, c)
            c_parts.append("`%s=%r` (`%s:%s`)" % (c, mc["valeur"], rel, mc["ligne"])
                           if mc["etat"] == "LU" else "`%s` (**%s**)" % (c, mc["etat"]))
        extra = (" ; constantes : " + ", ".join(c_parts)) if c_parts else ""
        l.append("- **%s** (`%s`) : points d'entree %s%s" % (titre, rel, f_txt, extra))
    l.append("\n### 1.2 Topologie declarative des services essentiels (`proxy_deno/core/services.toml`)\n")
    svcs = _services_toml(r)
    if svcs is None:
        l.append("**ILLISIBLE** : `proxy_deno/core/services.toml` absent ou illisible.\n")
    else:
        l.append("| Service | Wave | Essentiel | Mode declare | Commande cible |\n|---|---|---|---|---|")
        retenus = [s for s in svcs if str(s.get("essential", "false")).lower() in ("true", "1")] or svcs[:8]
        for s in sorted(retenus, key=lambda x: str(x.get("name", ""))):
            dis = str(s.get("disabled", "false")).lower() in ("true", "1")
            ess = str(s.get("essential", "false")).lower() in ("true", "1")
            mode = "dormant (on-demand)" if dis else ("essentiel" if ess else "standard")
            l.append("| `%s` | %s | %s | %s | `%s` |" % (
                s.get("name", "?"), s.get("wave", "--"), "oui" if ess else "non", mode, s.get("cmd", "--")))
        l.append("")
    l.extend([
        "## 2. ETAT DYNAMIQUE — Pointeurs vers les sources vivantes (aucun chiffre fige)\n",
        "> Les etats d'execution (services vivants, baux de lanes, RAM disponible, files de taches) changent en continu "
        "et ne sont jamais figes en prose.\n",
        "| Dimension dynamique | Pointeur vers la source vivante | Contrat de lecture |",
        "|---|---|---|",
        "| Vitalite des services (port / process / heartbeat) | `nokido_agent.app.forge_sensor_fusion_probe::probe_all` et `tools/forge_feature_checklist.py::section_services` | croise `services.toml` x port x process x heartbeat |",
        "| Baux de lanes actifs et jobs detaches | `nokido_agent.app.forge_lane_admission::current` (`LAFORGE_LANES_DB`) et `tools/forge_job_watch_cli.py --job <id>` | lecture WAL + verification sur artefact (rc != preuve) |",
        "| Signes vitaux et pression RAM / CPU | `nokido_agent.app.forge_ssot::point`, `GET /api/vitals` et `sandbox/health_diagnostic.json` | 2 observateurs (sampler + live) avant eviction/reprise |",
        "| Etat de la soif et propositions d'evolution | `sandbox/self_care_state.json` et `sandbox/evolution/` | suivi chronique et candidats soumis au juge |",
    ])
    return "\n".join(l) + "\n"


def rendre_prd(racine: Path | None = None, sha: str = "INCONNU", _quand: str = "") -> str:
    """04_PRD.md : perimetre produit, anatomie, contrats MCP, acteurs et roadmap (statique) + pointeurs (dynamique)."""
    r = ROOT if racine is None else Path(racine)
    l = [
        _entete_statique("04 — PRD : perimetre produit, anatomie et acteurs mesures", sha),
        "## 1. ETAT STATIQUE — Architecture, capacites et contrats (genere au commit)\n",
        "> Architecture, contrats d'outils, anneaux de droits et jalons lus dans les sources versionnees du depot.\n",
        "### 1.1 Identite du paquet et entrypoints CLI (`pyproject.toml`)\n",
    ]
    pj = _pyproject_info(r)
    if pj is None:
        l.append("**ILLISIBLE** : `pyproject.toml` absent ou illisible.\n")
    else:
        l.append("Paquet `%s` — licence `%s`.\n" % (pj["name"], pj["license"]))
        l.append("| Entrypoint CLI | Cible |\n|---|---|")
        for nom, cible in pj["scripts"]:
            l.append("| `%s` | `%s` |" % (nom, cible))
        l.append("")
    l.append("### 1.2 Anatomie fonctionnelle par organe (`tools/forge_module_census.py`)\n")
    orgs = _organes_census(r)
    if orgs is None:
        l.append("**ILLISIBLE** : `tools/forge_module_census.py` (`ORGANS`) absent ou illisible.\n")
    else:
        l.append("| Organe | Familles lexicales declarees (`ORGANS`) |\n|---|---|")
        for org, kws in orgs:
            l.append("| %s | %s |" % (org, ", ".join("`%s`" % k for k in kws[:6])))
        l.append("")
    l.append("### 1.3 Surface contractuelle MCP (`%s`)\n" % INSTANTANE_MCP)
    outils = outils_mcp(r)
    if outils is None:
        l.append("**ILLISIBLE** : `%s` absent ou illisible.\n" % INSTANTANE_MCP)
    else:
        l.append("Outils declares au contrat CI (detail complet dans `01_SCHEMA.md`) : %s.\n" % (
            ", ".join("`%s`" % o["nom"] for o in outils)))
    l.append("### 1.4 Acteurs CLI et anneaux RBAC (`config/agent_identities.json`)\n")
    acteurs = _acteurs_identites(r)
    if acteurs is None:
        l.append("**ILLISIBLE** : `config/agent_identities.json` absent ou illisible.\n")
    else:
        l.append("| Identite | Kind | Ring | Surface | Ecriture (`write_paths`) |\n|---|---|---|---|---|")
        for a in [x for x in acteurs if x["kind"] in ("cli_agent", "relay")]:
            l.append("| `%s` | %s | %s | %s | %s |" % (a["nom"], a["kind"], a["ring"], a["surface"], a["write_paths"]))
        l.append("")
    l.append("### 1.5 Jalons prioritaires P0 de la roadmap (`%s`)\n" % ARBRE)
    rm = roadmap(r)
    if rm is None:
        l.append("**ILLISIBLE** : `%s` absent ou illisible (lancer `forge_roadmap_keeper --arbre`).\n" % ARBRE)
    else:
        sel = [x for x in rm["restants"] if x["priorite"] == "P0"]
        l.append("| Item | Etat | Prio | Categorie | Reste |\n|---|---|---|---|---|")
        if not sel:
            l.append("| -- | -- | -- | -- | aucun jalon P0 en attente |")
        for x in sorted(sel, key=lambda k: (k["priorite"], k["cle"] or "")):
            cat = "arbitrage/geste owner" if x["owner"] else "autonome P0"
            l.append("| `%s` | %s | %s | %s | %s |" % (
                x["cle"], x["etat"], x["priorite"], cat,
                (x["reste"][:100] or "(non dit)").replace("|", "/").replace("\n", " ")))
        l.append("")
    l.extend([
        "## 2. ETAT DYNAMIQUE — Pointeurs vers les sources vivantes (aucun chiffre fige)\n",
        "> Aucun compteur volatil (nombre de tables, de chunks, de tests, de modules vivants ou d'avancement en %) "
        "n'est fige en prose : consulter les sources vivantes ci-dessous.\n",
        "| Dimension dynamique | Pointeur vers la source vivante | Contrat de lecture |",
        "|---|---|---|",
        "| Etat global du corps et compteurs vivants | `nokido_agent.app.forge_ssot::point` et `hub action=whoami` | lecture temps reel en base |",
        "| Avancement vivant de la roadmap et taches | `tools/forge_roadmap_keeper.py --arbre` (`docs/roadmap_arbre.json`) et `task action=status` (`sandbox/tasks.db`) | liste complete dans `06_PLAN.md` et recalcul vivant |",
        "| Recensement vivant des modules par organe | `tools/forge_module_census.py` (`sandbox/workspace/organ_map_full.json`) | scan AST de `app/` et `tools/` |",
        "| Verification des capacites a chaud | `nokido-doctor --vivant` et `tools/forge_feature_checklist.py` | separe declare / observe / verifie (abstention si sonde muette) |",
        "| Quotas modeles et fournisseurs | `hub action=quota_status` (`nokido_agent.app.forge_quota_tracker`) | etat courant des budgets et replis |",
    ])
    return "\n".join(l) + "\n"


_GARDES_AX = (
    ("Admission de job", "app/forge_job_runner.py", ("admettre_lancement",)),
    ("Regulateur de lanes", "app/forge_lane_admission.py", ("check_ressources", "admit")),
    ("Ecriture gouvernee", "tools/forge_governed_edit.py", ("governed_write",)),
    ("Garde shell PreToolUse", "tools/bash_guard.py", ("refus_git_gh", "segment_ok", "split_segments")),
    ("Garde fin de tour Stop", "tools/hook_stop_attente_passive.py", ("main",)),
    ("Garde memoire PreToolUse", "tools/hook_recon_first.py", ("main",)),
    ("Ordres bureau / Tray", "app/forge_ordres_bureau.py", ("demander_ordre", "commandes_en_attente")),
)


def rendre_ux(racine: Path | None = None, sha: str = "INCONNU", _quand: str = "") -> str:
    """05_UX_AX.md : gardes AX, surfaces CLI/TUI et routes web (statique) + pointeurs vivants (dynamique)."""
    r = ROOT if racine is None else Path(racine)
    l = [
        _entete_statique("05 — UX / AX : surfaces agents, CLI, TUI et cockpit web mesures", sha),
        "## 1. ETAT STATIQUE — Contrats AX, CLI/TUI et routes web (genere au commit)\n",
        "> Surfaces d'interaction et gardes extraits par AST depuis les modules du depot.\n",
        "### 1.1 AX — Gardes et points d'entree vus par un agent client\n",
    ]
    for label, rel, fns in _GARDES_AX:
        f_lu = _fonctions_module(r, rel, fns)
        if f_lu is None:
            l.append("- **%s** (`%s`) : **ILLISIBLE**" % (label, rel))
        else:
            l.append("- **%s** (`%s`) : %s" % (
                label, rel, ", ".join("`%s` (`%s:%d`)" % (n, rel, ln) for n, ln in f_lu) or "**ILLISIBLE**"))
    outils = outils_mcp(r)
    if outils is None:
        l.append("- **Contrats MCP** (`%s`) : **ILLISIBLE**\n" % INSTANTANE_MCP)
    else:
        l.append("- **Contrats MCP** (`%s`) : %s\n" % (
            INSTANTANE_MCP, ", ".join("`%s`" % o["nom"] for o in outils)))
    l.append("### 1.2 UX CLI, TUI et sondes de surfaces (`tools/forge_feature_checklist.py`, `tools/llama_cli.py`, `tools/nokido_tui.py`, `tools/forge_job_watch_cli.py`)\n")
    chk_fns = _fonctions_module(r, "tools/forge_feature_checklist.py")
    if chk_fns is None:
        l.append("- **Sondes de surfaces** (`tools/forge_feature_checklist.py`) : **ILLISIBLE**")
    else:
        sections = [(n, ln) for n, ln in chk_fns if n.startswith("section_")]
        l.append("- **Sondes de surfaces** (`tools/forge_feature_checklist.py`) : %s" % (
            ", ".join("`%s` (`:%d`)" % (n, ln) for n, ln in sections) or "**ILLISIBLE**"))
    try:
        src_cli = (r / "tools" / "llama_cli.py").read_text(encoding="utf-8", errors="replace")
        subs = sorted(set(re.findall(r'sub\.add_parser\(\s*"(\w+)"', src_cli)))
        l.append("- **Sous-commandes `nokido`** (`tools/llama_cli.py`) : %s" % (
            ", ".join("`%s`" % s for s in subs) if subs else "**ILLISIBLE**"))
    except OSError:
        l.append("- **Sous-commandes `nokido`** (`tools/llama_cli.py`) : **ILLISIBLE**")
    try:
        src_tui = (r / "tools" / "nokido_tui.py").read_text(encoding="utf-8", errors="replace")
        cmds = sorted(set(re.findall(r'"(/\w[\w-]*)"\s*:', src_tui)))
        l.append("- **Commandes TUI** (`tools/nokido_tui.py`) : %s" % (
            ", ".join("`%s`" % c for c in cmds) if cmds else "**ILLISIBLE**"))
    except OSError:
        l.append("- **Commandes TUI** (`tools/nokido_tui.py`) : **ILLISIBLE**")
    jw_fns = _fonctions_module(r, "tools/forge_job_watch_cli.py", ("lire_bilan", "main"))
    if jw_fns is None:
        l.append("- **Surveillance CLI** (`tools/forge_job_watch_cli.py`) : **ILLISIBLE**\n")
    else:
        l.append("- **Surveillance CLI** (`tools/forge_job_watch_cli.py`) : %s\n" % (
            ", ".join("`%s` (`:%d`)" % (n, ln) for n, ln in jw_fns) or "**ILLISIBLE**"))
    l.append("### 1.3 UX Cockpit Web — Pages et flux SSE (`app/web_hub/app.py`, `app/web_hub/wired_routes.py`)\n")
    _ROUTES_CLE = {"/", "/hub", "/dashboard", "/vitals", "/anatomy", "/organs", "/reports", "/auth/login",
                   "/launcher", "/rbac", "/providers", "/roadmap/arbre", "/swarm", "/rag", "/postal",
                   "/api/vitals/sse", "/api/swarm/stream"}
    routes_toutes = []
    for rel_w in ("app/web_hub/app.py", "app/web_hub/wired_routes.py"):
        rw = _routes_web(r, rel_w)
        if rw is None:
            l.append("- `%s` : **ILLISIBLE**" % rel_w)
        else:
            routes_toutes.extend((v, ch, fn, "%s:%d" % (rel_w, ln)) for v, ch, fn, ln in rw if ch in _ROUTES_CLE)
    if routes_toutes:
        l.append("| Methode | Route | Handler | Source |\n|---|---|---|---|")
        for v, ch, fn, src in routes_toutes:
            l.append("| `%s` | `%s` | `%s` | `%s` |" % (v, ch, fn, src))
    l.append("")
    l.extend([
        "## 2. ETAT DYNAMIQUE — Pointeurs vers les sources vivantes (aucun chiffre fige)\n",
        "> La disponibilite des pages, l'etat des controles JS/HTMX, les outils MCP servis a chaud et les flux SSE "
        "relevent de l'execution et se lisent via leurs sondes vivantes.\n",
        "| Surface dynamique | Pointeur vers la source vivante | Contrat de lecture |",
        "|---|---|---|",
        "| Etat des surfaces GUI (`live` / `dormant` / `absent`) | `tools/forge_ui_manifest.py --json` et `tools/forge_feature_checklist.py::section_http_gui` | distingue backend actif, dormant on-demand et absent |",
        "| Cablage des controles et pages web | `tools/forge_ui_nervous_census.py` (`sandbox/workspace/ui_audit/ui_contract_generated.json`) | mesure datee ISO ; refuse de conclure si age > 24 h |",
        "| Inventaire MCP servi a chaud | `POST http://127.0.0.1:8766/mcp` (`tools/list`, `tools/forge_feature_checklist.py::section_mcp`) | confronte le serveur vivant a `.mcp.json` |",
        "| Flux SSE et sante du cockpit web | `GET /api/vitals/sse`, `GET /api/swarm/stream`, `GET /status` (`:7400`) et `GET /health` (`:8766`) | flux temps reel sous semaphore |",
        "| File d'ordres operateur au Tray | `hub action=demander_ordre ordre=commandes-en-attente` (`logs/commandes_owner.jsonl`) | sépare `DEPOSE` (attente validation) et `FAITE` |",
    ])
    return "\n".join(l) + "\n"


def _sha() -> str:
    try:
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=20).stdout.strip() or "INCONNU"
    except (OSError, subprocess.SubprocessError):
        return "INCONNU"


# 8/11 (choix owner) : les 6 specs 01..06 sont desormais generees par rendre_tout ; plus aucun nom dans NON_COUVERTS.
NON_COUVERTS: tuple[str, ...] = ()
_SPECS_HISTORIQUES = ("03_APPFLOW.md", "04_PRD.md", "05_UX_AX.md")
_ENTETE_VOLATILE = "> Genere par `tools/forge_spec_extractor.py`"
_BALISE_SECTION = "<!-- nokido:"

try:
    from tools.forge_capability_audit import c_benchmarks as _c_benchmarks
except ImportError:
    from forge_capability_audit import c_benchmarks as _c_benchmarks  # type: ignore[no-redef]

_RE_COMPTEUR_DYNAMIQUE = re.compile(
    r"(?<![#\[0-9A-Za-z_/-])"
    r"(~?\s*\d[\d\s.,]*\s*(?:[kKmM]\+?)?(?:\s*/\s*\d[\d\s.,]*)?)\s*\*{0,2}\s*"
    r"("
    r"outils?\s+MCP|MCP\s+tools?|tools?\s+MCP|outil\(s\)|"
    r"(?:MCP\s+)?(?:tools?|outils?)\b|"
    r"tables?\b|table\(s\)|objet\(s\)|"
    r"modules?\b|fiches?\b|chunks?\b|fragments?\b|"
    r"(?:items?\s+)?CLOS\b|"
    r"(?:LLM\s+)?(?:providers?|fournisseurs?|vendors?)\b|"
    r"(?:(?:routed|free-tier|paid_api|cloud|local)\s+)?slots?\b"
    r")",
    re.I,
)
_RE_POINTEUR_SSOT = re.compile(
    r"(?:[\w./\\-]+(?:\.py|\.json|\.toml|\.db|\.jsonl|\.sql)\b"
    r"|\b(?:forge|nokido)_[a-z0-9_]+\b"
    r"|::[A-Za-z_]\w*"
    r"|\b(?:PROVIDER_SPECS|USE_CASE_CHAINS|_raw_tool_catalog|sqlite_master|ORGANS|CONSTANTES|INSTANTANE_MCP"
    r"|nokido-doctor|SSoT)\b"
    r"|`(?:app|tools|config|sandbox|forge_desktop)/[^`]*`"
    r"|\baction=\w+\b|/admin/providers|/api/vitals|\btools/list\b|<!--\s*STATS:)",
)


def _normaliser(txt: str) -> list:
    """Lignes comparables : l'en-tete (sha, date du rendu) et les balises de section sont volatiles."""
    return [
        l.rstrip() for l in txt.splitlines()
        if not l.startswith(_ENTETE_VOLATILE) and not l.strip().startswith(_BALISE_SECTION)
    ]


def _separer_statique_dynamique(txt: str) -> tuple[list[str], list[str]]:
    """Separe un rendu en (lignes_statiques, lignes_dynamiques) par sections balisees et colonnes MCP."""
    statique: list[str] = []
    dynamique: list[str] = []
    mode = "statique"
    dans_mcp = False
    for brut in txt.splitlines():
        l = brut.rstrip()
        if not l or l.startswith(_ENTETE_VOLATILE):
            continue
        s = l.strip()
        low = s.lower()
        if s.startswith("<!--") and s.endswith("-->"):
            if "dynamique" in low:
                mode, dans_mcp = "dynamique", False
                continue
            if "statique" in low:
                mode, dans_mcp = "statique", False
                continue
        if s.startswith("#"):
            dans_mcp = False
            if any(k in low for k in (
                "etat dynamique", "2. etat dynamique", "## bases", "roadmap_arbre.json",
                "06 — plan", "## bloques par un geste", "## realisables sans l'owner", "## clos",
            )):
                mode = "dynamique"
            elif any(k in low for k in (
                "etat statique", "1. etat statique", "## constantes", "## litteraux", "## outils mcp",
            )):
                mode = "statique"
                if "## outils mcp" in low:
                    dans_mcp = True
        if dans_mcp:
            if "outil(s) dans l'instantane de la ci" in low:
                st_l = l.replace(" -- **bareme ILLISIBLE**", "").replace("-- **bareme ILLISIBLE**", "").rstrip()
                statique.append(st_l)
                dynamique.append("bareme_illisible" if "bareme illisible" in low else "bareme_lisible")
                continue
            if s.startswith("| `") and s.count("|") >= 6:
                cols = [c.strip() for c in s.strip("|").split("|")]
                if len(cols) >= 5:
                    statique.append("| %s | %s | %s |" % (cols[0], cols[1], cols[2]))
                    dynamique.append("| %s | %s | %s |" % (cols[0], cols[3], cols[4]))
                    continue
        (statique if mode == "statique" else dynamique).append(l)
    return statique, dynamique


def _ligne_porte_date_iso(ligne: str) -> bool:
    """Reutilise c_benchmarks de forge_capability_audit (sans recopier sa regex de date ISO)."""
    verdict = _c_benchmarks("HumanEval 50% " + ligne)
    return "sans date" not in str(verdict.get("mesure") or "")


def _ligne_porte_pointeur_ssot(ligne: str) -> bool:
    return bool(_RE_POINTEUR_SSOT.search(ligne))


def detecter_chiffres_dynamiques_nus(dossier) -> list[str]:
    """Scanne docs/specs/*.md (hors redige/) et docs/wiki/*.md : signale fichier:ligne des compteurs nus."""
    d = Path(dossier)
    cibles: list[Path] = []
    if d.is_dir():
        cibles.extend(sorted(p for p in d.glob("*.md") if p.is_file()))
    for w in (d.parent / "wiki", d / "wiki"):
        if w.is_dir():
            for p in sorted(w.glob("*.md")):
                if p.is_file() and p not in cibles:
                    cibles.append(p)
    racine_rel = d.parent.parent if d.name == "specs" and d.parent.name == "docs" else d.parent
    signales: list[str] = []
    for p in cibles:
        try:
            lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        try:
            rel = str(p.relative_to(racine_rel)).replace("\\", "/")
        except ValueError:
            rel = p.name
        dans_frontmatter = False
        for idx, l in enumerate(lignes, 1):
            s = l.strip()
            if idx == 1 and s == "---":
                dans_frontmatter = True
                continue
            if dans_frontmatter:
                if s == "---":
                    dans_frontmatter = False
                continue
            if not s or s.startswith((_ENTETE_VOLATILE, "<!--", "CREATE TABLE", "CREATE INDEX")):
                continue
            m = _RE_COMPTEUR_DYNAMIQUE.search(s)
            if not m:
                continue
            brut_num = m.group(1).strip()
            digits = re.sub(r"\D", "", brut_num.split("/")[0])
            if digits and int(digits) < 3 and "/" not in brut_num and not re.search(r"[kKmM]", brut_num):
                continue
            if _ligne_porte_date_iso(s) or _ligne_porte_pointeur_ssot(s):
                continue
            signales.append("%s:%d: %s" % (rel, idx, m.group(0).strip()))
    return signales


def verifier(rendus: dict, dossier) -> dict:
    """{spec: {etat, ...}} : FRAIS / DYNAMIQUE_BOUGE (age_j) / PERIME (lignes_changees) / ABSENT ;
    controle CHIFFRE_DYNAMIQUE_NU sur docs/specs/*.md (hors redige/) et docs/wiki/*.md. Lecture seule."""
    import difflib
    d = Path(dossier)
    out = {}
    for nom, txt in rendus.items():
        p = d / nom
        if not p.is_file():
            out[nom] = {"etat": "ABSENT"}
            continue
        disque = p.read_text(encoding="utf-8", errors="replace")
        st_a, dy_a = _separer_statique_dynamique(disque)
        st_b, dy_b = _separer_statique_dynamique(txt)
        n_stat = sum(1 for l in difflib.ndiff(st_a, st_b) if l[:2] in ("- ", "+ "))
        n_dyn = sum(1 for l in difflib.ndiff(dy_a, dy_b) if l[:2] in ("- ", "+ "))
        if n_stat > 0:
            out[nom] = {"etat": "PERIME", "lignes_changees": n_stat + n_dyn, "lignes_statiques": n_stat}
        elif n_dyn > 0:
            age_j = round((time.time() - p.stat().st_mtime) / 86400.0, 1)
            out[nom] = {"etat": "DYNAMIQUE_BOUGE", "lignes_changees": n_dyn, "age_j": age_j}
        else:
            out[nom] = {"etat": "FRAIS"}
    for nom in list(NON_COUVERTS) + [n for n in _SPECS_HISTORIQUES if n not in rendus and n not in NON_COUVERTS]:
        p = d / nom
        out[nom] = ({"etat": "NON_COUVERT", "age_j": round((time.time() - p.stat().st_mtime) / 86400.0, 1)}
                    if p.is_file() else {"etat": "ABSENT"})
    nus = detecter_chiffres_dynamiques_nus(d)
    if nus:
        out["CHIFFRE_DYNAMIQUE_NU"] = {"etat": "CHIFFRE_DYNAMIQUE_NU", "lignes": nus}
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
        "03_APPFLOW.md": rendre_appflow(ROOT, sha, quand),
        "04_PRD.md": rendre_prd(ROOT, sha, quand),
        "05_UX_AX.md": rendre_ux(ROOT, sha, quand),
        "06_PLAN.md": rendre_plan(roadmap(ROOT), sha, quand),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ecrire", action="store_true", help="ecrit docs/specs/01_SCHEMA.md..06_PLAN.md")
    ap.add_argument("--verifier", action="store_true",
                    help="compare docs/specs au code (FRAIS/PERIME/ABSENT) ; "
                         "n'ecrit rien ; rc 1 si une spec GENEREE est perimee ou absente (le gate CI est non "
                         "bloquant : blocking=False), rc 0 sinon")
    ap.add_argument("--forcer", action="store_true",
                    help="avec --ecrire : ecrit meme un rendu ILLISIBLE par-dessus un doc complet")
    a = ap.parse_args(argv)
    docs = rendre_tout()
    specs = ROOT / "docs" / "specs"

    def _illisible_sous_ce_compte(nom: str) -> bool:
        # 8/11 (mesure, compte sandbox) : 01_SCHEMA rendu en 3 824 car. ILLISIBLE contre ~61 000 sur disque -- le compte
        # ne lit pas les bases. Ce n'est ni une derive du code ni un doc a jour : c'est ce compte qui ne voit pas.
        p = specs / nom
        if "ILLISIBLE" not in docs.get(nom, "") or not p.is_file():
            return False
        return "ILLISIBLE" not in p.read_text(encoding="utf-8", errors="replace")

    if a.verifier:
        v = verifier(docs, specs)
        for nom in docs:
            if v.get(nom, {}).get("etat") in ("PERIME", "DYNAMIQUE_BOUGE") and _illisible_sous_ce_compte(nom):
                v[nom] = {"etat": "ILLISIBLE", "cause": "rendu illisible sous ce compte, doc disque complet"}
        for nom in sorted(v):
            e = v[nom]
            print("[spec] %-16s %-12s %s" % (nom, e["etat"], ", ".join("%s=%s" % kv for kv in e.items()
                                                                         if kv[0] != "etat")))
        # liste BLANCHE : ILLISIBLE n'est pas frais -> compte dans le rc (UNKNOWN != sain), jamais range FRAIS
        perimes = sorted(n for n, e in v.items() if e["etat"] in ("PERIME", "ABSENT", "ILLISIBLE"))
        generees = [n for n in perimes if n in docs and n not in NON_COUVERTS]
        print("BILAN spec_verifier : %d perimee(s)/absente(s) %s" % (len(perimes), perimes))
        return 1 if generees else 0
    refuses = []
    for nom, txt in docs.items():
        print("[spec] %-12s %6d car. %s" % (nom, len(txt), "ILLISIBLE present" if "ILLISIBLE" in txt else "ok"))
        if a.ecrire:
            if _illisible_sous_ce_compte(nom) and not a.forcer:
                refuses.append(nom)
                print("[spec] %-12s NON ECRIT : rendu ILLISIBLE sous ce compte, le doc complet est garde "
                      "(--forcer pour ecraser)" % nom)
                continue
            specs.mkdir(parents=True, exist_ok=True)
            (specs / nom).write_text(txt, encoding="utf-8")
    return 1 if refuses else 0


if __name__ == "__main__":
    raise SystemExit(main())
