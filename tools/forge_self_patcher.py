"""
tools/forge_self_patcher.py — Nokido autonomous self-patching loop.

Flow:
  sandbox/evolution_proposal_*.md
  -> RAG lookup for known solutions
  -> deterministic rules OR LLM patch (laforge-qwen)
  -> write + AST check + pytest
  -> git commit if pass
  -> anchor_solution() + mark proposal applied

Usage:
    LAFORGE_PYTHON tools/forge_self_patcher.py --once [--dry-run]
    LAFORGE_PYTHON tools/forge_self_patcher.py --daemon
"""

import io
import sys

import ast
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

# Homologue biologique (owner 3/11, lu par le census -> la soif en mesure la couverture au corpus de physiologie).
__FORGE_HOMOLOGUE__ = {
    "mecanisme": "consolidation mnesique pendant le sommeil",
    "termes": "sleep memory consolidation hippocampal",
    "sources": ["PMC7046449", "Wilson McNaughton 1994 Science 265:676"],
    "invariant": "a l'eveil aucun candidat n'atteint le juge ; en NREM la file est consolidee, un candidat perime ecarte",
    "nr": "tests/nr/test_rsi_ecrit_au_repos_nr.py",
}

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
# La RACINE aussi : c'est elle qui porte le paquet `nokido_agent`. Lance par chemin (`python tools/...`, le
# superviseur), sys.path ne contient que tools/ -> ModuleNotFoundError avale -> ni HubClient ni coffre -> jeton
# maitre sans nom -> le hub voyait ce demon UNKNOWN ring 4 (mesure 26/10 12:52, ligne « identite : »).
for _p in (str(ROOT), str(APP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HUB_URL = "http://127.0.0.1:8766/mcp"


def _resolve_hub_token() -> str:
    """Token MCP depuis le coffre (source de vérité) puis env en secours.

    Un job détaché n'hérite pas de l'env du hub → 401 sur `ask` (mesuré 22/08).
    get_secret lit le coffre DPAPI, comme forge_auto_evolution_loop.
    """
    # Provenance RETENUE (jamais la valeur) puis dite par main() : cette fonction tourne a l'IMPORT, avant
    # logging.basicConfig -- un message emis ici part dans le vide (26/10 : demon vu UNKNOWN, journal muet).
    global _PROVENANCE_JETON
    try:
        from nokido_agent.app.forge_hub_client import HubClient
        global _HUB_CLIENT
        _HUB_CLIENT = HubClient(agent="SELF_PATCHER")  # propre ou bail ; repli maitre dit
        try:
            # 30/10 (journal du coffre, job_fce6a9f71bd4) : _jeton_courant() declenchait le repli tardif et LISAIT le
            # coffre pour une simple etiquette ; en voie d'echange, la provenance est dite sans rien lire.
            if getattr(_HUB_CLIENT, "_echange_job", False):
                _PROVENANCE_JETON = "HubClient SELF_PATCHER, echange_job (RFC 8693, aucun secret lu)"
            else:
                _PROVENANCE_JETON = "HubClient SELF_PATCHER, " + _HUB_CLIENT._jeton_courant()[1]
        except Exception as e:  # noqa: BLE001 - la provenance illisible est dite, elle aussi
            _PROVENANCE_JETON = "HubClient SELF_PATCHER, provenance ILLISIBLE (%s)" % type(e).__name__
        return _HUB_CLIENT.token
    except Exception as e:  # noqa: BLE001
        _PROVENANCE_JETON = "forge_hub_client indisponible (%s)" % type(e).__name__
    try:
        from nokido_agent.app.forge_secrets import get_secret
        tok = get_secret("FORGE_MCP_TOKEN")
        if tok:
            _PROVENANCE_JETON += " -> repli coffre:FORGE_MCP_TOKEN (sans nom d'agent)"
            return tok
    except Exception as e:  # noqa: BLE001
        _PROVENANCE_JETON += " -> coffre indisponible (%s)" % type(e).__name__
    tok_env = os.getenv("FORGE_MCP_TOKEN", "")  # UNE lecture hors guichet (repli historique, cliquet 26/10)
    _PROVENANCE_JETON += " -> repli env FORGE_MCP_TOKEN" + ("" if tok_env else " (VIDE : aucun jeton)")
    return tok_env


def _dire_identite() -> None:
    """Dit au journal avec quel jeton le patcher se presente au hub (appele par main, journal configure)."""
    logger.info(f"[patcher] identite : {_PROVENANCE_JETON}")


_HUB_CLIENT = None
_PROVENANCE_JETON = "non resolue"
HUB_TOKEN = _resolve_hub_token()
def _interpreteur() -> str:
    """Interpreteur des rejeux de tests, qui EXISTE quel que soit le compte du service. 3/11 : expanduser("~/...") se
    resolvait dans le profil du compte EXECUTANT -> FileNotFoundError a chaque rejeu F2P, 5 propositions « illisibles »
    a chaque cycle, 0 patch (NR tests/nr/test_rsi_interpreteur_existe_nr.py). Ordre : reference du depot
    (forge_python_bin), profil courant, puis l'interpreteur qui fait tourner CE processus."""
    import os as _os
    import sys as _sys
    existants = [c for c in _candidats_interpreteur() if c and _os.path.exists(c)]
    # 3/11 23 h 30 : exister ne suffit pas -- un python SANS pytest rendait rc=1 en ~40 ms, lu « rouge ». Le premier
    # candidat qui sait IMPORTER pytest gagne ; aucun -> le premier existant (le rejeu le dira illisible).
    return next((c for c in existants if _a_pytest(c)), existants[0] if existants else _sys.executable)


def _candidats_interpreteur() -> list:
    """Reference du depot (forge_python_bin), profil courant, puis l'interpreteur de CE processus."""
    import os as _os
    import sys as _sys
    out = []
    try:
        from forge_python_bin import LAFORGE_PYTHON as _ref
        out.append(str(_ref))
    except Exception:  # noqa: BLE001 - muet-ok : reference absente, on tente les suivants
        pass
    # 3/11 23 h 41 (cycle 0 prouve) : sous le compte du SERVICE, forge_python_bin et sys.executable designent
    # envs\nokido_services (sans pytest) et ~ n'est pas le profil owner. Le python de BASE de miniforge est derive de
    # l'emplacement du depot (ROOT = <dossier utilisateur>/Script python IA/Nokido), sans chemin en dur.
    _base = str(ROOT.parents[1] / "miniforge3" / "python.exe")
    return out + [_os.path.expanduser(r"~/miniforge3/python.exe"), _base, _sys.executable]


def _a_pytest(exe: str) -> bool:
    """L'interpreteur `exe` sait-il importer pytest ? (une sonde, au demarrage du demon)."""
    try:
        return subprocess.run([exe, "-c", "import pytest"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


LAFORGE_PY = _interpreteur()

PROPOSALS_DIR = ROOT / "sandbox"
APPLIED_DIR = ROOT / "sandbox" / "patch_applied"
HEARTBEAT = ROOT / "sandbox" / "self_patcher.heartbeat"
# RSI au repos (owner 3/11, option 1 « genere tout le temps, ecrit au repos »). Le juge ecrit le candidat dans l'arbre
# VIVANT partage : hors sommeil, le candidat attend ici. Consolidation = phases NREM (Wilson & McNaughton 1994 ;
# PMC7046449, veille au RAG). Transe de guerison = cytokine a TTL, lue par la soif (lethargie) et par le RSI.
FILE_REPOS = ROOT / "sandbox" / "self_patcher_file_repos.jsonl"
FILE_REPOS_MAX = 50
CYTOKINE_RSI = "CYTOKINE_RSI"
TRANSE_TTL_S = int(os.environ.get("LAFORGE_RSI_TRANSE_TTL_S", "1800"))
PHASES_CONSOLIDATION = ("NREM1", "NREM3")
STATE_FILE = ROOT / "sandbox" / "self_patcher_state.json"
INTERVAL_S = 3600  # 1h daemon cycle

SAFE_DIRS = ["app", "tools"]
BLOCKED_FILES = {
    "tools/nokido_hub.py",
    "tools/forge_self_patcher.py",
    "app/forge_semantic_firewall.py",
    "app/forge_integrity.py",
    "app/forge_sovereign_membrane.py",
    "app/forge_prompt_guard.py",
}
MAX_PATCH_LINES = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Nokido.SelfPatcher] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("Nokido.SelfPatcher")


# ── Deterministic rules ────────────────────────────────────────────────────

# Unicode chars that crash cp1252 NSSM stdout — replace with ASCII equivalents
_CP1252_MAP = {
    "→": "->",  # →
    "←": "<-",  # ←
    "↑": "^",  # ↑
    "↓": "v",  # ↓
    "✓": "[OK]",  # ✓
    "✗": "[X]",  # ✗
    "✔": "[OK]",  # ✔
    "✘": "[X]",  # ✘
    "★": "*",  # ★
    "▶": ">",  # ▶
    "●": "*",  # ●
}


def _rule_cp1252(fp: Path) -> tuple[str, str] | None:
    """Replace Unicode display chars with ASCII equivalents."""
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        # ILLISIBLE n'est pas SAIN. Sans cette trace, un fichier qu'on n'a PAS
        # PU lire se compte comme un fichier sans defaut : la regle se tait
        # dessus pour toujours, et le patcher se croit a jour.
        logger.warning("regle cp1252 : %s illisible (%s)", fp, type(exc).__name__)
        return None
    patched = text
    for ch, rep in _CP1252_MAP.items():
        patched = patched.replace(ch, rep)
    if patched != text:
        return text, patched
    return None


def _rule_missing_utf8_stdout(fp: Path) -> tuple[str, str] | None:
    """Add utf-8 stdout reconfigure if file has print/logging but no TextIOWrapper."""
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        # Meme defaut, meme remede : « pas de patch a proposer » et « je n'ai
        # pas pu regarder » doivent cesser de rendre la meme valeur.
        logger.warning("regle stdout utf-8 : %s illisible (%s)", fp,
                       type(exc).__name__)
        return None
    # Only patch daemon scripts with --daemon or main()
    if "--daemon" not in text and "def main" not in text:
        return None
    if "TextIOWrapper" in text or "PYTHONIOENCODING" in text:
        return None
    # Only if file has print/log calls
    if "print(" not in text and "logger." not in text:
        return None
    inject = (
        "import sys as _sys, io as _io\n"
        'if hasattr(_sys.stdout, "buffer"):\n'
        "    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, "
        'encoding="utf-8", errors="replace")\n'
    )
    # Insert after first docstring or first import
    lines = text.splitlines(keepends=True)
    insert_at = 0
    in_docstring = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith('"""'):
            in_docstring = True
        if in_docstring:
            if i > 0 and '"""' in stripped:
                insert_at = i + 1
                in_docstring = False
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = i
            break
    if insert_at == 0:
        return None
    patched_lines = lines[:insert_at] + [inject] + lines[insert_at:]
    patched = "".join(patched_lines)
    if patched == text:
        return None
    return text, patched


# Maps pattern keyword -> rule function
DETERMINISTIC_RULES: dict[str, callable] = {
    "cp1252": _rule_cp1252,
    "unicodeencodeerror": _rule_cp1252,
    "charmap codec": _rule_cp1252,
    "character maps to <undefined>": _rule_cp1252,
    "pythonioencoding": _rule_missing_utf8_stdout,
}


# ── Hub / RAG helpers ──────────────────────────────────────────────────────


def _hub_call(tool: str, args: dict, timeout: int = 90) -> dict:
    import urllib.request as _r

    # `id` OBLIGATOIRE : sans lui c'est une NOTIFICATION JSON-RPC, acceptee par le serveur MCP avec un corps
    # VIDE -- le patcher n'a jamais recu de reponse du modele par cette voie (mesure 25/10 15:40).
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": args,
            },
        }
    ).encode()
    # 30/10 (option B owner, mesure reelle du journal du coffre) : voie d'echange armee -> l'appel passe par HubClient
    # (echange RFC 8693 pour la portee exacte, DPoP), plus par des en-tetes Bearer construits ici (relecture du coffre).
    # Le client est cree au CHARGEMENT du module : l'environnement est relu a l'appel (un import fait sous un jeton de
    # job ne doit pas armer l'echange d'un appel qui n'en a plus).
    try:
        from nokido_agent.app.forge_agent_credential import jeton_sujet_du_job as _jsj
    except ImportError:  # repli checkout
        from forge_agent_credential import jeton_sujet_du_job as _jsj
    if (_HUB_CLIENT is not None and getattr(_HUB_CLIENT, "_echange_job", False)
            and _jsj() and os.environ.get("NOKIDO_JOB_ID")):
        r = _HUB_CLIENT.appel_outil(tool, args, timeout=timeout)
        return r if r is not None else {"error": "reponse vide ou illisible du hub, ou appel refuse "
                                                 "(voir le journal hub_client)"}
    headers = {"Content-Type": "application/json"}
    if _HUB_CLIENT is not None:
        headers = _HUB_CLIENT.entetes_repli_env()
    elif HUB_TOKEN:
        headers["Authorization"] = f"Bearer {HUB_TOKEN}"
    try:
        req = _r.Request(HUB_URL, data=payload, headers=headers)
        with _r.urlopen(req, timeout=timeout) as r:
            corps = r.read()
        if not corps.strip():
            return {"error": "reponse vide du hub (notification JSON-RPC ou corps absent)"}
        return json.loads(corps)
    except Exception as e:
        return {"error": str(e)}


def _rag_lookup(pattern: str) -> str:
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(pattern, "fix patch solution")
        results = v.get("results", [])
        if results and float(results[0].get("score", 0)) > 0.5:
            return results[0].get("preview", "")
    except Exception as e:
        logger.debug(f"[patcher] RAG lookup indisponible ({e}) — patch sans contexte de solutions connues")
    return ""


# ── LLM patch generation ───────────────────────────────────────────────────

_LLM_PROMPT = """\
You are a Python code patcher. Output ONLY valid JSON.

Recurring error patterns detected in Nokido logs:
{errors}

{rag_ctx}

Rules:
- target_file MUST be in app/ or tools/
- patch_search must be exact string present in file (include surrounding context)
- patch_replace must be < 20 lines
- Only fix the pattern above — no refactoring

Output format (JSON only, no explanation):
{{"target_file":"app/forge_example.py","description":"one line what was fixed","patch_search":"exact code to replace","patch_replace":"new code"}}
Or if no safe fix exists: {{"target_file":null,"reason":"why"}}"""


_RE_REFUS_HUB = re.compile(r"^\s*(ERR\b|ERREUR\b|\[Hub\] Erreur)|GATE DENY|ring\s*\d+\s*<=\s*requis", re.I)


def _extraire_rel(text: str) -> dict | None:
    """Bloc REL (```json``` portant error_id) d'une proposition, ou None si elle n'en porte pas."""
    for m in re.finditer(r"```json\s*(.*?)```", text, re.DOTALL):
        try:
            d = json.loads(m.group(1))
        except ValueError:  # muet-ok : un bloc json illisible n'est pas un REL, le suivant est examine
            continue
        if isinstance(d, dict) and "error_id" in d and "pointer_ref" in d:
            return d
    return None


def _corps_fonction(rel_file: str, function: str) -> str | None:
    """Source de la fonction pointee, lue par ast dans pointer_ref.file ; None si introuvable."""
    try:
        src = (ROOT / rel_file).read_text(encoding="utf-8", errors="replace")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
                return "\n".join(src.splitlines()[node.lineno - 1 : node.end_lineno])
    except (OSError, SyntaxError):  # muet-ok : None est DIT par _contexte_rel (« corps introuvable »)
        pass
    return None


def _contexte_rel(rel: dict) -> str:
    ptr = rel["pointer_ref"]
    corps = _corps_fonction(ptr["file"], ptr.get("function") or "")
    ev = rel.get("evidence", {})
    return (
        "\nREL (rapport d'erreur localise) :\n%s\n"
        "Fonction pointee (%s:%s) :\n%s\n"
        "Le correctif DOIT viser target_file = %s.\n"
        % (json.dumps({"error_id": rel["error_id"], "pointer_ref": ptr, "message": ev.get("message", ""),
                       "trace": ev.get("trace", [])}, ensure_ascii=False)[:3000],
           ptr["file"], ptr.get("line"), corps if corps else "(corps introuvable)", ptr["file"])
    )


# CONTRAT FAIL-TO-PASS (26/10, roadmap_p1_self_patcher_f2p_et_raffinement_20261026) : le test ROUGE du REL est
# rejoue AVANT la generation (deja vert = rien a reparer ; illisible = en attente, UNKNOWN != NO), puis passe au
# thymus avec les tests du module : un correctif qui ne le fait pas passer MEURT.
# Verdicts qui laissent le candidat dans l'arbre en attente du commit owner. Le juge a gain (juger_module_avec_gain,
# raccorde le 08/09) ne rend JAMAIS « SURVIT » en verdict final : tester ce seul mot rendait la branche succes MORTE.
VERDICTS_RETENUS = ("SURVIT", "AMELIORE")


def _test_du_rel(rel: dict) -> str | None:
    """nodeid pytest du test rouge d'un REL (`error_id` junit « tests.nr.test_x.TestA::test_y ») ; None si introuvable."""
    classname, sep, nom = str(rel.get("error_id") or "").partition("::")
    parts = [p for p in classname.split(".") if p]
    if not sep or not nom or not parts:
        return None
    for k in range(len(parts), 0, -1):
        chemin = "/".join(parts[:k]) + ".py"
        if (ROOT / chemin).is_file():
            return "::".join([chemin, *parts[k:], nom])
    return None


def _localiser_par_imports(test_f2p) -> dict | None:
    """3/11 (owner, « par les imports du test ») : un REL dont la trace ne passe par aucun fichier app/tools (l'assertion
    tombe DANS le test) est localise par le module forge_* que le test IMPORTE -- s'il est UNIQUE et existe dans app/ ou
    tools/. Plusieurs candidats, aucun, test illisible : None (la proposition reste en attente, c'est dit).
    NR tests/nr/test_rsi_localisation_par_imports_nr.py."""
    try:
        chemin = str(test_f2p or "").split("::", 1)[0]
        if not chemin:
            return None
        arbre = ast.parse((ROOT / chemin).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    noms = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            noms.update(a.name.rsplit(".", 1)[-1] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            noms.add(n.module.rsplit(".", 1)[-1])
    candidats = []
    for m in sorted(noms):
        if not m.startswith("forge_"):
            continue
        for d in ("app", "tools"):
            if (ROOT / d / ("%s.py" % m)).is_file():
                candidats.append("%s/%s.py" % (d, m))
                break
    return {"file": candidats[0], "par": "imports du test"} if len(candidats) == 1 else None


def _rel_deja_vert(nodeid: str) -> bool | None:
    """Le test du REL passe-t-il DEJA ? True vert, False rouge, None illisible (collecte, delai, interruption)."""
    try:
        r = subprocess.run([LAFORGE_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", nodeid],
                           cwd=ROOT, capture_output=True, text=True, timeout=300, errors="replace",
                           env={**os.environ, "PYTHONNOUSERSITE": "1"})
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"[patcher] test du REL {nodeid} non rejoue ({type(e).__name__}) : illisible")
        return None
    # 3/11 23 h 30 : rc=1 n'est « rouge » que si un test a REELLEMENT echoue. pytest absent, erreur de collecte,
    # aucun test lance -> illisible (UNKNOWN != NO), jamais rouge. NR tests/nr/test_rsi_rejeu_illisible_nr.py.
    sortie = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0:
        return True
    fin = " | ".join(sortie.strip().splitlines()[-2:])[:200]
    if r.returncode == 1 and re.search(r"\b\d+ failed\b|^FAILED ", sortie, re.M) \
            and not re.search(r"No module named pytest|error(s)? in|ImportError while loading|no tests ran", sortie):
        logger.info(f"[patcher] test du REL {nodeid} ROUGE (rc=1) : {fin}")
        return False
    logger.warning(f"[patcher] test du REL {nodeid} ILLISIBLE (rc={r.returncode}, rien d'execute) : {fin}")
    return None


# GENERATION du correctif (owner 26/10 : « si laforge-qwen est trop bete, un modele fort ») : cascade de fournisseurs,
# le fort GRATUIT d'abord (groq = gpt-oss-120b, ~200 000 jetons/jour), le local en repli. Le JUGE, lui, reste le
# thymus deterministe (tests, import reel, gain) : aucun modele ne vote sur la survie d'un correctif.
# 3/11 (owner « reparer Nemotron Super ») : le fort gratuit PROUVE en tete -- nemotron-3.5-super-vl-120b (NVIDIA NIM,
# code correct en 1,8 s, accepte par `ask`, job_87516ee25c57 ; quota libre 40 RPM / ~1000 appels par mois). Avec
# « groq,ollama » seuls, la relance des bancs du 3/11 a rendu 0 amelioration sur 4 bancs.
# 3/11 (owner « utilise lmstudio pour tes appels aussi ») : LM Studio (local, ttl de dechargement) AVANT Ollama, dont le
# moteur est absent ce jour (HTTP 500 « llama-server binary not found »).
_PATCHER_PROVIDERS_DEFAUT = "nvidia_nemotron_super,groq,lmstudio,ollama"


def _ask_cascade(prompt: str) -> tuple:
    """(texte, None) du premier fournisseur qui repond vraiment, sinon (None, dernier echec)."""
    echec = "aucun fournisseur"
    for prov in [p.strip() for p in os.environ.get("LAFORGE_PATCHER_PROVIDERS", _PATCHER_PROVIDERS_DEFAUT).split(",")
                 if p.strip()]:
        args = {"provider": prov, "message": prompt, "max_tokens": 1500 if prov != "ollama" else 400}
        resp = _hub_call("ask", args)
        if resp.get("error"):
            echec = "%s: %s" % (prov, str(resp["error"])[:160])
            logger.warning(f"[patcher] hub ask en échec ({echec}) -- fournisseur suivant")
            continue
        text = (resp.get("result", {}).get("content", [{}]) or [{}])[0].get("text", "")
        if not text:
            echec = "%s: reponse vide ou inattendue" % prov
            logger.warning(f"[patcher] hub ask réponse vide/inattendue ({prov}): {str(resp)[:160]}")
            continue
        if _RE_REFUS_HUB.search(text[:200]):
            # Un REFUS du hub (ring, videur, gate) arrive comme texte : ce n'est pas une reponse du modele
            # (mesure 26/10 : « GATE DENY tool=ask agent=UNKNOWN », 36 caracteres en 60 ms, 3 propositions perdues).
            echec = "%s: refus du hub : %s" % (prov, text[:120])
            logger.warning(f"[patcher] hub ask REFUSE ({prov}): {text[:160]}")
            continue
        logger.info(f"[patcher] correctif genere par {prov} ({len(text)} c)")
        return text, None
    return None, echec


def _llm_generate_patch(patterns: list[str], rag_ctx: str, rel_ctx: str = "") -> dict | None:
    errors = "\n".join(f"- {p}" for p in patterns[:4])
    ctx = f"\nExisting solution:\n{rag_ctx[:400]}" if rag_ctx else ""
    prompt = _LLM_PROMPT.format(errors=errors, rag_ctx=ctx) + rel_ctx

    text, echec = _ask_cascade(prompt)
    if text is None:
        return {"echec_amont": echec[:200]}
    try:
        m = re.search(r'\{[^{}]*"target_file"[^{}]*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        logger.info(f"[patcher] LLM a répondu sans spec target_file (len={len(text)})")
    except Exception as e:
        logger.warning(f"[patcher] LLM parse fail: {e}")
    return None


# ── Patch application ──────────────────────────────────────────────────────


def _safe_check(rel: str) -> str | None:
    """Return error string if file is not safe to patch, else None."""
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in BLOCKED_FILES:
        return f"blocked: {rel}"
    if not any(rel.startswith(d + "/") or rel.startswith(d) for d in SAFE_DIRS):
        return f"out of scope: {rel}"
    return None


def _apply_search_replace(fp: Path, search: str, replace: str,
                          max_lines: int = MAX_PATCH_LINES) -> tuple[bool, str]:
    """Search/replace in file. Return (ok, original_text_or_error).

    `max_lines` (2/11) : le plafond par defaut (30) garde les AUTO-modifications du depot ; un banc d'amelioration sur
    une copie isolee de code EXTERNE peut declarer le sien (`max_lignes_patch`). NR test_banc_goulot_conjoint_plafond_nr.
    """
    if len(replace.splitlines()) > max_lines:
        return False, f"patch too large ({len(replace.splitlines())} lines)"
    try:
        original = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, str(e)
    if search not in original:
        return False, "search string not found in file"
    patched = original.replace(search, replace, 1)
    try:
        ast.parse(patched)
    except SyntaxError as e:
        return False, f"AST fail: {e}"
    fp.write_text(patched, encoding="utf-8")
    return True, original


def _run_quality_gate(fp: Path) -> tuple[bool, str]:
    """AST + pylint >= 6.0. Returns (ok, msg)."""
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
        ast.parse(text)
    except SyntaxError as e:
        return False, f"AST: {e}"
    # Try pylint (score >= 6.0 threshold — lenient for auto-patches)
    try:
        r = subprocess.run(
            [LAFORGE_PY, "-m", "pylint", str(fp), "--score=y", "-E", "--disable=all", "--enable=E"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        errors="replace")
        if r.returncode > 1:  # 0=ok, 1=warnings, 2+=errors
            return False, f"pylint errors: {r.stdout[-300:]}"
    except Exception:  # muet-ok: pylint optionnel — le thymus reste le juge
        pass
    return True, "ok"


def _run_tests(target_rel: str) -> tuple[bool, str]:
    """Run pytest test file for target if it exists. Return (passed, msg)."""
    stem = Path(target_rel).stem
    candidates = [
        ROOT / "tests" / f"test_{stem}.py",
        ROOT / "tests" / "nr" / f"test_{stem}_nr.py",
    ]
    test_file = next((t for t in candidates if t.exists()), None)
    if not test_file:
        return True, "no test file — AST-only"

    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(ROOT),
    }
    r = subprocess.run(
        [
            LAFORGE_PY,
            "-m",
            "pytest",
            str(test_file),
            "-x",
            "-q",
            "-p",
            "no:cacheprovider",
            "--tb=short",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    errors="replace")
    if r.returncode == 0:
        return True, r.stdout[-200:]
    return False, (r.stdout + r.stderr)[-400:]


def _git_commit(files: list[str], description: str) -> bool:
    """DESARME le 2026-10-01 (revue claude.ai mission_rsi_soif, verifiee) : faisait `git add`,
    `git commit` puis `git push origin alpha` DIRECTEMENT dans l'arbre partage -- sans juge, sans
    claim, et publiait. Aucun appelant ce jour-la. Un patch autonome passe par un worktree et le
    merge gate (`forge_merge_gate.merger`, zone de l'evaluateur appliquee) ; publier est une
    decision OWNER (push global), jamais un geste d'organe. Le corps d'origine est dans git
    (avant ce commit). Refus DIT, jamais un faux succes."""
    logger.warning("[patcher] _git_commit DESARME : %d fichier(s) NON commites (%s) -- passer par "
                   "le merge gate en worktree ; le push reste une decision owner",
                   len(files or []), (description or "")[:80])
    return False


# ── Deterministic batch scan ───────────────────────────────────────────────


def _submit_to_judge(ref: str, rel: str, new_text: str, desc: str, test_f2p: str | None = None) -> dict:
    """Soumet le candidat au thymus (mutation_judge via forge_autonomous_loops).

    Le judge porte verrou, périmètre immuable, patron sain, récidive, import réel,
    tests ciblés et RESTAURATION ; SURVIT laisse le working tree modifié et la
    promotion reste le COMMIT OWNER (inhibition corticale). Thymus injoignable =
    refus fail-closed : jamais d'application directe en secours.
    """
    import sys as _sys

    tests = [test_f2p] if test_f2p else []  # le test rouge du REL d'abord : le faire passer EST le correctif
    if test_f2p:
        # Des tests EXPLICITES font sauter `perimetre_mesure` cote juge : on le joint ici, sinon le seul test F2P
        # perdrait la non-regression (P2P) des autres tests du module.
        try:
            from nokido_agent.app.forge_mutation_judge import perimetre_mesure

            tests += [t for t in perimetre_mesure(rel) if t not in tests]
        except Exception as e:  # noqa: BLE001 - perimetre illisible : F2P seul, et on le DIT
            logger.warning(f"[patcher] perimetre de {rel} illisible ({type(e).__name__}) : juge sur le seul test F2P")
    stem = Path(rel).stem
    cand_test = ROOT / "tests" / f"test_{stem}.py"
    if cand_test.exists():
        tests.append(f"tests/test_{stem}.py")
    try:
        _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_autonomous_loops import submit_candidate_to_judge
    except Exception as e:
        logger.warning(f"[patcher] thymus injoignable ({e}) — candidat NON appliqué ({rel})")
        return {"status": "BLOCKED", "verdict": "REFUSE", "pourquoi": f"thymus injoignable: {e}"}
    out = submit_candidate_to_judge(ref, rel, new_text, tests or None)
    logger.info(f"[patcher] thymus {rel}: {out.get('verdict')} -> {out.get('status')} ({desc[:60]})")
    return out


def _phase_courante() -> str:
    from nokido_agent.app.forge_circadian import current_phase

    return current_phase().value


def _ram_en_satiete() -> bool:
    """Le predicat de satiete du CORPS (celui des chaines de veille et de la soif) : un seul seuil."""
    from nokido_agent.app.forge_chain_executor import _ram_en_satiete as _sat

    return bool(_sat())


def _cytokine_active() -> bool:
    try:
        import importlib as _il

        return float(_il.import_module("nokido_agent.app.forge_endocrine").read(CYTOKINE_RSI) or 0.0) > 0.0
    except Exception as e:  # noqa: BLE001 - illisible = pas de transe : la regle de phase s'applique (fail-closed)
        logger.warning(f"[patcher] cytokine {CYTOKINE_RSI} illisible ({type(e).__name__}) : regle de phase seule")
        return False


def _mutation_autorisee() -> tuple:
    """(autorise, raison). Muter l'arbre : transe declaree, OU sommeil NREM hors satiete RAM. Phase ou RAM illisible =
    pas de mutation : muter au mauvais moment coute plus qu'attendre un cycle (couts asymetriques)."""
    if _cytokine_active():
        return True, "transe de guerison (%s active)" % CYTOKINE_RSI
    try:
        phase = _phase_courante()
    except Exception as e:  # noqa: BLE001 - dit dans la raison
        return False, "phase circadienne illisible (%s) : pas de mutation" % type(e).__name__
    if phase not in PHASES_CONSOLIDATION:
        return False, "eveil (phase %s) : consolidation en %s" % (phase, "/".join(PHASES_CONSOLIDATION))
    try:
        if _ram_en_satiete():
            return False, "sommeil (phase %s) mais RAM en satiete" % phase
    except Exception as e:  # noqa: BLE001 - dit dans la raison
        return False, "satiete RAM illisible (%s) : pas de mutation" % type(e).__name__
    return True, "sommeil (phase %s)" % phase


def _sha_fichier(rel: str):
    import hashlib

    try:
        return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    except OSError:
        return None


def _lire_file_repos() -> list:
    try:
        return [json.loads(l) for l in FILE_REPOS.read_text(encoding="utf-8").splitlines() if l.strip()]
    except FileNotFoundError:  # muet-ok : pas de file = rien en attente
        return []
    except (OSError, ValueError) as e:
        logger.warning(f"[patcher] file de repos illisible ({type(e).__name__}) : consideree vide, NON ecrasee")
        raise


def _ecrire_file_repos(entrees: list) -> None:
    FILE_REPOS.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE_REPOS.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entrees), encoding="utf-8")
    os.replace(tmp, FILE_REPOS)


def _soumettre_ou_differer(ref: str, rel: str, new_text: str, desc: str, test_f2p: str | None = None) -> dict:
    """Seul passage vers le juge depuis le cycle : au repos il juge, a l'eveil le candidat attend (DIFFERE_REPOS),
    arbre intact. Un meme (ref, rel) remplace son ancien candidat ; file bornee."""
    ok, raison = _mutation_autorisee()
    if ok:
        return _submit_to_judge(ref, rel, new_text, desc, test_f2p)
    try:
        entrees = [e for e in _lire_file_repos() if not (e.get("ref") == ref and e.get("rel") == rel)]
    except (OSError, ValueError):
        return {"status": "BLOCKED", "verdict": "REFUSE", "pourquoi": "file de repos illisible : candidat non range"}
    entrees.append({"ts": time.time(), "ref": ref, "rel": rel, "desc": desc, "test_f2p": test_f2p,
                    "sha_source": _sha_fichier(rel), "new_text": new_text})
    _ecrire_file_repos(entrees[-FILE_REPOS_MAX:])
    logger.info(f"[patcher] candidat {rel} DIFFERE au repos ({raison}) -- {len(entrees)} en file")
    return {"status": "DIFFERE_REPOS", "verdict": "DIFFERE", "pourquoi": raison}


def consolider() -> dict:
    """Sommeil (ou transe) : la file passe au juge. Un candidat dont le fichier a change depuis sa generation est
    PERIME (la consolidation integre au cadre EXISTANT, arXiv 2602.04095) : jamais applique sur un autre texte."""
    r = {"jugees": 0, "survit": 0, "perimees": 0, "restantes": 0}
    try:
        entrees = _lire_file_repos()
    except (OSError, ValueError):
        r["motif"] = "file de repos illisible"
        return r
    if not entrees:
        return r
    ok, raison = _mutation_autorisee()
    if not ok:
        r.update(restantes=len(entrees), motif=raison)
        return r
    for e in entrees:
        if _sha_fichier(e.get("rel", "")) != e.get("sha_source"):
            r["perimees"] += 1
            logger.info(f"[patcher] candidat {e.get('rel')} PERIME : fichier modifie depuis sa generation")
            continue
        out = _submit_to_judge(e["ref"], e["rel"], e["new_text"], e.get("desc", ""), e.get("test_f2p"))
        r["jugees"] += 1
        if out.get("verdict") in VERDICTS_RETENUS:
            r["survit"] += 1
    _ecrire_file_repos([])
    logger.info(f"[patcher] consolidation ({raison}) : {r}")
    return r


def transe_de_guerison(dry_run: bool = False, attente_max_s: int = 600, pas_s: int = 10, _dormir=time.sleep) -> dict:
    """Declenchement a la demande (owner 3/11) : cytokine a TTL (lethargie de la soif, mutation autorisee), attente
    que la RAM sorte de satiete (sans tuer quoi que ce soit), consolidation + un cycle, cytokine TOUJOURS eteinte."""
    import importlib as _il

    _en = _il.import_module("nokido_agent.app.forge_endocrine")
    _en.release(CYTOKINE_RSI, 1.0, ttl_s=TRANSE_TTL_S, source="self_patcher:transe",
                reason="transe de guerison a la demande : soif en lethargie, mutation autorisee")
    try:
        attendu = 0
        while _ram_en_satiete() and attendu < attente_max_s:
            _dormir(pas_s)
            attendu += pas_s
        if _ram_en_satiete():
            return {"transe": "ABANDONNEE", "motif": "RAM restee en satiete %d s : aucune mutation" % attendu}
        cons = consolider()
        stats = run_once(dry_run=dry_run)
        stats["consolidation"] = cons
        stats["transe"] = "FAITE"
        return stats
    finally:
        _en.release(CYTOKINE_RSI, 0.0, source="self_patcher:transe", reason="fin de transe")


def _batch_deterministic(rule_fn, rule_name: str, dry_run: bool) -> list[str]:
    """Apply a deterministic rule across all safe Python files. Return list of patched rels."""
    patched = []
    py_files = list((ROOT / "app").glob("*.py")) + list((ROOT / "tools").glob("*.py"))
    for fp in tqdm(py_files, desc=f"rule:{rule_name}", unit="file", leave=False):
        rel = str(fp.relative_to(ROOT)).replace("\\", "/")
        if _safe_check(rel):
            continue
        result = rule_fn(fp)
        if not result:
            continue
        _original, new_text = result
        if dry_run:
            logger.info(f"[patcher] DRY-RUN {rule_name}: {rel}")
            patched.append(rel)
            continue
        # Thymus : le judge porte AST, gates, tests et restauration — plus
        # d'écriture directe depuis le patcher.
        out = _soumettre_ou_differer(f"rule:{rule_name}", rel, new_text, rule_name)
        if out.get("verdict") in VERDICTS_RETENUS:
            logger.info(f"[patcher] SURVIT {rel} ({rule_name}) — promotion = commit owner")
            patched.append(rel)
    return patched


# ── Main cycle ─────────────────────────────────────────────────────────────


def _pertinence() -> dict:
    """Taux de pertinence du self-patcher (candidats tranches par l'owner) ; ILLISIBLE n'arrete rien."""
    try:
        from nokido_agent.app.forge_motivation import taux_pertinence

        return taux_pertinence("SELF_PATCHER")
    except Exception as e:  # noqa: BLE001 - mesure illisible : on ne coupe pas sur une non-mesure
        return {"statut": "ILLISIBLE", "raison": type(e).__name__}


# RAFFINEMENT (26/10, roadmap_p1_self_patcher_f2p_et_raffinement_20261026) : sur une proposition REL, un rejet du
# juge (MEURT, SURVIT_SANS_GAIN) est rendu au generateur pour UNE seconde passe. Au-dela : cout sans gain mesure.
# HALTED, REJETE_HELD_OUT, GAIN_INDECIDABLE ne relancent pas : une autre generation n'y changerait rien.
PASSES_MAX = 2
_REJETS_RAFFINABLES = ("MEURT", "SURVIT_SANS_GAIN")


def _essayer_patch(patch_spec, prop, rel, test_f2p, dry_run, stats, applied_files, unmatched) -> dict | None:
    """UNE tentative : gardes, SEARCH/REPLACE, jugement. Rend le verdict du juge, ou None si rien n'a ete juge."""
    if not (patch_spec and patch_spec.get("target_file")):
        if patch_spec:
            logger.info(f"[patcher] LLM: no safe fix — {patch_spec.get('reason', '?')}")
        else:
            logger.warning("[patcher] LLM: aucun spec rendu (échec hub/parse en amont — voir warnings)")
        return None
    target = patch_spec["target_file"]
    search = patch_spec.get("patch_search", "")
    replace_str = patch_spec.get("patch_replace", "")
    desc = patch_spec.get("description", "LLM auto-patch")
    err = _safe_check(target)
    if (not err and rel is not None
            and target.replace("\\", "/").lstrip("/") != rel["pointer_ref"]["file"]):
        err = f"target_file {target} != pointer_ref.file {rel['pointer_ref']['file']}"
    if err:
        logger.warning(f"[patcher] LLM patch blocked: {err}")
        stats["patches_failed"] += 1
        return None
    if not (search and replace_str):
        return None
    fp = ROOT / target
    if dry_run:
        logger.info(f"[patcher] DRY-RUN LLM: {target} — {desc}")
        return None
    if not fp.exists():
        return None
    if len(replace_str.splitlines()) > MAX_PATCH_LINES:
        logger.warning(f"[patcher] LLM patch trop large — refusé ({target})")
        stats["patches_failed"] += 1
        return None
    src_txt = fp.read_text(encoding="utf-8", errors="replace")
    if search not in src_txt:
        logger.warning(f"[patcher] LLM patch: search absent de {target}")
        stats["patches_failed"] += 1
        return None
    candidate = src_txt.replace(search, replace_str, 1)
    out = _soumettre_ou_differer(f"proposal:{prop.stem}", target, candidate, desc, test_f2p)
    if out.get("verdict") in VERDICTS_RETENUS:
        applied_files.append(target)
        stats["patches_applied"] += 1
        try:
            from nokido_agent.app.forge_self_correction import anchor_solution

            anchor_solution(
                problem="; ".join(unmatched[:2]),
                solution=f"Self-patcher: candidat SURVIT au thymus: {desc} -> {target} (promotion = commit owner)",
                example=f"patch_search={search[:80]}",
                domain="systeme",
            )
        except Exception as e:
            logger.debug(f"[patcher] anchor_solution non persisté ({e})")
    elif out.get("verdict") == "DIFFERE":
        stats["patches_differes"] = stats.get("patches_differes", 0) + 1
    else:
        stats["patches_failed"] += 1
    return out


def run_once(dry_run: bool = False) -> dict:
    try:
        APPLIED_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        logger.warning(f"[patcher] APPLIED_DIR inaccessible ({e}) — les proposals seront RE-traitées à chaque cycle")
    applied = {f.name for f in APPLIED_DIR.glob("*.md")} if APPLIED_DIR.exists() else set()
    proposals = sorted(PROPOSALS_DIR.glob("evolution_proposal_*.md"))
    pending = [p for p in proposals if p.name not in applied]

    logger.info(f"[patcher] {len(pending)} proposals pending")
    # Owner 26/10 : « de la matiere pertinente, pas du bruit a reprendre ». Sous le seuil de pertinence mesure
    # (candidats que l'owner a gardes tels quels / tranches), le patcher passe en SIMULATION : rien n'est ecrit.
    pert = _pertinence()
    mode = "SIMULATION" if dry_run else "REEL"
    if pert.get("statut") == "OBSERVATION":
        dry_run, mode = True, "OBSERVATION"
        logger.warning(f"[patcher] OBSERVATION : pertinence {pert.get('taux')} sur {pert.get('n')} candidats "
                       f"tranches -- aucun candidat ecrit tant que le taux reste sous le seuil")
    stats = {
        "proposals": len(pending),
        "patches_applied": 0,
        "patches_failed": 0,
        "commits": 0,
        "mode": mode,
        "pertinence": pert,
    }

    for prop in tqdm(pending, desc="proposals", unit="prop"):
        text = prop.read_text(encoding="utf-8", errors="replace")
        rel = _extraire_rel(text)
        test_f2p = _test_du_rel(rel) if rel is not None else None
        if (rel is not None and test_f2p
                and not (isinstance(rel.get("pointer_ref"), dict) and rel["pointer_ref"].get("file"))):
            _loc = _localiser_par_imports(test_f2p)   # 3/11 : localisation par les imports du test rouge
            if _loc:
                rel = dict(rel, pointer_ref=_loc)
                logger.info(f"[patcher] {prop.name} : REL localise par les imports du test -> {_loc['file']}")
        if rel is not None and not (isinstance(rel.get("pointer_ref"), dict) and rel["pointer_ref"].get("file")):
            # REL sans localisation : rien a viser, le modele ne peut que deviner -> NON consommee. SAUF si son
            # test est deja VERT : il n'y a plus rien a reparer, et l'ecarter ici le faisait relire a chaque
            # cycle sans fin (5 REL du 26/10 jamais consommes). NR test_self_patcher_f2p_nr.
            if test_f2p and _rel_deja_vert(test_f2p) is True:
                logger.info(f"[patcher] {prop.name} : REL sans localisation, test {test_f2p} deja VERT -- consomme")
                if not dry_run:
                    try:
                        (APPLIED_DIR / prop.name).write_text("skipped: REL sans localisation, test deja vert (%s)"
                                                             % test_f2p)
                    except OSError as e:
                        logger.warning(f"[patcher] marquage impossible ({e}) -- {prop.name} sera revu")
                continue
            logger.warning(f"[patcher] {prop.name} NON consommee (REL pointer_ref null : aucune frame app/tools)")
            continue
        if test_f2p:
            vert = _rel_deja_vert(test_f2p)
            if vert is None:
                logger.warning(f"[patcher] {prop.name} NON consommee (test du REL {test_f2p} illisible)")
                continue
            if vert:
                logger.info(f"[patcher] {prop.name} : test du REL {test_f2p} deja VERT -- rien a reparer")
                if not dry_run:
                    try:
                        (APPLIED_DIR / prop.name).write_text("skipped: test du REL deja vert (%s)" % test_f2p)
                    except OSError as e:
                        logger.warning(f"[patcher] marquage impossible ({e}) -- {prop.name} sera revu")
                continue
        patterns = []
        for line in text.splitlines():
            if line.startswith("- **"):
                key = line[4:].split("**")[0].strip() if "**" in line[4:] else ""
                if key:
                    patterns.append(key)

        if not patterns:
            if dry_run:
                # Une simulation ne CONSOMME rien : marquer ici retirerait la proposition
                # du cycle reel suivant (piege mesure 26/10 avant le reveil owner).
                continue
            try:
                (APPLIED_DIR / prop.name).write_text("skipped: no actionable patterns")
            except PermissionError as e:
                logger.warning(f"[patcher] marquage skip impossible ({e}) — {prop.name} sera revu chaque cycle")
            continue

        logger.info(f"[patcher] {prop.name}: {patterns[:3]}")
        applied_files: list[str] = []

        # 1. Deterministic rules
        matched_rules = set()
        for pat in patterns:
            for key, fn in DETERMINISTIC_RULES.items():
                if key in pat.lower():
                    if rel is None:
                        matched_rules.add((key, fn))

        for rule_key, rule_fn in matched_rules:
            patched = _batch_deterministic(rule_fn, rule_key, dry_run)
            applied_files.extend(patched)
            stats["patches_applied"] += len(patched)

        # 2. LLM fallback for unmatched patterns
        unmatched = [p for p in patterns if rel is not None or not any(k in p.lower() for k in DETERMINISTIC_RULES)]

        if unmatched and not applied_files:
            rag_ctx = _rag_lookup(" ".join(unmatched[:2]))
            retour_juge, amont = "", None
            for passe in range(PASSES_MAX if rel is not None else 1):
                patch_spec = _llm_generate_patch(unmatched, rag_ctx,
                                                 (_contexte_rel(rel) + retour_juge) if rel is not None else "")
                if patch_spec and patch_spec.get("echec_amont"):
                    amont = patch_spec["echec_amont"]
                    break
                out = _essayer_patch(patch_spec, prop, rel, test_f2p, dry_run, stats, applied_files, unmatched)
                if not out or out.get("verdict") not in _REJETS_RAFFINABLES:
                    break
                retour_juge = ("\nTENTATIVE %d REJETEE par le juge deterministe (%s) : %s\n"
                               "Propose un correctif qui tient compte de ce retour.\n"
                               % (passe + 1, out.get("verdict"), str(out.get("pourquoi") or out.get("note") or "")[:1200]))
            if amont:
                # Panne en amont (hub, modele) : rien n'a ete JUGE, la proposition reste en attente pour le
                # prochain cycle -- la marquer traitee confondait « pas pu demander » et « rien a faire ».
                logger.warning(f"[patcher] {prop.name} NON consommee (echec amont : {amont})")
                stats["patches_failed"] += 1
                continue

        # 3. Plus de commit auto : inhibition corticale — SURVIT laisse le
        # working tree modifié, la promotion est le commit OWNER.
        if applied_files and not dry_run:
            logger.info(f"[patcher] {len(applied_files)} candidat(s) SURVIT — en attente de commit owner: {applied_files}")

        # Mark proposal processed -- jamais en simulation : elle doit rester rejouable en reel
        if dry_run:
            continue
        try:
            (APPLIED_DIR / prop.name).write_text(
                json.dumps(
                    {
                        "processed_at": datetime.now().isoformat(),
                        "patterns": patterns,
                        "patched_files": applied_files,
                        "dry_run": dry_run,
                    },
                    indent=2,
                )
            )
        except PermissionError as e:
            logger.warning(f"[patcher] marquage processed impossible ({e}) — {prop.name} sera RE-traité au prochain cycle")

    return stats


def _write_heartbeat(cycle: int = 0):
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            json.dumps(
                {
                    "ts": datetime.now().isoformat(),
                    "cycle": cycle,
                    "interval_s": INTERVAL_S,
                    "pid": os.getpid(),
                }
            )
        )
    except PermissionError:  # muet-ok : sandbox/ n'est pas inscriptible par le compte
        # sandbox du hub, et ce chemin n'est atteint que dans ce cas. Sous NSSM
        # LocalSystem — le mode REEL de ce service — l'ecriture passe. Signaler ici
        # crierait a chaque execution de test sans qu'aucune panne n'existe, et un
        # garde qui crie a faux finit desarme. Le silence est DECLARE et borne au
        # SEUL PermissionError : toute autre erreur remonte.
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nokido self-patcher")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (1h cycle)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
    parser.add_argument("--transe", action="store_true",
                        help="Transe de guerison : soif en lethargie, consolidation + un cycle avec mutation, reveil")
    args = parser.parse_args()
    _dire_identite()

    if args.transe:
        logger.info(f"[patcher] transe: {transe_de_guerison(dry_run=args.dry_run)}")
        return

    if args.daemon:
        cycle = 0
        logger.info(f"[patcher] daemon started — interval={INTERVAL_S}s pid={os.getpid()}")
        while True:
            _write_heartbeat(cycle)
            logger.info(f"[patcher] cycle {cycle} start")
            try:
                if not args.dry_run:
                    logger.info(f"[patcher] consolidation: {consolider()}")
                stats = run_once(dry_run=args.dry_run)
                logger.info(f"[patcher] cycle {cycle}: {stats}")
            except Exception as e:
                logger.error(f"[patcher] cycle {cycle} error: {e}", exc_info=True)
            cycle += 1
            _write_heartbeat(cycle)
            time.sleep(INTERVAL_S)
    else:
        _write_heartbeat(0)
        stats = run_once(dry_run=args.dry_run)
        logger.info(f"[patcher] done: {stats}")
        _write_heartbeat(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
