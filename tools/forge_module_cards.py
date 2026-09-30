"""forge_module_cards.py — Proprioception COMPORTEMENTALE (couche statique).

Pour chaque module app/ + tools/, extrait via AST (deterministe, gratuit, zero
LLM) une carte compacte du COMPORTEMENT reel :
  - API publique (defs/classes non-_private + signatures + decorateurs)
  - effets de bord detectes {db,file,network,subprocess,env,ipc_zmq,llm,hub_http}
  - imports + appels frequents (callees) + entrypoint + async
  - sha source (garde-fou drift)

Plus informatif qu'une glose LLM (qui, sur signal maigre, produit du filler
generique). Regen : `LAFORGE_PYTHON tools/forge_module_cards.py`.
Sortie : sandbox/workspace/module_cards.json (regenerable, ~1.4 MB).

Fraicheur : appeler en post-commit sur les modules changes (diff-only) pour
recalculer seulement leurs cartes (le sha gate). Voir aussi forge_module_census.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "observabilite/anatomy : cartes de modules, proprioception statique"  # organe declare le 2026-09-06 (audit de raccordement)
import ast, json, hashlib, glob, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "sandbox" / "workspace"

# La regle UNIQUE de lecture des docstrings (en-tete machine) vit dans forge_wiki_modules :
# wiki, introspect et fiches RAG la partagent au lieu d'en tenir trois copies.
try:
    from forge_wiki_modules import sans_entete_machine as _sans_entete_machine
except ImportError:  # import en paquet (nokido_agent.tools.*)
    from nokido_agent.tools.forge_wiki_modules import sans_entete_machine as _sans_entete_machine
try:
    ORGAN = json.loads((WS / "organ_map_full.json").read_text(encoding="utf-8")).get("module_organ", {})
except Exception:
    ORGAN = {}
# Verdict d'AUTOREGULATION par module (produit par tools/forge_body_regulation_audit.py).
# La carte dit ce qu'un module FAIT ; ceci dit si le corps le tient : supervise +
# heartbeat, simplement lance, cable par import, invoque par un hook, ou zone morte.
# Lecture d'un cache, jamais un recalcul : cette fonction est appelee apres CHAQUE
# ecriture de fichier (proprioceptive_write -> refresh_changed) et doit rester gratuite.
try:
    REGUL = json.loads((WS / "body_regulation.json").read_text(encoding="utf-8"))
except Exception:
    REGUL = {}
# Definitions grounded (LLM-sur-code) des modules sans docstring, keyees par sha.
try:
    _SUMM = json.loads((ROOT / "tools" / "forge_card_summaries.json").read_text(encoding="utf-8"))
except Exception:
    _SUMM = {}
# Carte precedente : sert a PRESERVER la structure saine d'un module qui vient de
# casser (erreur de syntaxe) plutot que d'ecraser la perception par un blanc.
try:
    _PREV = json.loads((WS / "module_cards.json").read_text(encoding="utf-8"))
except Exception:
    _PREV = {}

# Patterns d'effets de bord : sous-chaine presente dans le source -> tag.
# Precision-first : eviter les generiques (.get/.post matchent dict.get).
EFFECT_PATTERNS = {
    "db":         ("sqlite3", "duckdb", ".execute(", ".commit(", "embeddings.db", "rag_chunks", "connect("),
    "file":       ("open(", ".write_text", ".read_text", "os.remove", "shutil.", "os.makedirs", ".mkdir(", "glob."),
    "network":    ("requests.", "httpx", "aiohttp", "socket.socket", "urllib.request", "websocket", "ClientSession", "urlopen"),
    "subprocess": ("subprocess", "os.system", "Popen", "check_output", "os.popen"),
    "env":        ("os.environ", "os.getenv", "getenv(", "load_dotenv"),
    "ipc_zmq":    ("zmq", ":5557", "DEALER", "msgpack"),
    "llm":        (".ask(", "ollama", "openai", "groq", "litellm", "chat.completions", "generate_content", "call_cascade"),
    "hub_http":   (":8766", "nokido_hub", "_hub_dispatch", "/api/ingest"),
}


def sig_of(fn) -> dict:
    a = fn.args
    names = [ar.arg for ar in (a.posonlyargs + a.args)]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    names += [ar.arg for ar in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    ret = None
    if fn.returns is not None:
        try:
            ret = ast.unparse(fn.returns)[:40]
        except Exception:
            ret = None
    decos = []
    for d in fn.decorator_list:
        try:
            decos.append(ast.unparse(d)[:30])
        except Exception:
            pass
    doc = (ast.get_docstring(fn) or "").strip().split("\n", 1)[0][:100]
    return {"name": fn.name, "args": names[:8], "returns": ret, "deco": decos, "doc": doc,
            "async": isinstance(fn, ast.AsyncFunctionDef)}


def _classify_organ(path: Path, rel: str) -> str:
    """Organe d'un module ABSENT de la carte figee — le code nourrit le corps.

    Sans ce repli, tout module NOUVEAU restait « ? » jusqu'a la prochaine regeneration
    de la carte : cree aujourd'hui, invisible a l'anatomie jusqu'a la nuit suivante.
    Comme `card_for` est rappele apres chaque ecriture (`refresh_changed`), le
    rattachement devient immediat et la carte ne peut plus deriver du code.

    L'autorite reste le census — on ne redecide rien ici.
    """
    try:
        from nokido_agent.tools.forge_module_census import organ as _organ

        return _organ(path.stem, path.name, rel)
    except Exception:  # noqa: BLE001
        return "?"


def card_for(path: Path) -> dict:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"module": path.name, "error": f"read {e}", "health": "unreadable"}
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    out = {
        "module": rel, "organ": ORGAN.get(path.name) or _classify_organ(path, rel),
        "loc": src.count("\n") + 1, "sha": hashlib.sha1(src.encode("utf-8", "replace")).hexdigest()[:12],
        "doc": "", "api": [], "classes": [], "imports": [], "effects": [], "calls_top": [],
        "entrypoint": "__main__" in src, "async": "async def" in src,
    }
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        # NECROSE : le module vient de casser. NE PAS ecraser la derniere carte
        # saine par un blanc (le planner en a besoin pour raisonner l'impact aval).
        # On PRESERVE la structure saine + drapeau nociceptif localise ; healed au
        # prochain parse propre (sha != broken). 3e voie : ni deni, ni amnesie.
        prev = _PREV.get(rel, {})
        for k in ("api", "classes", "imports", "calls_top", "effects", "doc", "summary"):
            if prev.get(k):
                out[k] = prev[k]
        out["health"] = "necrotic"
        out["error"] = f"syntax L{e.lineno}: {(e.msg or '')[:50]}"
        # la structure conservee decrit la version SAINE, pas le fichier casse :
        out["healthy_sha"] = prev.get("healthy_sha") or prev.get("sha")
        return out
    # La docstring ENTIERE (en-tete machine retire), plus seulement sa 1re ligne. Mesure du pilote
    # du 2026-09-29 (fiches RAG, FTS5, 40 requetes) : top 10 de 20 % avec la 1re ligne, 32,5 % avec
    # la docstring entiere -- et 181 fiches portaient « FORGE INTELLIGENCE [BLUE] » en guise de DOC.
    out["doc"] = " ".join(_sans_entete_machine(ast.get_docstring(tree) or "").split())[:1500]

    imports, calls = set(), {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for al in n.names:
                imports.add(al.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            imports.add(n.module.split(".")[0])
        elif isinstance(n, ast.Call):
            nm = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nm:
                calls[nm] = calls.get(nm, 0) + 1
    out["imports"] = sorted(i for i in imports if i)[:30]
    noise = {"len", "str", "int", "list", "dict", "print", "get", "append", "isinstance", "getattr"}
    out["calls_top"] = [k for k, _ in sorted(calls.items(), key=lambda x: -x[1]) if k not in noise][:15]

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out["api"].append(sig_of(node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = [m.name for m in node.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_")]
            out["classes"].append({"name": node.name, "methods": methods[:12],
                                   "doc": (ast.get_docstring(node) or "").split("\n", 1)[0][:100]})
    out["api"] = out["api"][:40]
    out["effects"] = [tag for tag, pats in EFFECT_PATTERNS.items() if any(p in src for p in pats)]
    reg = REGUL.get(path.name)
    if reg:
        out["regulation"] = reg.get("statut", "")
        out["regulation_why"] = reg.get("raison", "")
    # Definition grounded (resume automatique). PERIMEE != MORTE (2026-09-29) : un resume dont le sha
    # ne correspond plus au fichier etait ECARTE en silence -- 19 fiches sur 20 du pilote n'avaient
    # plus aucune description. Il est garde, MARQUE perime ; `forge_card_summarize` le regenere.
    s = _SUMM.get(rel)
    if s and s.get("summary"):
        out["summary"] = s["summary"]
        if s.get("sha") != out["sha"]:
            out["summary_perimee"] = True
    out["health"] = "ok"
    out["healthy_sha"] = out["sha"]
    return out


def build_cards(only: list[str] | None = None) -> dict:
    files = []
    for d in ("app", "tools"):
        for p in glob.glob(str(ROOT / d / "*.py")):
            if "_attic" in p or os.path.basename(p).startswith("tmp_"):
                continue
            files.append(Path(p))
    if only:
        keep = {os.path.basename(o) for o in only}
        files = [f for f in files if f.name in keep]
    return {c["module"]: c for c in (card_for(p) for p in sorted(files))}


DB = str(ROOT / "RAG" / "embeddings.db")


def load_cards() -> dict:
    p = WS / "module_cards.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return build_cards()


def card_text(c: dict) -> str:
    """Aplatit une carte en texte indexable FTS/embeddable."""
    api = "; ".join(
        f'{a["name"]}({",".join(a.get("args", []))})' + (f'->{a["returns"]}' if a.get("returns") else "")
        for a in c.get("api", [])
    )
    cls = "; ".join(f'{k["name"]}{{{",".join(k.get("methods", []))}}}' for k in c.get("classes", []))
    flags = " ".join(f for f, on in (("entrypoint", c.get("entrypoint")), ("async", c.get("async"))) if on)
    necro = f'[NECROSE {c.get("error", "")}] ' if c.get("health") == "necrotic" else ""
    return (
        f'{necro}MODULE {c["module"]} [{c.get("organ", "?")}] | DOC: {c.get("doc", "")} '
        f'| DEF: {"[perimee] " if c.get("summary_perimee") else ""}{c.get("summary", "")} '
        f'| API: {api} | CLASSES: {cls} | EFFECTS: {",".join(c.get("effects", []))} '
        f'| IMPORTS: {",".join(c.get("imports", [])[:15])} | CALLS: {",".join(c.get("calls_top", []))} '
        f'| REGULATION: {c.get("regulation", "?")} ({c.get("regulation_why", "non audite")}) | {flags}'
    ).strip()


def ingest_cards(cards: dict) -> int:
    """Ingere les cartes dans le RAG: rag_chunks (id stable) + rag_fts (recherchable)."""
    import sqlite3, hashlib, time, re
    con = sqlite3.connect(DB, timeout=30)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    for mod, c in cards.items():
        if c.get("health") == "unreadable":
            continue  # fichier illisible : rien a dire. Les NECROSE, elles, sont ingerees (flaggees).
        txt = card_text(c)
        cid = "card_" + hashlib.sha1(("card:" + mod).encode("utf-8")).hexdigest()[:12]
        src = "card/" + mod
        # RELIQUAT P0 WAL (2026-09-23). `DELETE FROM rag_fts WHERE chunk_id=?` balayait
        # la table FTS ENTIERE par carte : `chunk_id` y est UNINDEXED (6,2 Go / 2 min 44 s
        # par commit, mesure au piege). Seul `text` est indexe : on restreint par une
        # phrase de l'ANCIEN texte (lu par cle primaire), l'id reste le filtre exact.
        # Sans ancien texte : carte neuve, ou ligne orpheline laissee — et DITE — a
        # `purge_rag_fts_fantomes` (NREM3). NR : tests/nr/test_module_cards_sans_scan_nr.py
        ancien = con.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
        con.execute(
            "INSERT OR REPLACE INTO rag_chunks (id, source, text, domain, hash, indexed_at, embedding) "
            "VALUES (?,?,?,?,?,?,NULL)",
            (cid, src, txt, "module_card", c.get("sha", ""), now),
        )
        mots = re.findall(r"\w+", (ancien[0] if ancien else "") or "")[:8]
        if mots:
            con.execute("DELETE FROM rag_fts WHERE rowid IN (SELECT rowid FROM rag_fts "
                        "WHERE rag_fts MATCH ? AND chunk_id = ?)", ('"%s"' % " ".join(mots), cid))
        elif ancien:
            print("[cards] %s : ancien texte sans mot exploitable -> ligne FTS laissee a "
                  "purge_rag_fts_fantomes" % cid)
        con.execute("INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?,?,?,?)",
                    (cid, txt, src, "module_card"))
        n += 1
    con.commit()
    con.close()
    return n


def refresh_changed(names: list[str]) -> int:
    """Diff-only: regen + ingest des cartes pour les modules donnes (basenames).

    NECROSE : si un module refresh est casse (syntaxe), card_for garde sa structure
    SAINE + flag la carte, ET on emet ici un signal nociceptif (anchor_error) ->
    l'agent qui a casse le voit a son prochain cycle (read_lessons / self-correction).
    """
    if not names:
        return 0
    cards = load_cards()
    fresh = build_cards(only=names)
    cards.update(fresh)
    WS.mkdir(parents=True, exist_ok=True)
    (WS / "module_cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
    necrotic = [(m, c) for m, c in fresh.items() if c.get("health") == "necrotic"]
    if necrotic:
        try:  # best-effort : la nociception ne doit jamais casser la perception
            import sys as _sys
            if str(ROOT / "app") not in _sys.path:
                _sys.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_self_correction import anchor_error
            for m, c in necrotic:
                anchor_error(
                    error_msg=f"NECROSE {m}: {c.get('error', '')}",
                    context="proprioception: module casse detecte a la regen de carte",
                    solution="corriger la syntaxe ; derniere structure saine preservee dans module_cards.json",
                    domain="systeme",
                )
        except Exception:
            pass
    return ingest_cards(fresh)


def _validate_py(content: str) -> tuple[bool, str]:
    """L0 gate : ast.parse IN-PROCESS (autoritaire pour Python, rapide, pas de
    subprocess/pyc/python3-brut). Erreur CHIRURGICALE : ligne:colonne + nature +
    la ligne source fautive -> la self-correction s'enclenche sur du concret."""
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as e:
        lines = content.splitlines()
        bad = lines[e.lineno - 1].strip()[:80] if e.lineno and e.lineno <= len(lines) else ""
        return False, f"SyntaxError L{e.lineno}:C{e.offset or 0} {e.msg} | >>> {bad}"


def proprioceptive_write(file_path, content: str, *, action: str = "patch", refresh: bool = True) -> dict:
    """Ecriture PROPRIOCEPTIVE (L0 + atomique) pour les agents auto-modifiants.

    1. VALIDE le contenu AVANT de toucher le disque (.py -> ast.parse). KO -> le
       disque n'est JAMAIS touche (pas de fenetre necrotique, rien a rollback).
    2. Ecrit ATOMIQUEMENT : tmp -> fsync -> os.replace (atomique meme FS ; pas de
       fichier a moitie ecrit, pas de torn-read par le hub/autres lecteurs).
    3. Rafraichit la carte ciblee (L1) apres succes.
    Retour: {ok, written, sha} ou {ok:False, written:False, error:<chirurgical>}.
    """
    p = Path(file_path)
    if p.suffix == ".py":
        ok, err = _validate_py(content)
        if not ok:
            return {"ok": False, "written": False, "error": err}  # disque intact
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        with open(tmp, "rb+") as f:
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)  # atomique sur le meme filesystem
    except Exception as e:
        try:
            tmp.unlink()
        except Exception:
            pass
        return {"ok": False, "written": False, "error": f"io: {e}"}
    if refresh:
        try:
            refresh_changed([p.name])  # L1 : perception fraiche, ciblee (+ nociception si necrose)
        except Exception:
            pass
    return {"ok": True, "written": True, "sha": hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()[:12]}


def find(term: str) -> list:
    """Cherche les modules dont effets/calls/texte matchent le terme (ex: 'zmq')."""
    t = term.lower()
    hits = []
    for mod, c in load_cards().items():
        hay = (",".join(c.get("effects", [])) + " " + ",".join(c.get("calls_top", [])) + " " + card_text(c)).lower()
        if t in hay:
            hits.append((mod, c.get("organ", "?"), c.get("effects", [])))
    return sorted(hits)


def _git_changed_py() -> list[str]:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return [os.path.basename(l) for l in r.stdout.splitlines()
                if l.endswith(".py") and (l.startswith("app/") or l.startswith("tools/"))]
    except Exception:
        return []


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Cartes comportementales Nokido (proprioception).")
    ap.add_argument("--ingest", action="store_true", help="build complet + ingest RAG de toutes les cartes")
    ap.add_argument("--changed", nargs="*", metavar="MOD",
                    help="regen+ingest diff-only des modules donnes (vide = auto via git HEAD)")
    ap.add_argument("--find", metavar="TERME", help="liste les modules par effet/call/texte (ex: zmq)")
    a = ap.parse_args()

    if a.find:
        for mod, org, eff in find(a.find):
            print(f"{mod}  [{org}]  effects={','.join(eff)}")
        return
    if a.changed is not None:
        names = a.changed or _git_changed_py()
        n = refresh_changed(names)
        print(json.dumps({"changed": len(names), "ingested": n, "modules": names[:20]}, ensure_ascii=False))
        return

    cards = build_cards()
    WS.mkdir(parents=True, exist_ok=True)
    (WS / "module_cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = {"modules": len(cards), "parse_errors": sum(1 for c in cards.values() if "error" in c),
           "json_kb": round((WS / "module_cards.json").stat().st_size / 1024, 1)}
    if a.ingest:
        msg["ingested_rag"] = ingest_cards(cards)
    print(json.dumps(msg, ensure_ascii=False))


if __name__ == "__main__":
    main()
