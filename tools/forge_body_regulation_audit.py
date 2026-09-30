"""
tools/forge_body_regulation_audit.py — AUDIT D'AUTOREGULATION, module par module.

Demande owner 2026-07-25 : « un audit de chaque module .py, de sa contrepartie dans les
organes du corps, la verification de son autoregulation via le corps, et enfin faire
vivre le corps sur cet ensemble coordonne, avec cognition et capacitif en RAG. »

CE QUI EXISTE DEJA (anti-dup, on ne le refait pas) :
  - `tools/forge_module_census.py` + `sandbox/workspace/organ_map_full.json` :
    module -> ORGANE (714 forge classes, 0 orphelin).
  - `app/forge_organ_agents.py` : organe -> agent/tier/statut/cablage (niveau FAMILLE).
CE QUI MANQUAIT, et que ce module ajoute :
  le croisement **par MODULE** avec la regulation reelle du corps -- un module peut
  etre parfaitement classe dans un organe et n'etre regule par PERSONNE.

Quatre questions posees a chaque module, chacune repondue par une SOURCE, jamais par
une impression :
  1. ORGANE      : que dit le census ? (organ_map_full.json)
  2. SUPERVISE   : le superviseur le lance-t-il ? (services.toml : cmd/args)
  3. SURVEILLE   : ecrit-il un heartbeat que le superviseur lit ? (services.toml)
  4. VIVANT      : quelqu'un l'importe-t-il ? (scan des imports reels du depot)
                   Un module que PERSONNE n'importe et que PERSONNE ne lance est une
                   ZONE MORTE -- le piege deja paye 3 fois ici (_step_search,
                   _step_refine, forge_bounded_queue).

Le verdict n'est PAS un jugement de valeur : une bibliotheque importee par 20 modules
est saine sans etre supervisee. On distingue donc les ROLES (daemon / bibliotheque /
outil) avant de conclure.

Enfin, « faire vivre le corps » : le resultat est INGERE en RAG, un chunk par organe,
pour que la cognition puisse demander « qui regule X ? » au lieu de relire ce fichier.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ORGAN_MAP_JSON = ROOT / "sandbox" / "workspace" / "organ_map_full.json"
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"

# Le corps n'est PAS ecrit qu'en Python. `proxy_deno/core/supervisor.ts` EST l'organe
# qui lance tous les autres ; le webhub est en TS/JS ; des .ps1/.cmd portent le boot
# et la maintenance. Un audit limite au .py declarait « corps couvert » en ignorant
# son propre superviseur — angle mort signale par l'owner le 2026-07-25.
SCAN_DIRS = ("app", "tools", "proxy_deno", "scripts", "webhub")
CODE_EXT = (".py", ".ts", ".js", ".mjs", ".ps1", ".psm1", ".bat", ".cmd")
# Extensions citees dans services.toml (le superviseur lance des .ts et des .ps1
# autant que des .py) — sert a reconnaitre QUI est lance.
_SVC_FILE_RE = re.compile(r"([A-Za-z0-9_.-]+\.(?:py|ts|js|mjs|ps1|psm1|bat|cmd))", re.I)


# ── 1. ORGANE : ce que dit le census ────────────────────────────────────────
def load_organ_map() -> dict:
    """module -> organe, depuis le census AUTO-COURANT (jamais re-derive ici)."""
    try:
        raw = json.loads(ORGAN_MAP_JSON.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        print(f"[audit] census illisible ({type(e).__name__}) -> organes inconnus", flush=True)
        return {}
    # Forme REELLE du census (verifiee, pas supposee) :
    #   {"module_organ": {"forge_rag_engine.py": "Memoire (hippocampe/RAG)", ...},
    #    "tally": {...}, "provenance": {...}}
    # Les deux formes a plat sont conservees en repli : la premiere version de cette
    # fonction les supposait toutes deux et n'a rien charge -- 1710 modules « non
    # classes » alors que le census en classait 714. Une lecture de la structure aurait
    # coute 10 secondes.
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        inner = raw.get("module_organ")
        if isinstance(inner, dict):
            return {Path(k).name: v for k, v in inner.items() if isinstance(v, str)}
        for k, v in raw.items():
            if isinstance(v, str):
                out[Path(k).name] = v
            elif isinstance(v, list):
                for m in v:
                    out[Path(str(m)).name] = k
    return out


# ── 2 & 3. SUPERVISION : ce que dit services.toml ───────────────────────────
# Services DECLARES mais `disabled = true` : eteints PAR DECISION. Mesure 2026-07-28 :
# 27 des 80 entrees de services.toml, dont NokidoWatchdog, NokidoBrainWorker,
# NokidoNightTrainer, NokidoEgressLock, NokidoGitProxy — tous comptes jusqu'ici en
# « mort silencieuse ». Meme faux positif que searxng cote sante le meme jour :
# « au repos » n'est pas « en panne ». Un capteur qui confond les deux fait du bruit,
# et le bruit a couvert 13 h de mort reelle du daemon epistemique.
DESACTIVES: dict = {}

# Un nom de script cite dans un fichier : forme nue (sans espace) ou CITEE entre
# guillemets, seule forme ou un espace est sans ambiguite ("Nokido Tray.bat").
REF_PAT = re.compile(r"([A-Za-z0-9_.-]+\.(?:py|ts|js|mjs|ps1|psm1|bat|cmd))")
REF_PAT_CITE = re.compile(r"[\"']([A-Za-z0-9_.\- ]+\.(?:py|ts|js|mjs|ps1|psm1|bat|cmd))[\"']")
# Etat de lecture de chaque racine scannee par `scan_references` -- DIT, jamais tu.
REF_ROOTS_ETAT: dict = {}

# ZONES MORTES INSTRUITES -- 2026-09-06. Le capteur avait rendu 29 « ni supervise,
# ni importe, ni cite nulle part ». Chacune a ete croisee avec ce qu'il ne lisait
# pas : 387 taches planifiees et 33 services nssm (lus, 0 hit), les 3 lanceurs du
# Bureau owner (nokido_start.ps1, nokido_stop.ps1, restart_hub.ps1 -- aucun des 29),
# le registre des services pour les installateurs, le contenu pour les modules.
# Une instruction est une MESURE datee, pas un permis de suppression : rien ici
# n'autorise a retirer un fichier. Statuts : INSTALLATEUR (effet present/absent),
# OUTIL (script manuel sans appelant), ASSET (fichier hors perimetre import),
# GELE (copie ou predecesseur conserve), NON_CABLE (module ecrit, jamais branche),
# INDETERMINE (ce qu'on n'a PAS pu voir, nomme).
INSTRUITS_LE = "2026-09-06"
INSTRUITS: dict = {
    "install_autonomous_loops_nssm.ps1": ("INSTALLATEUR", "service NokidoAutonomousLoops PRESENT au registre : effet accompli"),
    "install_deno_hub_mcp_nssm.ps1": ("INSTALLATEUR", "service NokidoDenoHubMCP PRESENT au registre : effet accompli"),
    "install_deno_proxy_nssm.ps1": ("INSTALLATEUR", "service NokidoDenoProxy PRESENT au registre : effet accompli"),
    "install_deno_webhub_nssm.ps1": ("INSTALLATEUR", "service NokidoDenoWebHub PRESENT au registre : effet accompli"),
    "nssm_register_wasmedge.ps1": ("INSTALLATEUR", "service NokidoWasmedge ABSENT du registre : cervelet WasmEdge jamais installe ou retire, a geler"),
    "create_wasmedge_task.ps1": ("INSTALLATEUR", "tache \\LaForge\\wasmedge_cervelet ABSENTE (387 taches lues) : a geler avec NokidoWasmedge"),
    "forge_circadian_install.ps1": ("INSTALLATEUR", "taches LaForge-Circadian-* ABSENTES (387 lues) ; le circadien vit dans circadianLoop du superviseur Deno : a geler"),
    "register_autopoiesis_cp.ps1": ("INDETERMINE", "fichier ILLISIBLE au compte sandbox (ACL) ; aucune tache 'autopoies' parmi les 387 lues : a lire en console owner"),
    "custom_statusline.ps1": ("INDETERMINE", "sa citation attendue vit dans ~/.claude/settings.json (profil owner), illisible au compte sandbox : a verifier en console owner"),
    "Nokido Control Panel.bat": ("OUTIL", "lanceur owner ; cite entre guillemets par install_shortcuts.ps1 (nom a espace)"),
    "Nokido Tray.bat": ("OUTIL", "lanceur owner ; cite entre guillemets par install_shortcuts.ps1 (nom a espace)"),
    "nokido_stop.bat": ("GELE", "predecesseur de nokido_stop.ps1, cible reelle du lanceur Bureau 'Nokido STOP.lnk' ; conserve, ne pas lancer"),
    "supervisor.backup.ts": ("GELE", "copie de sauvegarde de supervisor.ts, jamais chargee ; conserve, ne pas lancer"),
    "forge_cert_binding.py": ("NON_CABLE", "module mTLS (identite de transport liee a l'identite applicative) sans aucun importateur : dette de cablage du volet identification"),
    "forge_fts_trigram.py": ("NON_CABLE", "index trigram code/logs ecrit, ni importe ni invoque : a cabler ou a geler, decision a prendre"),
    # Instruits le 2026-09-17 par l'autopsie RUNTIME du jalon NEXT (bb:verdict_next_autopsie_acp_a2a_2026_09_17),
    # menee par agents LOCAUX en lecture seule, denominateur 2 lus / 0 illisibles / 0 sautes.
    "forge_a2a_server.py": ("NON_CABLE", "serveur A2A declare disabled=true sans appelant on-demand, port 7783 JAMAIS interroge par un client, zero consommateur de sortie, effet reel nul hors tests NR : le protocole ne peut pas converger avec les autres clients puisqu'il n'est branche a rien. Decision a prendre, rebrancher ou geler -- ZONE_MORTE n'autorise aucune suppression"),
    "forge_a2a_card.py": ("NON_CABLE", "carte d'agent A2A importee par le seul forge_a2a_server, lui-meme non cable : sa regulation suit celle de son unique importateur"),
    "watch_cli_progress.py": ("OUTIL", "moniteur terminal d'un watch job (scripts/, legacy) sans appelant : usage manuel"),
    "add_defender_exclusion.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : usage manuel owner"),
    "fix_graph_env.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : reparation manuelle"),
    "fix_graph_utf8.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : reparation manuelle"),
    "fix_ollama_models_path.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : reparation manuelle"),
    "kill-gemini.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : arret manuel"),
    "nssm_stabilize.bat": ("OUTIL", "script batch sans appelant (depot, taches, services lus) : usage manuel owner"),
    "start_lobehub.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : lancement manuel"),
    "switch_webhub_to_py314.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : migration ponctuelle"),
    "wasm_asset_copy.ps1": ("OUTIL", "script PowerShell sans appelant (depot, taches, services lus) : copie ponctuelle"),
    "browser_js_linkgopher_patched.js": ("ASSET", "fichier JS d'extension navigateur (linkgopher) : hors perimetre import, pas un organe"),
    "linkgopher.js": ("ASSET", "fichier JS d'extension navigateur (linkgopher) : hors perimetre import, pas un organe"),
    "options.js": ("ASSET", "fichier JS d'extension navigateur (linkgopher) : hors perimetre import, pas un organe"),
    "popup_js_popup.js": ("ASSET", "fichier JS d'extension navigateur (linkgopher) : hors perimetre import, pas un organe"),
}


def load_supervision() -> tuple[dict, dict, dict]:
    """module -> service qui le lance, module -> heartbeat, module -> port declare.

    Les entrees `disabled` sont ecartees de `supervised` et rangees dans DESACTIVES :
    les compter comme lancees produisait une mort silencieuse imaginaire.

    Le PORT est la troisieme source, ajoutee le 2026-07-30 : un service qui declare un
    port est sonde ACTIVEMENT par le superviseur (probe HTTP P1.1, cf supervisor.ts),
    donc sa mort n'est PAS silencieuse — le port se ferme et la sonde le voit. Sans
    cette source, l'audit comptait `nokido_hub.py` (le hub lui-meme), `main.ts`,
    `forge_qdrant_server.py` et `netcfg_lazy_proxy.ts` parmi les morts silencieuses :
    autant de FAUX POSITIFS que la boucle d'amelioration poursuivait.
    """
    supervised: dict[str, str] = {}
    heartbeat: dict[str, str] = {}
    ports: dict[str, int] = {}
    DESACTIVES.clear()
    try:
        import tomllib

        data = tomllib.loads(SERVICES_TOML.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        print(f"[audit] services.toml illisible ({type(e).__name__})", flush=True)
        return supervised, heartbeat, ports
    for svc in data.get("service", []):
        name = svc.get("name", "?")
        blob = " ".join(str(a) for a in (svc.get("args") or [])) + " " + str(svc.get("cmd", ""))
        _off = bool(svc.get("disabled"))
        for m in _SVC_FILE_RE.findall(blob):
            fname = Path(m).name
            if _off:
                DESACTIVES[fname] = name
                continue
            supervised[fname] = name
            if svc.get("heartbeat"):
                heartbeat[fname] = svc["heartbeat"]
            if svc.get("port"):
                ports[fname] = int(svc["port"])
    return supervised, heartbeat, ports


# ── 4. VIVANT : qui importe qui, mesure sur le code REEL ────────────────────
def scan_imports() -> tuple[dict, dict]:
    """importe_par[module] = nb de fichiers qui l'importent ; roles[module] = daemon|lib|outil."""
    files: list[Path] = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix.lower() in CODE_EXT and "node_modules" not in p.parts:
                files.append(p)
    importers: dict[str, set] = defaultdict(set)
    roles: dict[str, str] = {}
    # Dependances hors Python : `import x from './forge_y.ts'`, `require('...')`,
    # `Import-Module .\x.psm1`, `. .\x.ps1` (sourcing PowerShell).
    _JS_IMP = re.compile(r"""(?:from|require\(|import\()\s*['"]([^'"]+)['"]""")
    _PS_IMP = re.compile(r"""(?:Import-Module|\.\s+)['"]?([\w./\\-]+\.psm?1)['"]?""", re.I)
    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ext = f.suffix.lower()
        if ext == ".py":
            has_main = "__main__" in src
            looks_daemon = bool(re.search(r"while True|--daemon|--watch|daemon infini", src))
        else:
            # Un .ts/.js « outil » a un point d'entree ; un daemon boucle ou sert.
            has_main = bool(re.search(r"import\.meta\.main|Deno\.serve|listen\(|param\s*\(", src, re.I))
            looks_daemon = bool(re.search(r"while\s*\(true\)|setInterval|Deno\.serve|serve\(", src, re.I))
        roles[f.name] = "daemon" if (has_main and looks_daemon) else ("outil" if has_main else "lib")

        cites: list[str] = []
        if ext == ".py":
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    cites += [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    cites.append(node.module)
            cites = [c.split(".")[-1] + ".py" for c in cites]
        elif ext in (".ts", ".js", ".mjs"):
            cites = [Path(m).name for m in _JS_IMP.findall(src)]
        elif ext in (".ps1", ".psm1"):
            cites = [Path(m).name for m in _PS_IMP.findall(src)]
        for c in cites:
            stem = Path(c).stem
            if stem.startswith(("forge_", "nokido_")) or Path(c).suffix.lower() in CODE_EXT:
                name = c if Path(c).suffix else c + ".py"
                importers[name].add(f.name)
    return {k: len(v) for k, v in importers.items()}, roles


def _is_link(path: str) -> bool:
    """Jonction NTFS ou lien symbolique — a ne pas traverser."""
    try:
        if hasattr(os.path, "isjunction") and os.path.isjunction(path):
            return True
        return os.path.islink(path)
    except OSError:
        return True  # illisible = on n'y va pas


def scan_references() -> dict:
    """module -> nb de fichiers qui le citent PAR SON CHEMIN (et non par import).

    Mesure indispensable : un module peut etre parfaitement vivant sans qu'aucun
    `import` ne le mentionne. Cas reels rencontres au premier passage, tous classes
    « zone morte » a tort :
      - `bash_guard.py` : invoque par les HOOKS (`.claude/settings.json`), jamais importe ;
      - les scripts lances par `run_job` / `trusted_script path=...` (chaine de
        caracteres, invisible a l'AST) ;
      - les entrees de `services.toml` et les runbooks `.md`/`.ps1`.
    Sans ce second regard, l'audit rend des centaines de faux positifs et devient
    exactement le « capteur decoratif » qu'on cherche a eviter.
    """
    refs: dict[str, int] = defaultdict(int)
    globs = ("**/*.py", "**/*.md", "**/*.json", "**/*.toml", "**/*.ps1", "**/*.bat",
             "**/*.cmd", "**/*.ts", "**/*.yml", "**/*.yaml")
    # `sandbox` est EXCLU : c'est la zone d'ARTEFACTS GENERES, dont la sortie de cet
    # audit lui-meme (`body_regulation.json` nomme les 1477 modules) et les cartes
    # (`module_cards.json`). Sans cette exclusion le capteur lit sa propre sortie et
    # declare TOUT le monde « invoque » : mesure du 25/07 — 125 zones mortes et 49
    # outils se sont evapores d'un coup (742 -> 916 INVOQUE, la somme exacte). Un
    # resultat parfait est le premier symptome d'un capteur qui se mord la queue.
    skip = {"__pycache__", ".git", "node_modules", "_work", "_attic", ".venv",
            "site-packages", "dist", "build", "logs", "backups", "archive", "sandbox"}
    # Filet complementaire si l'un de ces artefacts est genere hors `sandbox/`.
    artefacts = {"body_regulation.json", "module_cards.json", "organ_map_full.json",
                 "module_inventory.md", "section10.md", "forge_organ_map.json",
                 # Sa propre source : la table INSTRUITS nomme 29 modules, et le capteur
                 # les lisait « cites par 1 fichier » -- le sien. Mesure 2026-09-06, le
                 # jour meme ou la table a ete ecrite. Un instrument qui se lit lui-meme
                 # mesure son vocabulaire (deja paye 3x le 04/09).
                 "forge_body_regulation_audit.py"}
    exts = {".py", ".md", ".json", ".toml", ".ps1", ".bat", ".cmd", ".ts", ".yml", ".yaml"}
    # Le perimetre scanne 8 extensions (CODE_EXT) mais ce detecteur ne cherchait que
    # `.py` : tout .ts/.js/.ps1/.bat cite dans services.toml, un hook ou un lanceur
    # ressortait ZONE_MORTE faute d'etre reconnu INVOQUE -- un capteur aveugle a 7 de
    # ses 8 extensions accuse de mort ce qu'il ne sait pas lire. Meme motif que la regex
    # figee du 2026-07-22 : on REPARE le capteur, on ne debranche pas le garde.
    # Un nom AVEC ESPACE ("Nokido Tray.bat") n'est capte QU'ENTRE GUILLEMETS, seule
    # forme sans ambiguite. Mesure 2026-09-06 : trois lanceurs a espace sortaient
    # ZONE_MORTE alors que install_shortcuts.ps1 les cite, entre guillemets. Capter
    # l'espace nu produirait des faux positifs de masse sur de la prose.
    pat, pat_cite = REF_PAT, REF_PAT_CITE
    # `os.walk` avec ELAGAGE, et non `glob("**/*")` : glob descend dans TOUTE
    # l'arborescence puis on filtre -- il traverse donc `.git`, `sandbox`, les backups.
    # Ici on retire les dossiers de `dirnames` : ils ne sont jamais visites.
    for root in (ROOT, Path.home() / ".claude"):
        # Trois etats par racine, DITS. `~/.claude` (hooks, statusline) vit dans le
        # profil owner, ILLISIBLE au compte sandbox : `is_dir()` y rend False, et un
        # False lu comme « rien a citer » fabrique des zones mortes en silence.
        try:
            lisible = root.is_dir() and bool(os.listdir(root))
        except OSError:
            lisible = False
        REF_ROOTS_ETAT[str(root)] = "LU" if lisible else "ILLISIBLE_OU_ABSENT"
        if not lisible:
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Les JONCTIONS NTFS se presentent comme des dossiers ordinaires : `os.walk`
            # y descend, et celle qui pointe vers `V:` PEND quand le volume n'est pas
            # monte (pathologie deja connue du RAG). Precaution, PAS un correctif : le
            # blocage suppose ici n'a jamais eu lieu -- le scan aboutissait, c'est le RSS
            # du WRAPPER que je lisais au lieu du log du job.
            dirnames[:] = [d for d in dirnames
                           if d not in skip and not d.startswith(".")
                           and not _is_link(os.path.join(dirpath, d))]
            for name in filenames:
                if Path(name).suffix.lower() not in exts or name in artefacts:
                    continue
                f = Path(dirpath) / name
                try:
                    # Plafond de taille : les dumps (census, index, logs concatenes)
                    # pesent des dizaines de Mo et ne citent aucun module utilement.
                    if f.stat().st_size > 2_000_000:
                        continue
                    txt = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in set(pat.findall(txt)) | set(pat_cite.findall(txt)):
                    if m != name:            # une auto-mention ne prouve rien
                        refs[m] += 1
    return dict(refs)


def scan_systeme() -> tuple[dict, dict]:
    """Ce que le SYSTEME invoque hors depot : taches planifiees et services nssm.

    `scan_references` ne lit que des fichiers ; un script lance par une tache ou un
    service n'y est cite nulle part et sort ZONE_MORTE. Mesure 2026-09-06 : 387 taches
    et 33 services lisibles depuis le compte sandbox -- 0 des 29 zones mortes du jour,
    mais un capteur qui ne regarde pas ne peut pas le dire. Trois etats par observateur,
    avec le denominateur : LU / VIDE / ILLISIBLE. Jamais un silence lu comme un zero.
    Angle mort qui RESTE, nomme : les lanceurs du profil owner (Bureau, Demarrage),
    lisibles seulement en SYSTEM -- releves a la main le 2026-09-06 (nokido_start.ps1,
    nokido_stop.ps1, restart_hub.ps1, aucun autre).
    """
    refs: dict[str, set] = defaultdict(set)
    etats: dict[str, dict] = {}
    reg = r"HKLM\SYSTEM\CurrentControlSet\Services"
    sondes = {
        # Denominateur = lignes dont le 2e champ commence par `\` (le nom de tache) :
        # la 1re colonne du CSV verbeux est le nom d'HOTE, pas la tache -- compter les
        # lignes qui commencent par `"\` rendait « LU 0 » sur 387 taches lues.
        "schtasks": (["schtasks", "/query", "/fo", "csv", "/v"],
                     lambda o: sum(1 for l in o.splitlines() if l.startswith('"') and '","\\' in l)),
        "nssm_Application": (["reg", "query", reg, "/s", "/f", "Application", "/v", "Application"], lambda o: o.count("REG_")),
        "nssm_AppParameters": (["reg", "query", reg, "/s", "/f", "AppParameters", "/v", "AppParameters"], lambda o: o.count("REG_")),
    }
    for nom, (cmd, compte) in sondes.items():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=90)
        except (OSError, subprocess.SubprocessError) as e:
            etats[nom] = {"etat": "ILLISIBLE", "raison": f"{type(e).__name__}: {e}"[:120]}
            continue
        out = r.stdout or ""
        if not out.strip():
            etats[nom] = {"etat": "ILLISIBLE" if r.returncode else "VIDE",
                          "raison": (r.stderr or f"rc={r.returncode}").strip()[:120]}
            continue
        etats[nom] = {"etat": "LU", "n": compte(out)}
        for m in set(REF_PAT.findall(out)) | set(REF_PAT_CITE.findall(out)):
            refs[m].add(nom)
    return {k: sorted(v) for k, v in refs.items()}, etats


# Un conteneur EST un organe : SearXNG voit (recherche), Qdrant se souvient (vecteurs),
# crawl4ai digere (web), Ollama metabolise (LLM). Les ignorer laissait un angle mort
# entier — mesure 2026-07-25 : 1477 entrees dans la carte, TOUTES des .py, zero
# conteneur. Un corps qui ne sait pas que son organe de la vue est arrete ne peut pas
# expliquer pourquoi il ne voit plus (cas reel : veilles bloquees, SearXNG down).
CONTAINER_ORGAN = (
    ("searxng", "Digestif/Sens (ingestion/web)"),
    ("crawl4ai", "Digestif/Sens (ingestion/web)"),
    ("qdrant", "Memoire (hippocampe/RAG)"),
    ("embed", "Memoire (hippocampe/RAG)"),
    ("brain-worker", "Cognition/Agentique/Raisonnement"),
    ("ollama", "Metabolisme LLM (routage/backends)"),
    ("webhub", "Interface/UI (peau/expression)"),
    ("hub", "SNC (cerveau/moelle/SNP)"),
    ("neo4j", "Graph/Connaissances"),
    ("graph", "Graph/Connaissances"),
)


def scan_containers(refs: dict) -> list:
    """Les conteneurs DECLARES du corps, avec leur organe et leur regulation.

    Source = les fichiers compose a la RACINE (ceux de `sandbox/` sont des depots
    tiers explores, pas des organes de Nokido). On ne demande PAS son etat au daemon :
    il peut etre arrete — et c'est justement le cas ou l'information compte le plus.
    On decrit donc ce que le corps DECLARE et ce qui le TIENT, pas un instantane.
    """
    out: list = []
    seen: set = set()
    keeper = ""
    try:
        import tomllib

        data = tomllib.loads(SERVICES_TOML.read_text(encoding="utf-8", errors="replace"))
        for svc in data.get("service", []):
            blob = json.dumps(svc, ensure_ascii=False).lower()
            if "docker" in blob or "compose" in blob:
                keeper = svc.get("name", "")
                break
    except Exception:  # noqa: BLE001
        pass

    for comp in sorted(ROOT.glob("docker-compose*.y*ml")):
        try:
            txt = comp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        in_services = False
        for line in txt.splitlines():
            if re.match(r"^services:\s*$", line):
                in_services = True
                continue
            if in_services and re.match(r"^[A-Za-z_]", line):
                in_services = False          # sortie du bloc services (volumes:, etc.)
            m = re.match(r"^  ([A-Za-z0-9][A-Za-z0-9_.-]*):\s*$", line)
            if in_services and m:
                name = m.group(1)
                if name in seen:
                    continue
                seen.add(name)
                low = name.lower()
                organ = next((o for k, o in CONTAINER_ORGAN if k in low), "non classe")
                # Un conteneur est « tenu » si un keeper le surveille, et « cable »
                # si le code le nomme (URL, port, ensure_service).
                n_ref = refs.get(name, 0) + refs.get(name.replace("laforge-", ""), 0)
                if keeper:
                    st = "REGULE"
                    why = f"declare dans {comp.name}, surveille par {keeper}"
                elif n_ref:
                    st, why = "CABLE", f"declare dans {comp.name}, cite par {n_ref} fichier(s)"
                else:
                    st, why = "ZONE_MORTE", f"declare dans {comp.name}, rien ne le lance ni ne le cite"
                out.append({"module": f"container:{name}", "organe": organ,
                            "role": "conteneur", "statut": st, "raison": why,
                            "importe_par": 0, "cite_par": n_ref})
    return out


def verdict(mod: str, sup: dict, hb: dict, imported: dict, role: str,
            refs: dict, ports: dict | None = None,
            refs_sys: dict | None = None) -> tuple[str, str]:
    """Statut de regulation + la RAISON (jamais un verdict sans son motif).

    ZONE_MORTE veut dire « aucun rattachement TROUVE », pas « module mort ». Angles
    morts connus et non couverts : taches planifiees et cles de demarrage du profil
    owner (illisibles depuis les comptes de service), lancements manuels, appels
    construits dynamiquement. C'est un signal a INSTRUIRE, jamais un permis de
    supprimer -- le cout d'un faux positif (organe vivant debranche) est sans commune
    mesure avec celui d'un faux negatif (un module inutile de plus).
    """
    n_imp = imported.get(mod, 0)
    n_ref = refs.get(mod, 0)
    if mod in DESACTIVES:
        return "DESACTIVE", (f"declare par {DESACTIVES[mod]} mais disabled=true — "
                             "eteint PAR DECISION, pas une mort silencieuse")
    if mod in sup:
        if mod in hb:
            return "REGULE", f"supervise par {sup[mod]} + heartbeat surveille"
        _p = (ports or {}).get(mod)
        if _p:
            # Sa mort n'est PAS silencieuse : le port se ferme et la sonde HTTP du
            # superviseur (P1.1) le voit. Compter ces services parmi les morts
            # silencieuses faisait poursuivre des faux positifs, dont le hub lui-meme.
            return "SONDE", (f"supervise par {sup[mod]}, sans heartbeat mais port "
                             f"{_p} sonde activement (probe HTTP)")
        return "SUPERVISE", f"lance par {sup[mod]}, SANS heartbeat (mort silencieuse possible)"
    if n_imp > 0:
        return "CABLE", f"importe par {n_imp} module(s)"
    n_sys = (refs_sys or {}).get(mod)
    if n_sys:
        # Le systeme lui-meme le lance : tache planifiee ou service nssm. Invisible
        # aux fichiers du depot, vivant quand meme.
        return "INVOQUE", f"invoque par le systeme ({', '.join(n_sys)}), sans import ni citation"
    if mod in INSTRUITS:
        # Une instruction DATEE, mesuree a la main, prime sur un simple compte de
        # citations : la doctrine (RULES_SHARED, memoires, docs) qui DOCUMENTE une
        # zone morte la rendait INVOQUE -- une mention n'est pas une invocation. Le
        # compte reste dans la raison, et un import ou une invocation systeme,
        # testes plus haut, retirent l'instruction d'eux-memes.
        st, why = INSTRUITS[mod]
        suite = f" ; cite par {n_ref} fichier(s) depuis" if n_ref else ""
        return st, f"{why} (instruit le {INSTRUITS_LE}{suite})"
    if n_ref > 0:
        # Invoque par chemin : hook, run_job, runbook, config. Vivant sans import.
        return "INVOQUE", f"cite par {n_ref} fichier(s) (hook/config/script), sans import"
    if role == "outil":
        return "OUTIL", "lance a la demande (aucun import attendu)"
    return "ZONE_MORTE", ("ni supervise, ni importe, ni cite (fichiers lus, taches planifiees, "
                          "services nssm) ; lanceurs du profil owner NON lus")


def main() -> int:
    ap = argparse.ArgumentParser()
    # L'ingestion est le DEFAUT : « faire vivre le corps » est la raison d'etre de cet
    # outil, et surtout `run action=run_job` IGNORE le parametre `args` -- son wrapper
    # genere lance le script NU (verifie dans job_*_wrap.py). Un drapeau obligatoire
    # rendait donc l'outil silencieusement inoperant en deporte : audit affiche, RAG
    # vide, aucune erreur. Le defaut porte l'effet utile ; c'est le refus qui s'exprime.
    ap.add_argument("--no-ingest", dest="ingest", action="store_false",
                    help="rapport seul, sans ecrire en RAG")
    ap.add_argument("--ingest", dest="ingest", action="store_true",
                    help="(defaut) ecrire le resultat en RAG")
    ap.set_defaults(ingest=True)
    ap.add_argument("--top", type=int, default=25, help="zones mortes listees dans le rapport")
    args = ap.parse_args()

    organ_of = load_organ_map()
    sup, hb, ports = load_supervision()
    imported, roles = scan_imports()
    refs = scan_references()
    for _r, _e in REF_ROOTS_ETAT.items():
        print(f"[references] {_e:<20} {_r}", flush=True)
    refs_sys, etats_sys = scan_systeme()
    for _n, _e in etats_sys.items():
        print(f"[systeme] {_n:<20} {_e.get('etat')} {_e.get('n', _e.get('raison', ''))}",
              flush=True)
    print(f"[systeme] {len(refs_sys)} script(s) invoques par tache planifiee / service nssm",
          flush=True)

    # Perimetre : le CORPS, pas les brouillons. On exclut les zones de travail
    # (_attic, sandbox, __pycache__, tests) et les scripts jetables (`_batch12_send.py`,
    # `tmp_*.py`) : les compter en « zones mortes » noierait les VRAIES sous des
    # centaines de faux positifs -- premier passage : 583 « zones mortes » dont
    # l'immense majorite etait du jetable.
    _EXCLUDE_DIRS = ("_attic", "sandbox", "__pycache__", "tests", "test", "seed", "research")
    # `auto_boot_20260319_153549.py` & co : artefacts GENERES et horodates, pas des organes.
    _EXCLUDE_FILE = re.compile(r"^(_|tmp_|test_|auto_boot_\d)")

    def _in_perimetre(p: Path) -> bool:
        if any(part in _EXCLUDE_DIRS for part in p.parts):
            return False
        return not _EXCLUDE_FILE.match(p.name)

    # Chemin relatif conserve : il porte la fonction quand le nom ne la dit pas
    # (`app/web_hub/forms/ask_form.py`). On garde le PREMIER vu, l'ordre etant trie.
    found: dict[str, str] = {}
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if (p.suffix.lower() in CODE_EXT and "node_modules" not in p.parts
                    and _in_perimetre(p) and p.name not in found):
                found[p.name] = str(p.relative_to(ROOT)).replace("\\", "/")
    modules = sorted(found)

    # Classification DELEGUEE au census (`forge_module_census.organ`) : c'est lui
    # l'autorite (carte explicite > mot-cle > dossier). Cette fonction se contentait
    # de relire la carte JSON, donc tout ce que la carte ne nommait pas ressortait
    # « non classe » -- 768 modules, alors que le classificateur savait en placer la
    # quasi-totalite. Reutiliser plutot que redecider : une seule taxonomie.
    classify = None
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_module_census import organ as _census_organ

        classify = _census_organ
    except Exception as e:  # noqa: BLE001
        print(f"[audit] census indisponible ({type(e).__name__}) : organes = carte seule",
              flush=True)

    rows = []
    for m in modules:
        organ = organ_of.get(m)
        if not organ and classify:
            organ = classify(Path(m).stem, m, found.get(m))
        if not organ or organ.startswith("?"):
            organ = "non classe"
        st, why = verdict(m, sup, hb, imported, roles.get(m, "lib"), refs, ports, refs_sys)
        rows.append({"module": m, "organe": organ, "role": roles.get(m, "lib"),
                     "statut": st, "raison": why, "importe_par": imported.get(m, 0),
                     "cite_par": refs.get(m, 0), "invoque_systeme": refs_sys.get(m, [])})

    # Les conteneurs rejoignent la MEME carte que les modules : meme statut, meme
    # organe, meme ingestion RAG. Sinon l'autoregulation raisonne sur un demi-corps.
    conteneurs = scan_containers(refs)
    rows.extend(conteneurs)
    print(f"[conteneurs] {len(conteneurs)} organes conteneurises ajoutes a la carte",
          flush=True)

    by_status: dict[str, int] = defaultdict(int)
    by_organ: dict[str, list] = defaultdict(list)
    for r in rows:
        by_status[r["statut"]] += 1
        by_organ[r["organe"]].append(r)

    print(f"=== AUDIT AUTOREGULATION — {len(rows)} modules ===", flush=True)
    for st, n in sorted(by_status.items(), key=lambda kv: -kv[1]):
        print(f"  {st:<12} {n:>4}", flush=True)
    print(f"\n=== PAR ORGANE ({len(by_organ)}) ===", flush=True)
    for organ, mods in sorted(by_organ.items(), key=lambda kv: -len(kv[1])):
        regs = sum(1 for m in mods if m["statut"] in ("REGULE", "SUPERVISE"))
        morts = sum(1 for m in mods if m["statut"] == "ZONE_MORTE")
        print(f"  {organ:<40} {len(mods):>4} mods | {regs:>3} supervises | {morts:>3} zones mortes",
              flush=True)

    mortes = [r for r in rows if r["statut"] == "ZONE_MORTE"]
    print(f"\n=== ZONES MORTES ({len(mortes)}) — {args.top} premieres ===", flush=True)
    print("  AVERTISSEMENT — ce verdict n'autorise AUCUNE suppression. Lus ce passage :"
          " fichiers du depot, taches planifiees et services nssm (etats ci-dessus)."
          " NON lus : les lanceurs de boot du profil OWNER (Bureau, Demarrage), et"
          " ~/.claude quand la racine est marquee ILLISIBLE. Mesure : forge_owner_daemons.py"
          " est lance au boot par l'owner et sortait ZONE_MORTE.", flush=True)
    print("  Avant d'agir sur un module : croiser avec son LOG, pas avec ce tableau.",
          flush=True)
    for r in mortes[:args.top]:
        print(f"  {r['module']:<46} [{r['organe']}]", flush=True)

    # Cache pour les CONSOMMATEURS (forge_module_cards notamment). Le scan de
    # references coute ~1 min : le refaire dans `refresh_changed`, appele apres chaque
    # ecriture de fichier, rendrait toute edition insupportable. Producteur periodique
    # / consommateur instantane, comme `organ_map_full.json` juste a cote.
    cache = {r["module"]: {"statut": r["statut"], "raison": r["raison"],
                           "organe": r["organe"]} for r in rows}
    out_json = ROOT / "sandbox" / "workspace" / "body_regulation.json"
    try:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[cache] {out_json.name} — {len(cache)} modules", flush=True)
    except OSError as e:
        print(f"[cache] ECHEC ecriture ({e}) — les cartes garderont l'ancien verdict",
              flush=True)

    if args.ingest:
        n = ingest_rag(rows, by_organ, by_status)
        print(f"\n[RAG] {n} chunk(s) ecrits — le corps peut desormais se decrire lui-meme",
              flush=True)
    print("\nFIN", flush=True)
    return 0


def _index_fts(conn, cid: str, text: str, source: str, ancien: str | None = None) -> None:
    """Indexation lexicale, avec le motif d'echec IMPRIME plutot qu'avale.

    Sans FTS le chunk existe mais reste introuvable tant qu'il n'est pas vectorise :
    une panne d'index se lirait « ingestion OK » alors que rien n'est cherchable.
    Purge puis `INSERT`, jamais `INSERT OR IGNORE` : sur une table FTS il ne met
    pas a jour le texte -- une reindexation laisserait l'ANCIENNE version en place.

    La purge passe par `forge_db_path.purger_fts` (MATCH sur une phrase de l'ANCIEN
    texte, `ancien` lu par cle primaire AVANT le remplacement), JAMAIS par
    `DELETE ... WHERE chunk_id=?` : `chunk_id` est UNINDEXED, ce DELETE balayait tout
    l'index lexical sous verrou d'ecriture, 17 fois par audit -- ~1 h de verrou chaque
    soir a 22 h (NREM1) et hub fige (mesure 2026-09-27).
    NR : tests/nr/test_audit_regulation_fts_sans_scan_nr.py
    """
    try:
        if ancien is not None:
            from nokido_agent.app.forge_db_path import purger_fts

            _n, laissees = purger_fts(conn, [(cid, ancien)])
            for c in laissees:
                print(f"[FTS] {c} : ancien texte sans mot exploitable -> ligne laissee a "
                      "purge_rag_fts_fantomes", flush=True)
        conn.execute("INSERT INTO rag_fts (chunk_id, text, source, domain)"
                     " VALUES (?,?,?,?)", (cid, text, source, "laforge"))
    except Exception as e:  # noqa: BLE001
        print(f"[FTS] ECHEC index {cid} : {e} — chunk ecrit mais NON cherchable en lexical",
              flush=True)


def ingest_rag(rows: list, by_organ: dict, by_status: dict) -> int:
    """FAIRE VIVRE LE CORPS : un chunk par organe + une synthese, en RAG.

    But cognitif : qu'une question comme « qui regule le systeme nerveux ? » trouve la
    reponse par retrieval, au lieu d'exiger la relecture de ce fichier. Domaine
    `laforge` -> tier CHAUD, donc vectorise par le daemon (cf. forge_tier_policy).
    """
    import hashlib

    from nokido_agent.app.forge_db_path import open_writer, write_retry  # noqa: F401

    now = datetime.now(tz=timezone.utc).isoformat()
    # ENVELOPPE DE REPRISE. `open_writer` (WAL + autocommit + busy_timeout) ne
    # suffit pas quand un VOISIN tient une transaction ouverte : busy_timeout
    # attend un verrou liberable, pas un verrou detenu. Mesure du 2026-09-08 —
    # l'audit a produit son verdict COMPLET (1894 modules, 16 organes) puis l'a
    # PERDU sur « database is locked » pendant qu'une veille ingerait en
    # parallele ; le job rendait rc=1 alors que l'AUDIT avait reussi, et seul le
    # RAG restait muet. La docstring de `write_retry` nomme exactement ce cas.
    # Verrouille par tests/nr/test_audit_ingestion_reprise_nr.py.
    def _ecrire_les_cartes(conn):
        n = 0
        for organ, mods in by_organ.items():
            regs = [m for m in mods if m["statut"] in ("REGULE", "SUPERVISE")]
            morts = [m for m in mods if m["statut"] == "ZONE_MORTE"]
            lignes = "\n".join(
                f"- {m['module']} [{m['role']}] {m['statut']} : {m['raison']}" for m in mods[:120])
            text = (
                f"ORGANE {organ} — autoregulation ({len(mods)} modules, "
                f"{len(regs)} supervises, {len(morts)} zones mortes)\n\n{lignes}"
            )
            cid = "body_reg_" + hashlib.md5(organ.encode()).hexdigest()[:10]
            ancien = conn.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,author,"
                "ingested_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (cid, text, f"body_audit:{organ}", "laforge", "corps:autoregulation",
                 "BodyRegulationAudit", now, now))
            _index_fts(conn, cid, text, f"body_audit:{organ}", ancien[0] if ancien else None)
            n += 1
        synth = (
            "SYNTHESE AUTOREGULATION DU CORPS NOKIDO\n\n"
            + "\n".join(f"- {k} : {v} modules" for k, v in sorted(by_status.items(), key=lambda kv: -kv[1]))
            + f"\n\nTotal {len(rows)} modules sur {len(by_organ)} organes.\n"
            "Lecture : REGULE = supervise + heartbeat surveille ; SUPERVISE = lance mais "
            "sans heartbeat NI port sonde (sa mort est silencieuse) ; SONDE = supervise "
            "sans heartbeat mais port sonde activement, sa mort EST vue ; "
            "CABLE = importe par d'autres "
            "modules ; INVOQUE = cite par un hook, une config ou un script, sans import ; "
            "OUTIL = lance a la demande ; ZONE_MORTE = ni lance, ni importe, ni cite.\n"
            "Regeneration : LAFORGE_PYTHON tools/forge_body_regulation_audit.py --ingest"
        )
        cid = "body_reg_synthese"
        ancien = conn.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,author,"
            "ingested_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (cid, synth, "body_audit:synthese", "laforge", "corps:autoregulation",
             "BodyRegulationAudit", now, now))
        _index_fts(conn, cid, synth, "body_audit:synthese", ancien[0] if ancien else None)
        n += 1
        return n

    return write_retry(_ecrire_les_cartes)


if __name__ == "__main__":
    raise SystemExit(main())
