"""forge_module_census.py — Census anatomique des modules Nokido.

Scan app/ + tools/, classe chaque module dans un organe, ecrit l'inventaire +
la table §10. Override autoritaire = sandbox/workspace/organ_map_full.json
(carte keep + heuristique + LLM, 714 forge tous classes) ; fallback keyword
pour le non-forge. Regen : `LAFORGE_PYTHON tools/forge_module_census.py`.

La carte json est produite par C:/tmp/organ_classify.py + organ_finalize.py
(passe heuristique precision-first + classification LLM free-tier du residu).
"""
import ast
import json as _json
import re
import sys
from pathlib import Path
from collections import Counter

# ROOT auto-detect : ce fichier vit dans <ROOT>/tools/ -> parent.parent = ROOT.
ROOT = Path(__file__).resolve().parent.parent

ORGANS = [
    ("Immunitaire (firewall/garde)", ("firewall", "guard", "membrane", "integrity", "sanitiz", "rbac", "secret", "noise", "silo_frag", "prompt_guard", "conv_sanit", "dlp", "trust")),
    ("Memoire (hippocampe/RAG)", ("rag", "embed", "memory", "vector", "ingest_self", "tier", "chunk", "recall", "self_correction", "lesson", "qualify", "truth", "hybrid_bridge", "jepa", "sft", "multivec")),
    ("Metabolisme LLM (routage/backends)", ("llm_router", "provider", "cascade", "ollama", "llama", "agent_proxy", "tokenizer", "cognitive_router", "oracle", "cache_align", "prompt_cache")),
    ("Locomoteur/Orchestration", ("orchestr", "silo_engine", "swarm", "handoff", "goap", "_plan", "trajectory", "dispatcher", "runner", "runtime", "scorecard", "blackboard", "durable", "fleet", "reflexion")),
    ("SNC (cerveau/moelle/SNP)", ("hub", "mcp", "registry", "middleware", "byte_router", "nlu", "intent", "spike", "context", "event_stream", "broker", "message_frame", "secur")),
    ("Graph/Connaissances", ("graph", "ppr", "edge", "cve", "project_state", "callgraph")),
    ("SN vegetatif (autonome)", ("inspector", "watchdog", "monitor", "keeper", "sentinel", "heartbeat", "supervisor", "watcher", "_loop", "evolution", "resource", "throttle", "snapshot", "docker", "ping")),
    ("Digestif/Sens (ingestion/web)", ("crawl", "web", "browser", "gitingest", "egress", "ingest", "ui_oracle", "video", "playwright", "rootme", "paste")),
    ("Observabilite/Trace", ("trace", "observ", "span", "telemetry", "audit", "langfuse", "viz", "anatomy", "scorecard")),
    ("Qualite/Build/Spec", ("quality", "dep_manager", "spec_clar", "_test", "clinical", "scaffold")),
    ("SWE-bench", ("swebench", "swe_", "anchor_swe", "aider")),
    ("Cognition/Agentique/Raisonnement", ("active_inference", "reasoning", "arbitrat", "actor", "agentic", "agent", "mpc", "react", "think", "authority", "roles", "benchmark", "lats", "anti_ia", "judge", "debate", "panel", "consensus", "curator", "skill", "reflexion", "intuition", "cascade_oracle", "nlu", "intent", "cognitive", "arbiter", "self_improv", "evolv", "novelty", "fitness")),
    ("Infra/Bootstrap/Config", ("__init__", "bootstrap", "bridge", "facade", "debug", "diag", "setup", "config", "launcher", "services", "lifecycle", "python_bin", "db_path", "secrets", "env", "util", "helper", "common", "base")),
    ("Reseau/Distribue/Sync", ("nats", "zmq", "sync", "distrib", "p2p", "mesh", "cluster", "node", "topology", "acp", "copilot", "wire", "poll_daemon", "sidecar")),
    # --- 2026-07-25 : familles qui sortaient « non classe » alors qu'elles portent
    # une fonction claire. Placees EN FIN de liste : le premier match gagne, donc
    # elles ne peuvent voler aucun module aux organes ci-dessus (precision-first).
    ("Interface/UI (peau/expression)", ("_form", "web_hub", "webhub", "tui", "dashboard", "htmx", "ui_", "_ui", "logo", "favicon", "template")),
    ("Qualite/Build/Spec", ("bench", "check_", "ci_", "lint", "smoke", "validate", "verify_", "assert", "coverage")),
    ("SN vegetatif (autonome)", ("cleanup", "purge", "reaper", "retention", "vacuum", "rotate", "gc_")),
    ("Infra/Bootstrap/Config", ("apply_", "build_", "deploy", "install", "migrat", "patch_", "provision", "bootstrap", "seed_", "dist")),
    ("SNC (cerveau/moelle/SNP)", ("claude_", "hook", "capture", "session", "inbox", "notify", "postal", "prompt")),
    ("Cognition/Agentique/Raisonnement", ("brain", "gemini", "codex", "agy", "antigravity", "llm_", "ask_")),
    # --- 2026-09-06 (audit de raccordement) : le vocabulaire que les modules emploient
    # DEJA pour se declarer (`__FORGE_COLOR__`) et que le vote ignorait — 9 modules
    # declares restaient « non classe ». Toujours en fin de liste : precision-first.
    ("SN vegetatif (autonome)", ("regulation", "autoregulation", "homeostas", "metabol", "endocrin", "flap", "temps_mort", "lane", "admission")),
    ("SNC (cerveau/moelle/SNP)", ("routing", "router", "snn", "neuro", "snp", "nervous", "cortex", "surface")),
    ("Observabilite/Trace", ("proprioception", "atlas", "signal_", "census", "port_")),
    ("Immunitaire (firewall/garde)", ("videur", "ring_", "separation", "policy", "quarantine", "arena", "tpm", "shredder", "sandbox")),
    ("Cognition/Agentique/Raisonnement", ("mcts", "grounder", "dialogue", "domain_mapper", "typed_task", "workflow", "cowork")),
    ("Memoire (hippocampe/RAG)", ("ssot", "sdr", "successor", "world_model", "reindex")),
]

# Rattachement par DOSSIER — filet applique APRES le mot-cle, jamais avant : la
# structure physique porte une intention (un module dans `ctf_web/` est offensif
# meme si son nom ne le dit pas), mais elle est moins precise que le nom, et un
# module range dans `legacy/` garde la fonction que son nom annonce.
# But : plus AUCUN module sans organe, donc plus aucun angle mort de regulation.
ORGAN_BY_DIR = (
    ("web_hub", "Interface/UI (peau/expression)"),
    ("tui_adapters", "Interface/UI (peau/expression)"),
    ("forms", "Interface/UI (peau/expression)"),
    ("bench", "Qualite/Build/Spec"),
    ("tests", "Qualite/Build/Spec"),
    ("collab_modes", "Locomoteur/Orchestration"),
    ("agents", "Cognition/Agentique/Raisonnement"),
    ("agent_actuaire_statisticien", "Cognition/Agentique/Raisonnement"),
    ("netcfg", "Reseau/Distribue/Sync"),
    ("core", "Infra/Bootstrap/Config"),
    ("settings", "Infra/Bootstrap/Config"),
    ("legacy", "Infra/Bootstrap/Config"),
    ("scripts", "Infra/Bootstrap/Config"),
)

# Override autoritaire : carte complete. Cherche tools/ (versionne) puis
# sandbox/workspace/ (artefact genere). Fallback = {} -> keyword pur.
_ORGAN_MAP = {}
for _cand in (ROOT / "tools" / "forge_organ_map.json", ROOT / "sandbox" / "workspace" / "organ_map_full.json"):
    try:
        _ORGAN_MAP = _json.loads(_cand.read_text(encoding="utf-8")).get("module_organ", {})
        if _ORGAN_MAP:
            break
    except Exception:
        continue


# Cartes comportementales (forge_module_cards) : on y lit les IMPORTS deja extraits
# par AST, plutot que de re-parser. Chargement paresseux : le fichier pese ~2 Mo et
# la plupart des modules sont classes bien avant d'en avoir besoin.
_CARDS: dict | None = None


def _imports_of(fname):
    global _CARDS
    if _CARDS is None:
        _CARDS = {}
        try:
            raw = _json.loads((ROOT / "sandbox" / "workspace" / "module_cards.json")
                              .read_text(encoding="utf-8"))
            for rel, card in raw.items():
                _CARDS[Path(rel).name] = card.get("imports") or []
        except Exception:
            _CARDS = {}
    imps = _CARDS.get(fname)
    if imps:
        return imps
    # Repli AST : les cartes sont un artefact GENERE, non versionne. Mesure 2026-09-06 :
    # le gate CI `anatomie` (bloquant) rougissait sur le runner GitHub pour UN module
    # (`tools/prove_autonomy_pillars.py`) classe ici par ses imports -- le runner n'a
    # pas module_cards.json, donc pas de filet imports, donc « non classe ». Un gate ne
    # depend d'aucun artefact que le depot ne porte pas : on relit les imports a la
    # source. Cout : un ast.parse par module sans carte, quelques ms.
    for d in ("app", "tools"):
        p = ROOT / d / fname
        if not p.is_file():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError, ValueError):
            return []
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                out.append(node.module.split(".")[0])
        _CARDS[fname] = out
        return out
    return []


def _organ_by_imports(fname):
    """Organe DEDUIT de ce que le module utilise — sa fonction, pas son etiquette.

    Dernier filet, pour les noms qui ne disent rien (`Nokido.py`, `autotools.py`).
    Un module qui importe massivement `forge_rag_*` travaille pour la memoire, quel
    que soit son nom. On vote sur les dependances `forge_*`/`nokido_*` classees, et
    on n'accepte qu'une MAJORITE NETTE (>= 2 votes et strictement devant la 2e) :
    sur un signal faible il vaut mieux avouer « non classe » que ranger au hasard --
    une etiquette inventee est pire que pas d'etiquette, elle se propage en RAG.
    """
    votes = Counter()
    for imp in _imports_of(fname):
        if not imp.startswith(("forge_", "nokido_")):
            continue
        o = _ORGAN_MAP.get(imp + ".py")
        if not o:
            n = imp.lower()
            o = next((org for org, kws in ORGANS if any(k in n for k in kws)), None)
        if o and not o.startswith("?"):
            votes[o] += 1
    if not votes:
        return None
    top = votes.most_common(2)
    if top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
        return top[0][0]
    return None


# Mots trop communs pour discriminer un organe dans un TEXTE libre : ils sont utiles
# comme fragments de NOM de fichier ("config" dans forge_config.py) mais apparaissent
# dans presque toutes les docstrings. Les garder ferait gagner Infra a chaque fois.
_STOP_TEXT = {"base", "util", "helper", "common", "env", "config", "setup", "debug",
              "node", "wire", "_test", "_plan", "_loop", "agent", "hub", "skill"}


def _organ_by_text(text, source_is_declaration=False):
    """Organe deduit d'un TEXTE (declaration `__FORGE_COLOR__` ou docstring).

    Meme vocabulaire que le nom de fichier, mais par VOTE (occurrences cumulees) et
    non premier-match : sur une phrase, l'ordre des mots n'a aucune raison de refleter
    l'importance. On exige une majorite stricte, sauf pour une DECLARATION explicite
    (`__FORGE_COLOR__ : cognition/...`), qui est courte et intentionnelle -- le module
    dit lui-meme a quel organe il appartient, c'est la meilleure source apres la carte.
    """
    t = (text or "").lower()
    if not t:
        return None
    votes = Counter()
    for org, kws in ORGANS:
        # Le nom de l'organe lui-meme ("cognition", "immunitaire", "digestif"...) est
        # le signal le plus direct : une declaration le cite mot pour mot.
        for word in re.findall(r"[a-zA-Zéèêà]{5,}", org.lower()):
            if word in t:
                votes[org] += 3 if source_is_declaration else 1
        for k in kws:
            if len(k) >= 5 and k not in _STOP_TEXT:
                votes[org] += t.count(k)
    votes = Counter({k: v for k, v in votes.items() if v})
    if not votes:
        return None
    top = votes.most_common(2)
    if source_is_declaration and top[0][1] >= 1 and (len(top) == 1 or top[0][1] > top[1][1]):
        return top[0][0]
    if top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
        return top[0][0]
    return None


# Fenetre lue pour la DECLARATION d'organe. « 3 ko : assez pour la declaration et la
# docstring » etait FAUX — mesure 2026-09-06 : nokido.py (declaration ligne 22) et
# nokido_cutover_owner.py (ligne 52) portent une docstring plus longue ; leur
# declaration tombait hors fenetre et ils restaient « non classe » EN la portant.
# forge_organ_declare lit CETTE constante : l'ecrivain et le lecteur s'accordent sur
# la meme fenetre, sinon l'un ecrit ce que l'autre ne verra jamais.
HEAD_CHARS = 12_000
# Une declaration COMMENCE sa ligne : `__FORGE_COLOR__ = "..."` (attribut de module)
# ou la meme forme sur une ligne de docstring. Une mention dans un commentaire ou une
# regex n'en est pas une. Mesure 2026-09-06 : la regex non ancree prenait la PREMIERE
# mention — forge_organ_declare.py se voyait classe sur son propre commentaire.
DECL_RE = re.compile(r"(?m)^[ \t]*__FORGE_COLOR__\s*[:=]\s*(.{0,90})")


def _read_head(fname, relpath=None):
    """En-tete du module (HEAD_CHARS) : la declaration doit y tenir, docstring comprise."""
    cands = []
    if relpath:
        cands.append(ROOT / relpath)
    cands += [ROOT / "app" / fname, ROOT / "tools" / fname]
    for p in cands:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")[:HEAD_CHARS]
        except OSError:
            continue
    return ""


# Un corps distingue le TISSU (structure), l'ORGANE (fonction regulee), l'OUTIL
# (employe a la demande) et le DECHET (resorbe). Nokido les melangeait dans un seul
# recensement, d'ou 194 « zones mortes » dont ~110 n'etaient pas des organes malades
# mais des outils ranges (mesure 2026-07-28). Compter un scalpel range comme un organe
# necrose sature l'alerte, et une alerte saturee n'est plus lue.
_NATURE_RULES = (
    ("outil", re.compile(r"^(gd_\d+|xbox_|fix_|force_|scrub_|reload_|restore_|"
                         r"backfill_|migrate_|dump_|recon_|check_|probe_)", re.I)),
    ("outil", re.compile(r"_(form|probe|patch|oneshot)\.py$", re.I)),
    ("outil", re.compile(r"\.(ps1|bat|cmd|js)$", re.I)),
    ("tissu", re.compile(r"^(setup|install|bootstrap|conftest|__init__)", re.I)),
)


def nature(fname=None, relpath=None):
    """Nature d'un module : organe | tissu | outil | dechet.

    La DECLARATION du module prime toujours (`__FORGE_NATURE__ = "outil"`) : le code
    nourrit le corps, le corps ne devine pas. L'heuristique n'est qu'un filet, et elle
    ne classe que sur le NOM — jamais sur la prose, pour la meme raison qui a fait
    retirer le classement par docstring : une etiquette inventee se propage en RAG et
    devient indistinguable d'une mesure.
    """
    head = _read_head(fname, relpath) if fname else ""
    m = re.search(r"__FORGE_NATURE__\s*[:=]\s*[\"']?([a-z]+)", head or "")
    if m and m.group(1) in ("organe", "tissu", "outil", "dechet"):
        return m.group(1)
    base = str(relpath or fname or "").replace("\\", "/").split("/")[-1]
    for nat, rx in _NATURE_RULES:
        if rx.search(base):
            return nat
    return "organe"


def organ(name, fname=None, relpath=None):
    """Organe d'un module. Autorite decroissante : carte > nom > dossier > imports.

    `relpath` (chemin relatif a la racine, ex. "app/web_hub/forms/ask_form.py") est
    optionnel et RETRO-COMPATIBLE : sans lui le comportement est celui d'avant. Un
    corps ou un module n'appartient a aucun organe est un module que rien ne regule,
    d'ou les trois filets successifs -- du plus sur (une carte ecrite a la main) au
    plus infere (ce que le module utilise reellement).
    """
    if fname and fname in _ORGAN_MAP:
        return _ORGAN_MAP[fname]
    n = name.lower()
    for org, kws in ORGANS:
        if any(k in n for k in kws):
            return org
    if relpath:
        parts = [p.lower() for p in str(relpath).replace("\\", "/").split("/")[:-1]]
        for token, org in ORGAN_BY_DIR:
            if token in parts:
                return org
    if fname:
        by_imp = _organ_by_imports(fname)
        if by_imp:
            return by_imp
        # Le module se DECLARE-t-il ? (`__FORGE_COLOR__ : cognition/sense-of-agency`)
        # C'est court, intentionnel, ecrit par quelqu'un qui savait : la meilleure
        # source apres la carte.
        #
        # La DOCSTRING, elle, a ete essayee puis RETIREE. Elle classait 61 modules de
        # plus, mais sur de la prose : `forge_adb.py` (pont ADB) devenait « Immunitaire »
        # parce que sa phrase disait « privilegie/trusted », et `forge_body_world_model`
        # (prediction) tombait dans « Infra ». Une etiquette inventee est pire que pas
        # d'etiquette : elle se propage en RAG, dans les cartes et dans l'atlas, ou plus
        # personne ne peut la distinguer d'une mesure. Mieux vaut un « non classe »
        # honnete, qui appelle une decision humaine.
        decl = DECL_RE.search(_read_head(fname, relpath))
        if decl:
            by_decl = _organ_by_text(decl.group(1), source_is_declaration=True)
            if by_decl:
                return by_decl
    return "? non classe"


def purpose(path):
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        doc = ast.get_docstring(ast.parse(src))
        if doc:
            for line in doc.splitlines():
                line = line.strip()
                if line and not line.startswith(("=", ":", "#", "-")):
                    return line[:120]
        for line in src.splitlines()[:10]:
            s = line.strip()
            if s.startswith("#") and len(s) > 12:
                return s.lstrip("# ")[:120]
    except Exception:
        pass
    return ""


def loc(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    except Exception:
        return 0


def _maj_carte(rows, ws):
    """Ecrit la carte organe->module que 11 organes LISENT et que PLUS RIEN n'ecrivait.

    Mesure 2026-08-28 : `organ_map_full.json` portait 725 entrees et 5,4 jours d'age
    pour 1543 modules recenses, et ses trois pieces generatrices (`module_organ.py`,
    `provenance.py`, `tally.py`) sont une perte prouvee de l'elagage du 12-08. Signal
    sans emetteur : 11 lecteurs (forge_module_cards, forge_self_awareness,
    forge_memoire_active, forge_veille_digest, ...) continuaient de citer
    « 714 organes » sans que rien ne les contredise.

    FUSION, jamais ecrasement : une entree deja presente porte une autorite
    (`keep` / `llm` / humaine) que ce script n'a pas les moyens de reproduire. Il
    AJOUTE seulement ce que ses filets deterministes classent, laisse hors carte
    tout `? non classe` — l'absence EST le signal — et journalise les divergences
    au lieu de trancher a la place de la carte.
    """
    import datetime as _dt

    carte = ws / "organ_map_full.json"
    try:
        data = _json.loads(carte.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- carte absente ou illisible: on la refait
        data = {}
    mo = dict(data.get("module_organ") or {})
    prov = dict(data.get("provenance") or {})
    ajouts, divergences = 0, []
    for path, org, _l, _p in rows:
        if org.startswith("?"):
            continue
        nom = path.split("/")[-1]
        if nom in mo:
            if mo[nom] != org:
                divergences.append((nom, mo[nom], org))
            continue
        mo[nom] = org
        ajouts += 1
    prov["census"] = prov.get("census", 0) + ajouts
    data["module_organ"] = mo
    data["provenance"] = prov
    data["tally"] = dict(Counter(mo.values()).most_common())
    data["generated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    data["generator"] = "tools/forge_module_census.py"
    carte.write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[carte] organ_map_full.json : {len(mo)} entrees (+{ajouts} ce passage), "
          f"{len(divergences)} divergence(s) — carte conservee")
    for nom, ancien, neuf in divergences[:10]:
        print(f"  DIVERGENCE {nom}: carte={ancien} != census={neuf}")
    return len(mo), ajouts, len(divergences)


def _modules():
    """Les modules du corps : app/ puis tools/, hors _attic et tmp_*, en (dossier, Path)."""
    for d in ("app", "tools"):
        base = ROOT / d
        if not base.exists():
            continue
        for f in sorted(base.glob("*.py")):
            if "_attic" in str(f) or f.name.startswith("tmp_"):
                continue
            yield d, f


def _organe_de(d, f):
    # relpath OBLIGATOIRE : sans lui `_read_head` cherche `app/<nom>` puis
    # `tools/<nom>`, et sur un systeme de fichiers insensible a la casse
    # `app/Nokido.py` repond pour `tools/nokido.py` -- mesure 2026-09-06 :
    # nokido.py declarait son organe ligne 22 et restait « non classe »,
    # le census lisait l'homonyme legacy. Le chemin lu doit etre le chemin vu.
    return organ(f.stem, f.name, f"{d}/{f.name}")


def check() -> int:
    """Gate CI en LECTURE SEULE : 0 = tout module app/ et tools/ est classe, 1 sinon.

    Mesure 2026-09-06 : 301 -> 0 non classes en une journee (lots de declarations,
    lecteur et ecrivain accordes sur la meme fenetre). Sans garde, le prochain
    forge_*.py sans declaration ni mot-cle rouvre la breche en silence -- et un
    module non classe est un module que rien ne regule. N'ecrit RIEN : la carte,
    l'inventaire et non_classes.json restent au census complet (`main`).
    """
    total, unc = 0, []
    for d, f in _modules():
        total += 1
        if _organe_de(d, f).startswith("?"):
            unc.append(f"{d}/{f.name}")
    print(f"[anatomie] {total} modules app/ + tools/ lus, {len(unc)} non classe(s)")
    for m in unc:
        print(f"  NON CLASSE  {m}  -> declarer __FORGE_COLOR__ (tools/forge_organ_declare.py)")
    return 1 if unc else 0


def main():
    rows = []
    for d, f in _modules():
        rows.append((f"{d}/{f.name}", _organe_de(d, f), loc(f), purpose(f)))

    by_organ = Counter(r[1] for r in rows)
    ws = ROOT / "sandbox" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    out = ["# Inventaire modules LaForge\n", f"Total: {len(rows)} modules, {sum(r[2] for r in rows)} LOC\n", "## Par organe\n"]
    for org, n in by_organ.most_common():
        out.append(f"- **{org}** : {n} modules, {sum(r[2] for r in rows if r[1]==org)} LOC")
    out.append("\n## Detail (LOC | module | purpose)\n")
    for org, _ in by_organ.most_common():
        out.append(f"\n### {org}")
        for path, o, l, p in sorted([r for r in rows if r[1] == org], key=lambda r: -r[2]):
            out.append(f"- `{path}` ({l}) {('— ' + p) if p else ''}")
    (ws / "module_inventory.md").write_text("\n".join(out), encoding="utf-8")

    s10 = []
    s10.append(f"### Census automatique ({len(rows)} modules / {sum(r[2] for r in rows)//1000}k LOC, `tools/forge_module_census`)\n")
    s10.append("Carte RÉELLE par organe (override organ_map_full.json + fallback keyword) :\n")
    s10.append("| Organe | Mods | LOC | Modules représentatifs (top LOC) |")
    s10.append("|---|---|---|---|")
    for org, n in by_organ.most_common():
        if org.startswith("?"):
            continue
        top = sorted([r for r in rows if r[1] == org], key=lambda r: -r[2])[:7]
        mods = " · ".join(f"`{r[0].split('/')[-1]}`" for r in top)
        lc = sum(r[2] for r in rows if r[1] == org)
        s10.append(f"| {org} | {n} | {lc // 1000}k | {mods} |")
    core = sorted([r for r in rows if r[1].startswith("?")], key=lambda r: -r[2])[:12]
    s10.append(f"| Core/legacy + longue traîne (non-forge) | {sum(1 for r in rows if r[1].startswith('?'))} | {sum(r[2] for r in rows if r[1].startswith('?'))//1000}k | " + " · ".join(f"`{r[0].split('/')[-1]}`" for r in core) + " |")
    (ws / "section10.md").write_text("\n".join(s10), encoding="utf-8")
    _maj_carte(rows, ws)

    print("\n".join(s10))
    print("\n=== STATS ===")
    print(f"TOTAL {len(rows)} modules, {sum(r[2] for r in rows)} LOC")
    for org, n in by_organ.most_common():
        print(f"{n:>4}  {sum(r[2] for r in rows if r[1]==org):>7} LOC  {org}")
    unc = [r[0] for r in rows if r[1].startswith("?")]
    print(f"\nNON CLASSES ({len(unc)}):", unc[:25])
    # La liste COMPLETE, pas les 25 premiers : 301 non-classes le 2026-09-06 et le
    # chantier de declaration (__FORGE_COLOR__) a besoin de chacun d'eux. Un filtre
    # qui ecarte des donnees le dit ; un fichier ecrit vaut mieux qu'un print tronque.
    try:
        _out = ROOT / "sandbox" / "workspace" / "non_classes.json"
        _out.write_text(_json.dumps({"n": len(unc), "modules": unc}, ensure_ascii=False, indent=0),
                        encoding="utf-8")
        print(f"[carte] non_classes.json : {len(unc)} module(s) -> {_out}")
    except OSError as _e:
        print(f"[carte] non_classes.json NON ecrit ({type(_e).__name__}: {_e})")
    return rows


if __name__ == "__main__":
    # `--check` : gate CI en lecture seule (0 = tout classe). Sans drapeau : census complet.
    if "--check" in sys.argv:
        raise SystemExit(check())
    main()
