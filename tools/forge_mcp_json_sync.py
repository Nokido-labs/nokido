"""
forge_mcp_json_sync — sync Bearer tokens dans `.mcp.json` (format Claude Code /
Cline / VSCode MCP clients) depuis le coffre machine DPAPI.

Pourquoi : `.mcp.json` est gitignore et porte les Bearer tokens en clair. Apres
rotation de la cle ou migration vault, le fichier devient stale -> client MCP
plante en 401 "SDK auth failed". Ce script lit `vault_get(FORGE_TOKEN_<agent>)`
pour chaque server defini dans `.mcp.json`, repere le header `X-Agent-Name`,
et reecrit l'Authorization Bearer correspondant.

Usage :
    python tools/forge_mcp_json_sync.py                    # sync .mcp.json
    python tools/forge_mcp_json_sync.py --path X.json      # custom path
    python tools/forge_mcp_json_sync.py --bootstrap        # create from template
    python tools/forge_mcp_json_sync.py --dry-run          # show diff only
    python tools/forge_mcp_json_sync.py --check            # exit 1 si stale

Anatomie : organe = SN peripherique (registry tokens). Pathologie evitee =
"septicemie" silencieuse ou un secret rote n est pas propage et bloque
l identification de l agent (ring < 0 puis 401 cascade).

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `entetes_agent` — En-tetes d'authentification de `agent_name`, ou None si son jeton propre manque.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_machine_vault import available as vault_available
from nokido_agent.app.forge_machine_vault import vault_get

# Dossier du PROPRIETAIRE (repo = <owner_home>/Script python IA/Nokido), pas `Path.home()` :
# sous un autre compte (SYSTEM, bac a sable), `Path.home()` visait `C:/Users/Default` (mesure
# 2026-09-28) -- meme regle que forge_vscode_mcp_sync.OWNER_HOME.
OWNER_HOME = ROOT.parent.parent

DEFAULT_PATHS = [
    ROOT.parent / ".mcp.json",
    OWNER_HOME / ".claude" / ".mcp.json",
    OWNER_HOME / ".config" / "cline" / "mcp_settings.json",
]

# `~/.claude.json` porte AUSSI des declarations du serveur (mesure 2026-09-28) : portee
# UTILISATEUR (`mcpServers` a la racine) et portee LOCALE (`projects[<dossier>].mcpServers`).
# La portee locale passe AVANT `.mcp.json` : ne synchroniser que `.mcp.json` laissait Claude
# Code en 401 apres la rotation des `FORGE_TOKEN_*`, pendant que ce script disait « en phase ».
# NR : tests/nr/test_mcp_json_sync_portees_claude_nr.py.
CLAUDE_JSON = OWNER_HOME / ".claude.json"

# Clients HTTP dont le jeton se RAFRAICHIT ici apres une rotation (2026-09-28 : Gemini,
# Antigravity et VS Code natif en 401 apres la rotation des FORGE_TOKEN_* -- aucun outil ne les
# rafraichissait ; forge_vscode_mcp_sync garde volontairement le jeton existant et renvoie la
# rotation ICI). NR : tests/nr/test_mcp_json_sync_clients_http_nr.py.
CLIENTS_HTTP = [
    OWNER_HOME / ".gemini" / "settings.json",                          # Gemini CLI
    OWNER_HOME / ".gemini" / "config" / "mcp_config.json",             # Antigravity
    OWNER_HOME / "AppData" / "Roaming" / "Code" / "User" / "mcp.json",  # VS Code natif (`servers`)
    ROOT.parent / ".github" / "mcp.json",                              # Copilot
]


def _ecrire_atomique(chemin: Path, cfg: dict) -> None:
    tmp = chemin.with_name(chemin.name + ".tmp_sync")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))  # relu valide AVANT de remplacer
    tmp.replace(chemin)

TEMPLATE = {
    "mcpServers": {
        "laforge-sovereign-hub": {
            "type": "http",
            "url": "http://127.0.0.1:8766/mcp",
            "headers": {
                "Authorization": "Bearer __FORGE_TOKEN_CLAUDE__",
                "X-Agent-Name": "CLAUDE",
            },
            "timeout": 120000,
        }
    }
}


def _resolve_token(agent_name: str) -> str | None:
    """Jeton PROPRE de l'agent, jamais le maitre en repli (2b-6, 2026-09-28).

    Avant : un agent sans jeton propre recevait le MAITRE, ecrit en clair dans `.mcp.json`.
    Absent -> None : l'appelant le dit (NO_VAULT_KEY) et n'ecrit rien."""
    return _jeton_propre(agent_name)


# ─── headersHelper (2026-09-24, reglage (c) accorde par l'owner) ─────────────────────
# Doc Claude Code (mcp.md, ingeree le 24/09) : `headersHelper` est une commande lancee a
# CHAQUE connexion, qui ecrit sur stdout un objet JSON d'en-tetes ; ils remplacent les
# en-tetes statiques de meme nom, et la commande est relancee sur 401/403. Le jeton n'est
# donc plus AU REPOS dans `.mcp.json`, ni dans une variable d'environnement (heritee par
# TOUS les sous-processus : hooks, Bash). Ce script devient lui-meme le helper
# (`--emit-headers AGENT`) : pas de second outil.
#
# CONTRAT AUTH-2/AUTH-4 (SSoT auth_contrat_de_fermeture_2026-09-24) : le helper n'emet que
# le jeton PROPRE de l'agent. Jamais le maitre en repli -- le maitre ne devient pas une
# identite d'organe -- et jeton absent = RIEN sur stdout, code de sortie non nul.


def _jeton_propre(agent_name: str) -> str | None:
    """Jeton PROPRE de l'agent, sans repli sur le maitre."""
    if not agent_name:
        return None
    return vault_get(f"FORGE_TOKEN_{agent_name.upper().strip()}") or None


def entetes_agent(agent_name: str, provenance: str | None = None, tache: str | None = None) -> dict | None:
    """En-tetes d'authentification de `agent_name`, ou None si son jeton propre manque.

    `LaForge-Provenance` (RFC 6648, sans X-) dit QUI a lance le sous-processus ; absente, elle est
    dite INCONNUE, jamais inventee."""
    tok = _jeton_propre(agent_name)
    if not tok:
        return None
    nom = agent_name.upper().strip()
    prov = str(provenance or "").strip().upper() or "INCONNUE"
    h = {"Authorization": f"Bearer {tok}", "X-Agent-Name": nom, "LaForge-Agent-Name": nom,
         "LaForge-Provenance": prov}
    if str(tache or "").strip():
        h["LaForge-Tache"] = str(tache).strip()   # forme courte (court_tache) : lie l'ecriture a SA tache
    return h


def _patch_config(cfg: dict) -> tuple[dict, list[tuple[str, str]]]:
    """Returns (patched_cfg, changes_list). changes = [(server, action), ...]"""
    changes: list[tuple[str, str]] = []
    servers = cfg.get("mcpServers")
    if not isinstance(servers, dict):
        # VS Code natif range ses serveurs sous `servers` (mesure 2026-09-28).
        servers = cfg.get("servers") if isinstance(cfg.get("servers"), dict) else {}
    for name, srv in servers.items():
        if not isinstance(srv, dict):
            continue
        headers = srv.get("headers", {})
        if srv.get("headersHelper"):
            # Le jeton est fourni A LA CONNEXION : en reecrire un en clair ici annulerait
            # precisement ce que le helper retire. On le DIT, on n'ecrit rien.
            changes.append((name, "HEADERS_HELPER: jeton fourni a la connexion, rien a ecrire"))
            continue
        # `LaForge-Agent-Name` : ancien nom de l'en-tete, encore reconnu par le hub et porte
        # par les configs VS Code natif et Antigravity (2026-09-28).
        agent = headers.get("X-Agent-Name", "") or headers.get("LaForge-Agent-Name", "")
        if not agent and (srv.get("url") or srv.get("serverUrl") or srv.get("type") in ("http", "sse")):
            # HTTP SANS agent n'est PAS du stdio (mesure 2026-09-28 : la declaration
            # UTILISATEUR de ~/.claude.json etait classee « transport stdio » et jamais
            # regardee). Le jeton n'est attribuable a aucune identite : on le DIT.
            changes.append((name, "SANS_AGENT: en-tete X-Agent-Name absent, jeton non attribuable"))
            continue
        if not agent:
            # Ne PAS sauter en silence. Un serveur sans header est un transport
            # STDIO : son bearer vit dans l'ENV du lanceur, pas dans un header,
            # donc ce script ne peut pas le synchroniser. Le passer sous silence
            # faisait lire « tout est en phase » sur un lien jamais regarde --
            # a verifier a la main apres chaque rotation de FORGE_MCP_TOKEN.
            changes.append((name, "NON_COUVERT: transport stdio (bearer hors header)"))
            continue
        new_tok = _resolve_token(agent)
        if not new_tok:
            changes.append((name, f"NO_VAULT_KEY:FORGE_TOKEN_{agent.upper()}"))
            continue
        old_auth = headers.get("Authorization", "")
        new_auth = f"Bearer {new_tok}"
        if old_auth == new_auth:
            changes.append((name, "ALREADY_IN_SYNC"))
            continue
        headers["Authorization"] = new_auth
        srv["headers"] = headers
        changes.append((name, "PATCHED"))
    return cfg, changes


def _patch_claude_json(cfg: dict) -> tuple[dict, list[tuple[str, str]]]:
    """Les deux portees de `~/.claude.json` : UTILISATEUR (racine) et LOCALE (par projet).

    `_patch_config` modifie les declarations EN PLACE ; le reste du fichier (etat de
    Claude Code) n'est pas touche."""
    changes: list[tuple[str, str]] = []
    if isinstance(cfg.get("mcpServers"), dict):
        _, ch = _patch_config(cfg)
        changes += [(f"utilisateur/{n}", a) for n, a in ch]
    for projet, conf in (cfg.get("projects") or {}).items():
        if isinstance(conf, dict) and isinstance(conf.get("mcpServers"), dict):
            _, ch = _patch_config(conf)
            changes += [(f"local:{projet}/{n}", a) for n, a in ch]
    return cfg, changes


def _find_default_path() -> Path | None:
    for p in DEFAULT_PATHS:
        if p.is_file():
            return p
    return None


def _journaliser_appel(agent: str, provenance: str) -> None:
    """Mesure (phase 2 identites) : une ligne JSONL par appel du headersHelper.

    Ne consigne que ts/agent/provenance/entrypoint/parent_pid : jamais le jeton ni une autre
    variable d'environnement. Best-effort : un echec ne touche ni stdout ni le code retour.
    """
    try:
        import time
        from nokido_agent.app.forge_db_path import racine_donnees
        rep = Path(racine_donnees()) / "sandbox" / "logs"
        rep.mkdir(parents=True, exist_ok=True)
        ligne = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "agent": str(agent),
                 "provenance": str(provenance or "").strip().upper() or "INCONNUE",
                 "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT") or "ABSENT",
                 "parent_pid": os.getppid()}
        with open(rep / "headers_helper.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[mcp_json_sync] journal headers_helper non ecrit ({type(e).__name__})", file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------------
# AUDITEUR (E6 du plan OAuth MCP, 3/11) : lecture SEULE de toutes les configs clientes, classe d'authentification
# par serveur, JAMAIS une valeur (ni morceau, ni longueur). Mesure avant/apres de chaque migration E7.
# NR : tests/nr/test_mcp_json_sync_auditeur_nr.py
# ---------------------------------------------------------------------------------------------------------------
CODEX_TOML = OWNER_HOME / ".codex" / "config.toml"
_CLE_ENV_CODEX = "bearer_token_env_var"


def _a_authorization(entetes) -> bool:
    return isinstance(entetes, dict) and any(str(k).lower() == "authorization" and v for k, v in entetes.items())


def classer_serveur(srv: dict) -> str:
    """OAUTH_URL_SEULE · HEADERS_HELPER · BEARER_EN_CLAIR · ENV_VAR · STDIO · INCONNU (liste blanche : rien n'est
    « sain » par defaut)."""
    if not isinstance(srv, dict):
        return "INCONNU"
    if srv.get("headersHelper"):
        return "HEADERS_HELPER"
    if _a_authorization(srv.get("headers")) or _a_authorization(srv.get("http_headers")):
        return "BEARER_EN_CLAIR"
    if srv.get(_CLE_ENV_CODEX):
        return "ENV_VAR"
    if srv.get("command"):
        return "STDIO"
    if srv.get("url") or srv.get("serverUrl") or srv.get("httpUrl"):
        return "OAUTH_URL_SEULE"
    return "INCONNU"


def vise_nokido(srv: dict) -> bool:
    url = str(srv.get("url") or srv.get("serverUrl") or srv.get("httpUrl") or "")
    if ":8766" in url:
        return True
    # Points d'entree du hub, jamais « nokido » dans un chemin (mesure 3/11 : playwright lance depuis le dossier
    # Nokido etait compte NOKIDO).
    ligne = " ".join([str(srv.get("command") or "")] + [str(a) for a in (srv.get("args") or [])]).lower()
    return any(m in ligne for m in ("mcp_stdio_bridge", "nokido_hub.py", "forge_mcp_stdio"))


def _serveurs_par_portee(cfg: dict):
    """(portee, nom, srv) : mcpServers / servers (VS Code) / mcp_servers (codex) + portees projets de ~/.claude.json."""
    for cle in ("mcpServers", "servers", "mcp_servers"):
        if isinstance(cfg.get(cle), dict):
            for nom, srv in cfg[cle].items():
                yield "utilisateur", nom, srv
    for projet, pv in (cfg.get("projects") or {}).items():
        if isinstance(pv, dict) and isinstance(pv.get("mcpServers"), dict):
            for nom, srv in pv["mcpServers"].items():
                yield "projet:%s" % projet, nom, srv


def _etat_fichier(chemin: Path):
    """(etat, motif). `Path.exists()` avale l'acces refuse (mesure 3/11 sous LaForgeTrusted : ~/.claude.json lu
    « ABSENT » alors qu'il existe). ABSENT seulement si le parent est LISTABLE et ne contient pas le fichier."""
    try:
        chemin.stat()
        return "PRESENT", ""
    except FileNotFoundError:
        try:
            os.listdir(chemin.parent)
        except FileNotFoundError:
            return "ABSENT", "dossier parent absent"
        except OSError as exc:
            return "ILLISIBLE", "parent:" + type(exc).__name__
        return "ABSENT", ""
    except OSError as exc:
        return "ILLISIBLE", type(exc).__name__


def auditer(chemins) -> list:
    lignes = []
    for chemin in chemins:
        chemin = Path(chemin)
        base = {"fichier": str(chemin)}
        etat, motif = _etat_fichier(chemin)
        if etat != "PRESENT":
            lignes.append(dict(base, etat=etat, **({"motif": motif} if motif else {})))
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
            if chemin.suffix == ".toml":
                import tomllib
                cfg = tomllib.loads(texte)
            else:
                cfg = json.loads(texte)
        except (OSError, PermissionError) as exc:
            lignes.append(dict(base, etat="ILLISIBLE", motif=type(exc).__name__))
            continue
        except Exception as exc:  # noqa: BLE001 - contenu non analysable : DIT, jamais « sain »
            lignes.append(dict(base, etat="ILLISIBLE", motif="format:" + type(exc).__name__))
            continue
        vus = 0
        for portee, nom, srv in _serveurs_par_portee(cfg if isinstance(cfg, dict) else {}):
            vus += 1
            lignes.append(dict(base, etat="LU", portee=portee, serveur=nom, classe=classer_serveur(srv),
                               nokido=vise_nokido(srv) if isinstance(srv, dict) else False))
        if not vus:
            lignes.append(dict(base, etat="LU", portee="-", serveur="(aucun serveur declare)", classe="-",
                               nokido=False))
    return lignes


def _chemins_audit_defaut() -> list:
    return list(dict.fromkeys(list(DEFAULT_PATHS) + [CLAUDE_JSON] + list(CLIENTS_HTTP) + [CODEX_TOML]))


def _main_auditer(chemins) -> int:
    lignes = auditer(chemins or _chemins_audit_defaut())
    for l in lignes:
        if l["etat"] != "LU":
            print("  %-10s %s %s" % (l["etat"], l["fichier"], l.get("motif", "")))
        else:
            print("  %-16s %-6s %-30s %-24s %s" % (l["classe"], "NOKIDO" if l["nokido"] else "-", l["serveur"][:30],
                                                  l["portee"][:24], l["fichier"]))
    defauts = [l for l in lignes if l["etat"] == "LU" and l["nokido"] and l["classe"] == "BEARER_EN_CLAIR"]
    illisibles = [l for l in lignes if l["etat"] == "ILLISIBLE"]
    print("[auditer] %d serveur(s) vers Nokido, %d jeton(s) EN CLAIR, %d fichier(s) ILLISIBLE(S) -- rien ecrit"
          % (sum(1 for l in lignes if l.get("nokido")), len(defauts), len(illisibles)))
    if illisibles:
        return 4
    return 1 if defauts else 0


def main() -> int:
    if "--auditer" in sys.argv:
        _ap = argparse.ArgumentParser(description="auditeur des configs MCP clientes (lecture seule)")
        _ap.add_argument("--auditer", action="store_true")
        _ap.add_argument("--auditer-chemin", type=Path, action="append", default=None)
        _a, _ = _ap.parse_known_args()
        return _main_auditer(_a.auditer_chemin)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", type=Path, default=None, help="explicit .mcp.json path")
    ap.add_argument("--bootstrap", action="store_true", help="create from template if missing")
    ap.add_argument("--dry-run", action="store_true", help="print diff, no write")
    ap.add_argument("--check", action="store_true", help="exit 1 if any server stale")
    ap.add_argument("--emit-headers", metavar="AGENT", default=None,
                    help="mode headersHelper : ecrit sur stdout le JSON des en-tetes de AGENT "
                         "(jeton PROPRE seulement, jamais le maitre ; rien si absent)")
    ap.add_argument("--provenance", metavar="P", default=os.environ.get("NOKIDO_PROVENANCE", ""),
                    help="avec --emit-headers : QUI a lance ce sous-processus (en-tete LaForge-Provenance) ; "
                         "absent -> INCONNUE")
    ap.add_argument("--tache", metavar="T", default="",
                    help="avec --emit-headers : forme courte de la tache (en-tete LaForge-Tache)")
    ap.add_argument("--verifier", action="store_true",
                    help="avec --emit-headers : n'emet PAS la valeur, dit seulement les cles "
                         "et la longueur du jeton (controle sans exposition)")
    ap.add_argument("--claude-json", type=Path, default=CLAUDE_JSON,
                    help="~/.claude.json : portees UTILISATEUR et LOCALE, synchronisees aussi")
    ap.add_argument("--client", type=Path, action="append", default=None,
                    help="config d'un client HTTP a resynchroniser (repetable) ; sans --path ni "
                         "--client : Gemini, Antigravity, VS Code natif, Copilot")
    args = ap.parse_args()

    if args.emit_headers:
        _journaliser_appel(args.emit_headers, args.provenance)
        try:
            entetes = entetes_agent(args.emit_headers, args.provenance, args.tache) if vault_available() else None
        except Exception as e:  # noqa: BLE001
            print(f"[mcp_json_sync] coffre ILLISIBLE ({type(e).__name__}) : aucun en-tete emis",
                  file=sys.stderr)
            return 2
        if not entetes:
            print(f"[mcp_json_sync] FORGE_TOKEN_{args.emit_headers.upper()} absent : aucun "
                  "en-tete emis (jamais de repli sur le maitre)", file=sys.stderr)
            return 1
        if args.verifier:
            print(json.dumps({"cles": sorted(entetes),
                              "longueur_jeton": len(entetes["Authorization"]) - len("Bearer ")}))
            return 0
        sys.stdout.write(json.dumps(entetes))
        return 0

    if not vault_available():
        print("[mcp_json_sync] ERROR: vault DPAPI unavailable", file=sys.stderr)
        return 2

    target = args.path or _find_default_path()
    if target is None:
        if not args.bootstrap:
            print("[mcp_json_sync] no .mcp.json found; rerun with --bootstrap", file=sys.stderr)
            return 3
        target = DEFAULT_PATHS[0]

    if not target.is_file():
        if not args.bootstrap:
            print(f"[mcp_json_sync] not found: {target} (use --bootstrap)", file=sys.stderr)
            return 3
        target.parent.mkdir(parents=True, exist_ok=True)
        cfg = json.loads(json.dumps(TEMPLATE))
    else:
        try:
            cfg = json.loads(target.read_text(encoding="utf-8"))
        except PermissionError as exc:
            # 3/11 : trois etats, jamais deux -- un fichier du profil owner illisible pour ce compte est DIT (code 4),
            # jamais un plantage ni un « en ordre ». NR : tests/nr/test_mcp_json_sync_illisible_nr.py
            print(f"[mcp_json_sync] ILLISIBLE ({type(exc).__name__}) : {target} -- relancer sous le compte owner",
                  file=sys.stderr)
            return 4

    others = [p for p in DEFAULT_PATHS if p.is_file() and p != target]
    if others and args.path is None:
        # _find_default_path s'arrete au PREMIER chemin existant : sans cette
        # ligne, un « ALREADY_IN_SYNC » se lit comme un verdict sur toute la
        # famille alors qu'un seul fichier a ete ouvert.
        print("[mcp_json_sync] NON EXAMINE(S), relancer avec --path : %s" % (
            ", ".join(str(p) for p in others)))

    cfg, changes = _patch_config(cfg)

    stale = any(action == "PATCHED" for _, action in changes)
    missing = [n for n, a in changes if a.startswith("NO_VAULT_KEY")]

    for name, action in changes:
        print(f"  {name:40s}  {action}")

    cj_cfg, cj_changes = None, []
    if args.claude_json and args.claude_json.is_file():
        cj_cfg, cj_changes = _patch_claude_json(
            json.loads(args.claude_json.read_text(encoding="utf-8")))
        print(f"[mcp_json_sync] {args.claude_json} :")
        for name, action in cj_changes or [("(aucune declaration de serveur)", "-")]:
            print(f"  {name:40s}  {action}")
    cj_stale = any(action == "PATCHED" for _, action in cj_changes)
    missing += [n for n, a in cj_changes if a.startswith("NO_VAULT_KEY")]

    clients = args.client if args.client else ([] if args.path else list(CLIENTS_HTTP))
    cl_res = []
    for chemin in clients:
        if not chemin.is_file():
            print(f"[mcp_json_sync] {chemin} : absent")
            continue
        cfg_c, ch = _patch_config(json.loads(chemin.read_text(encoding="utf-8")))
        print(f"[mcp_json_sync] {chemin} :")
        for name, action in ch or [("(aucune declaration de serveur)", "-")]:
            print(f"  {name:40s}  {action}")
        cl_res.append((chemin, cfg_c, any(a == "PATCHED" for _, a in ch)))
        missing += [n for n, a in ch if a.startswith("NO_VAULT_KEY")]
    cl_stale = any(s for _, _, s in cl_res)

    if args.check:
        return 1 if (stale or cj_stale or cl_stale or missing) else 0

    if args.dry_run:
        print("--- DRY RUN — no file written ---")
        return 0

    if stale or not target.exists():
        target.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        print(f"[mcp_json_sync] wrote: {target}")
    else:
        print("[mcp_json_sync] no change needed")

    if cj_stale:
        _ecrire_atomique(args.claude_json, cj_cfg)
        print(f"[mcp_json_sync] wrote: {args.claude_json} (relu au demarrage de Claude Code)")
    for chemin, cfg_c, s in cl_res:
        if s:
            _ecrire_atomique(chemin, cfg_c)
            print(f"[mcp_json_sync] wrote: {chemin} (relu au demarrage du client)")

    if missing:
        print(f"[mcp_json_sync] WARNING: missing vault keys: {missing}", file=sys.stderr)
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
