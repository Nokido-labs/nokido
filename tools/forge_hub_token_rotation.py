#!/usr/bin/env python3
"""forge_hub_token_rotation.py — rotation OWNER-DRIVEN des bearer tokens hub :8766.

Dette depuis 2026-07-19 : la clé d'accès hub figure dans l'historique git POUSSÉ
(superrepo 2 commits + LaForge ~13, 3 remotes) => divulguée. Décision owner du
19/07 : rotation différée, « script guidé owner-driven » quand on la fera.
CE script est ce guide. Il ne s'exécute PAS depuis un agent : la moitié du travail
touche le profil owner (~/.claude.json, .zcode) et coupe les sessions live.

    # 1. Inventaire (défaut, AUCUNE écriture) — état vault/configs/git/hub
    LAFORGE_PYTHON tools/forge_hub_token_rotation.py

    # 2. Rotation effective (owner, console) :
    LAFORGE_PYTHON tools/forge_hub_token_rotation.py --execute --keys FORGE_TOKEN_CLAUDE
    #    puis restart hub (restart_hub.ps1 / lanceur) + restart des sessions clients

RÈGLES DE CONCEPTION (mesurées, cf. RULES_SHARED + mémoires 2026-07-19) :
- AUCUNE valeur de secret n'est affichée : uniquement des empreintes sha256[:12].
- 3 états par source, jamais 2 : trouvé · absent · ILLISIBLE (ACL) — un scan qui
  n'a pas pu regarder le DIT au lieu de rassurer.
- ~/.claude.json GLOBAL porte la clé en 2+ occurrences (mcpServers global + scope
  projet) : après rotation sans MAJ de CE fichier, Claude Code = 401 au reconnect
  même si .mcp.json projet est bon (mesuré 19/07). Ce script le réécrit.
- .claude/settings.local.json (allowlist permissions) porte des littéraux Bearer :
  ils sont remplacés aussi, sinon règles d'allowlist mortes + secret qui traîne.
- Réutilise l'existant (anti-dup) : forge_secrets (vault DPAPI), et renvoie vers
  forge_mcp_json_sync --check pour la famille .mcp.json après coup.
- Réécriture d'historique git NON requise : la rotation invalide l'ancienne valeur.

Anatomie : organe = immunitaire (rotation de clés = renouvellement des anticorps).
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/rotation-cles-hub"

import argparse
import hashlib
import json
import os
import re
import secrets as _secrets
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # LaForge/
sys.path.insert(0, str(ROOT))

HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766")
OWNER_HOME = Path(os.environ.get("LAFORGE_OWNER_HOME", r"%USERPROFILE%"))
SUPER = ROOT.parent                                     # superrepo (Script python IA)

TOKEN_RE = re.compile(r"\b[0-9a-f]{64}\b")
# Liste de SECOURS seulement : la source réelle est vault_list() (une liste figée
# rend invisibles les agents ajoutés depuis — motif « keeper aveugle par filtre NOM »).
VAULT_KEYS_FALLBACK = [
    "FORGE_MCP_TOKEN", "FORGE_TOKEN_CLAUDE", "FORGE_TOKEN_GEMINI",
    "FORGE_TOKEN_ANTIGRAVITY", "FORGE_TOKEN_ZCODE", "FORGE_TOKEN_BRIDGE",
    "FORGE_TOKEN_CODEX", "FORGE_TOKEN_DSPY_ROUTER",
]
# Fichiers clients susceptibles de porter la clé en clair (profil owner).
CONFIG_FILES = [
    OWNER_HOME / ".claude.json",                        # GOTCHA: 2+ occurrences
    OWNER_HOME / ".claude" / ".mcp.json",
    OWNER_HOME / ".zcode" / "mcp.json",
    SUPER / ".mcp.json",
    SUPER / ".zcode" / "config.json",
    SUPER / ".claude" / "settings.local.json",          # littéraux allowlist
    ROOT / ".mcp.json",
    ROOT / "Nokido.env",                                # 3e couche forge_secrets
    ROOT / ".env",
    # Clients hors Claude : invisibles depuis le sandbox (HOME=C:/Users/Default),
    # donc JAMAIS conclure "absent" depuis un compte de service — d'ou le 3e etat.
    OWNER_HOME / ".config" / "cline" / "mcp_settings.json",
    OWNER_HOME / "AppData" / "Roaming" / "Code" / "User" / "mcp.json",
    OWNER_HOME / ".codex" / "config.toml",
    OWNER_HOME / ".gemini" / "settings.json",
    # Pont STDIO (Claude Desktop / Cowork) : le bearer n'y vit pas dans un
    # header HTTP mais dans l'ENV du lanceur. forge_mcp_json_sync ne le voit
    # PAS (il n'inspecte que les serveurs porteurs d'un X-Agent-Name), et
    # l'inventaire ne le voyait pas non plus -> une rotation de FORGE_MCP_TOKEN
    # cassait Claude Desktop en silence.
    OWNER_HOME / "laforge_bridge.bat",
    OWNER_HOME / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
]

# Claude Desktop installe depuis le MICROSOFT STORE (MSIX) : AppData\Roaming est
# VIRTUALISE vers ...\Packages\Claude_<id>\LocalCache\Roaming. Le fichier sous
# AppData\Roaming\Claude existe ALORS AUSSI, porte le meme nom et un contenu
# credible -- mais l'application ne le lit JAMAIS. Mesure 2026-09-03 : plusieurs
# heures perdues a patcher l'homonyme inerte pendant que le pont servait un jeton
# rote depuis le vrai fichier, et chaque source verifiee ressortait saine.
# L'id du paquet est un hash : on GLOBBE, on ne code pas le chemin en dur.
try:
    _MSIX_CFG = sorted((OWNER_HOME / "AppData" / "Local" / "Packages").glob(
        "Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"))
except OSError as _e:
    _MSIX_CFG = []
    print("[rotation] Packages MSIX ILLISIBLE (%s) — config Store NON examinee"
          % _e.__class__.__name__)
CONFIG_FILES += _MSIX_CFG


def fp(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _scan_text(path: Path):
    """-> (etat, tokens) ; etat dans {trouve, absent, illisible}."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "absent", []
    except OSError as e:
        return "illisible (%s)" % e.__class__.__name__, []
    return "trouve", sorted(set(TOKEN_RE.findall(txt)))


def _git_history_tokens(repo: Path):
    """Valeurs 64-hex dans l'historique COMPLET du dépôt (donc divulguées si poussé)."""
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(repo), "log", "--all", "-p",
             "--diff-filter=ACDM", "--", "*.json", "*.env", "*.md", "*.py", "*.toml"],
            capture_output=True, text=True, errors="replace", timeout=300)
        if out.returncode != 0:
            return "illisible (git rc=%d)" % out.returncode, []
        return "trouve", sorted(set(TOKEN_RE.findall(out.stdout)))
    except Exception as e:
        return "illisible (%s)" % e.__class__.__name__, []


def _vault_tokens():
    """{cle_vault: valeur} — valeurs jamais affichées (empreintes seulement).

    Enumere le coffre (vault_list) au lieu d'une liste figee : un agent ajoute
    apres coup serait invisible, et son token passerait pour 'inconnu du vault'.
    """
    got = {}
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:
        return "illisible (import forge_secrets: %s)" % e.__class__.__name__, {}
    keys, state = list(VAULT_KEYS_FALLBACK), "trouve (liste de secours)"
    try:
        from nokido_agent.app.forge_machine_vault import vault_list
        # Enumeration COMPLETE. Filtrer sur le NOM (« TOKEN ») rendait vault=-
        # pour toute cle vive nommee autrement — mesure 2026-09-03 :
        # CLOUDFLARE_SECRET_KEY_ACCESS, presente au coffre a l'identique, passait
        # pour un residu a supprimer. Le filtre reste a l'AFFICHAGE, jamais sur
        # le verdict : un capteur ne doit pas rendre « absent » ce qu'il exclut.
        listed = list(vault_list())
        if listed:
            keys, state = sorted(set(listed) | set(VAULT_KEYS_FALLBACK)), "trouve (enumere)"
    except Exception as e:
        state = "partiel (vault_list indispo: %s)" % e.__class__.__name__
    for k in keys:
        try:
            v = get_secret(k)
        except Exception:
            v = None
        if v:
            got[k] = v.strip()
    return state, got


# QUATRIEME TRANSPORT. Un secret ne vit pas que dans un fichier : header HTTP,
# env de lanceur, fichier de config... et VARIABLE D'ENVIRONNEMENT PERSISTANTE.
# Mesure 2026-09-03 : le pont stdio est reste en 401 des heures alors que le
# coffre ET le fichier de config portaient la bonne valeur — une variable User
# periemee primait sur les deux, et l'inventaire ne la regardait pas. Un scanner
# qui ne connait qu'un transport rend un vert qui ne couvre que lui.
_ENV_SCOPES = (
    ("User", "HKCU", r"Environment"),
    ("Machine", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
)


def _env_registry():
    """-> (etat, [(portee, nom, valeur)]) pour les variables portant un 64-hex.

    Trois etats comme partout ici : une ruche illisible le DIT, elle ne se lit pas
    comme vide. La suppression n'est PAS faite ici : toucher a l'environnement
    systeme est une action OWNER (et `Machine` exige une elevation)."""
    try:
        import winreg
    except ImportError:
        return "indisponible (hors Windows)", []
    racines = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    trouves, illisibles = [], []
    for portee, ruche, chemin in _ENV_SCOPES:
        try:
            with winreg.OpenKey(racines[ruche], chemin) as k:
                i = 0
                while True:
                    try:
                        nom, val, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if isinstance(val, str) and TOKEN_RE.search(val):
                        # HKCU est celui du COMPTE QUI EXECUTE : lance depuis un
                        # compte de service, on inspecte SES variables, pas celles
                        # de l'owner — et « 0 trouve » se lirait alors comme sain.
                        # La portee porte donc le compte, toujours.
                        aff = portee if portee == "Machine" else "User@%s" % (
                            os.environ.get("USERNAME") or "?")
                        trouves.append((aff, nom, TOKEN_RE.search(val).group(0)))
        except OSError as e:
            illisibles.append("%s (%s)" % (portee, e.__class__.__name__))
    etat = "compte=%s" % (os.environ.get("USERNAME") or "?")
    if illisibles:
        etat += " — ILLISIBLE: %s" % ", ".join(illisibles)
    return etat, trouves


# Routes candidates : (methode, chemin, corps). Aucune n'est presumee bonne —
# c'est le controle negatif qui ELIT celle qui discrimine reellement (mesure
# 2026-07-30 : /api/whoami n'existe pas, 404 pour tout le monde).
PROBE_ROUTES = [
    ("POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"ping"}'),
    ("GET", "/api/whoami", None),
    ("GET", "/api/self", None),
]
_PROBE_ROUTE = PROBE_ROUTES[0]


def _hub_probe(token: str, route=None):
    """-> 'ACCEPTE' | 'REFUSE' | 'INTESTABLE (raison)' sur la route ELUE."""
    method, path, body = route or _PROBE_ROUTE
    req = urllib.request.Request(
        HUB_URL + path, data=body, method=method,
        headers={"Authorization": "Bearer " + token, "X-Agent-Name": "CLAUDE",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            txt = r.read(4096).decode("utf-8", "replace").lower()
        if "bad_token" in txt or "unauthorized" in txt or "invalid token" in txt:
            return "REFUSE"
        return "ACCEPTE"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "REFUSE"
        if e.code == 404:
            return "INTESTABLE (route absente)"
        return "ACCEPTE"          # 4xx/5xx applicatif = l'auth a ete franchie
    except Exception as e:
        return "INTESTABLE (%s)" % e.__class__.__name__


def _probe_is_discriminant():
    """CONTROLE NEGATIF : elit une route qui REFUSE un token jamais existe et
    ACCEPTE une cle du coffre. Sans les DEUX, aucun verdict hub n'est rapporte
    (une sonde qui dit oui a tout fabrique une alerte maximale ; une sonde qui
    dit non a tout rassure a tort)."""
    global _PROBE_ROUTE
    bidon = _secrets.token_hex(32)
    _, vault = _vault_tokens()
    ref = vault.get("FORGE_TOKEN_CLAUDE") or vault.get("FORGE_MCP_TOKEN")
    if not ref:
        return False, "SANS REFERENCE", "SANS REFERENCE"
    last = ("", "")
    for route in PROBE_ROUTES:
        neg, pos = _hub_probe(bidon, route), _hub_probe(ref, route)
        last = (neg, pos)
        if neg == "REFUSE" and pos == "ACCEPTE":
            _PROBE_ROUTE = route
            print("[controle sonde] route elue: %s %s" % (route[0], route[1]))
            return True, neg, pos
    return False, last[0], last[1]


def inventory(probe: bool = True):
    print("=== INVENTAIRE ROTATION (aucune ecriture) ===")
    if probe:
        ok, v_neg, v_pos = _probe_is_discriminant()
        print("[controle sonde] token bidon -> %s | cle du vault -> %s : %s" % (
            v_neg, v_pos, "DISCRIMINANTE" if ok else "NON DISCRIMINANTE"))
        if not ok:
            print("  => les verdicts hub ci-dessous NE PROUVENT RIEN (sonde a "
                  "corriger avant toute conclusion). Colonne hub ignoree.")
            probe = False
    v_state, vault = _vault_tokens()
    vault_by_fp = {fp(v): k for k, v in vault.items()}
    shown = {k: v for k, v in vault.items() if "TOKEN" in k.upper()}
    print("[vault %s] %d clés présentes, %d affichées (nom contenant TOKEN ; le "
          "verdict ci-dessous porte sur les %d): %s" % (
              v_state, len(vault), len(shown), len(vault),
              ", ".join("%s=%s" % (k, fp(v)) for k, v in shown.items()) or "-"))

    hist_all: set[str] = set()
    for repo in (SUPER, ROOT):
        h_state, toks = _git_history_tokens(repo)
        hist_all |= set(toks)
        print("[git %s] %s : %d valeur(s) 64-hex dans l'historique" % (h_state, repo.name, len(toks)))

    file_map: dict[str, list[str]] = {}
    for f in CONFIG_FILES:
        st, toks = _scan_text(f)
        for t in toks:
            file_map.setdefault(t, []).append(f.name)
        print("[config %-9s] %-25s : %s" % (st, f.name, ", ".join(fp(t) for t in toks) or "-"))

    e_state, e_vars = _env_registry()
    print("[env %s] %d variable(s) d'environnement portant un 64-hex" % (e_state, len(e_vars)))
    for portee, nom, val in e_vars:
        file_map.setdefault(val, []).append("env:%s\\%s" % (portee, nom))
        print("[env %-9s] %-25s : %s" % (portee, nom[:25], fp(val)))

    # VERDICT PRINCIPAL — ne depend d'AUCUNE sonde reseau : une valeur qui est a
    # la fois dans l'historique git POUSSE et dans le coffre AUJOURD'HUI est une
    # cle vive divulguee, que le hub reponde ou non.
    vive_divulguee = sorted(
        (k, fp(v)) for k, v in vault.items() if v in hist_all)
    print("--- CLES VIVES PRESENTES DANS L'HISTORIQUE GIT (hors sonde) ---")
    if vive_divulguee:
        for k, f in vive_divulguee:
            print("  A ROTER  %-32s %s" % (k, f))
        print("  => %d cle(s) du coffre figurent dans un historique pousse." % len(vive_divulguee))
    else:
        print("  aucune (les cles du coffre sont absentes des historiques lus)")

    candidates = hist_all | set(file_map) | set(vault.values())
    print("--- verdict par empreinte (jamais la valeur) ---")
    exposed_alive = []
    for t in sorted(candidates, key=fp):
        in_hist = t in hist_all
        verdict = _hub_probe(t) if probe else "NON SONDE"
        vkey = vault_by_fp.get(fp(t), "-")
        print("  %s  git_history=%-5s  vault=%-22s  configs=%-30s  hub=%s" % (
            fp(t), in_hist, vkey, ",".join(file_map.get(t, [])) or "-", verdict))
        if in_hist and verdict == "ACCEPTE":
            exposed_alive.append((fp(t), vkey))
    if not probe:
        print("VERDICT SUSPENDU : sonde non discriminante (voir controle ci-dessus).")
    elif exposed_alive:
        print("/!\\ DIVULGUE + ENCORE ACCEPTE -> a roter : %s" % exposed_alive)
    else:
        print("OK: aucune valeur d'historique git n'est encore acceptee par le hub.")
    return exposed_alive, vault


def execute(keys: list[str]):
    """Rotation effective : vault + réécriture configs. Owner console UNIQUEMENT."""
    _, vault = _vault_tokens()
    from nokido_agent.app.forge_secrets import set_secret
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    replacements: dict[str, str] = {}
    for k in keys:
        old = vault.get(k)
        if not old:
            print("SKIP %s : absent du vault (rien à roter sous ce nom)" % k)
            continue
        new = _secrets.token_hex(32)
        set_secret(k, new)
        replacements[old] = new
        print("ROTATED vault %s : %s -> %s" % (k, fp(old), fp(new)))

    if not replacements:
        print("Aucune rotation effectuée.")
        return 1

    for f in CONFIG_FILES:
        st, toks = _scan_text(f)
        hits = [t for t in toks if t in replacements]
        if not hits:
            if st.startswith("illisible"):
                print("  ILLISIBLE %s — à traiter à la main (%s)" % (f, st))
            continue
        txt = f.read_text(encoding="utf-8")
        bak = f.with_suffix(f.suffix + ".bak-rot-" + stamp)
        bak.write_text(txt, encoding="utf-8")
        n = 0
        for old, new in replacements.items():
            n += txt.count(old)
            txt = txt.replace(old, new)
        f.write_text(txt, encoding="utf-8")
        print("  PATCHED %s : %d occurrence(s) (backup %s)" % (f, n, bak.name))

    print("""
=== SUITE MANUELLE (dans l'ordre) ===
1. Restart hub (charge les nouvelles clés) : restart_hub.ps1 / lanceur — JAMAIS
   nssm direct (règle d'or 10, LaForge-Master est propriétaire).
2. Verif : relancer ce script SANS --execute — les anciennes empreintes doivent
   sortir REFUSE, les nouvelles ACCEPTE.
3. `LAFORGE_PYTHON tools/forge_mcp_json_sync.py --check` (famille .mcp.json).
4. Redémarrer les sessions clients (Claude Code, zcode, Gemini) — une session
   ouverte garde l'ancienne clé en mémoire => 401 (mesuré 19/07).
5. Supprimer les .bak-rot-* une fois la bascule validée (ils portent l'ANCIENNE
   valeur — inoffensive après rotation, mais autant nettoyer).""")
    return 0


# Cle du coffre ATTENDUE par fichier client : sert a REMETTRE un jeton hub perime
# a sa valeur vive. Mappe par chemin complet et non par nom de fichier — deux
# clients distincts s'appellent tous les deux « mcp.json ».
EXPECTED_VAULT_KEY = {
    str(OWNER_HOME / ".claude.json"): "FORGE_TOKEN_CLAUDE",
    str(OWNER_HOME / ".claude" / ".mcp.json"): "FORGE_TOKEN_CLAUDE",
    str(SUPER / ".mcp.json"): "FORGE_TOKEN_CLAUDE",
    str(ROOT / ".mcp.json"): "FORGE_TOKEN_CLAUDE",
    str(SUPER / ".claude" / "settings.local.json"): "FORGE_TOKEN_CLAUDE",
    str(OWNER_HOME / ".zcode" / "mcp.json"): "FORGE_TOKEN_ZCODE",
    str(SUPER / ".zcode" / "config.json"): "FORGE_TOKEN_ZCODE",
    str(OWNER_HOME / ".gemini" / "settings.json"): "FORGE_TOKEN_GEMINI",
    str(OWNER_HOME / ".codex" / "config.toml"): "FORGE_TOKEN_CODEX",
    str(OWNER_HOME / ".config" / "cline" / "mcp_settings.json"): "FORGE_TOKEN_CLINE",
    str(OWNER_HOME / "AppData" / "Roaming" / "Code" / "User" / "mcp.json"): "FORGE_TOKEN_VSCODE",
    # Pont stdio : la valeur mesuree le 2026-09-03 y etait celle de
    # FORGE_TOKEN_CLAUDE, pas de FORGE_TOKEN_BRIDGE malgre le nom de la
    # variable. On restaure la CONTINUITE (l'etat d'avant rotation) ; basculer
    # sur FORGE_TOKEN_BRIDGE serait un changement de comportement non mesure,
    # et un header d'agent non apparie a son jeton DEGRADE le ring (videur, §5).
    str(OWNER_HOME / "AppData" / "Roaming" / "Claude"
        / "claude_desktop_config.json"): "FORGE_TOKEN_CLAUDE",
    str(OWNER_HOME / "laforge_bridge.bat"): "FORGE_MCP_TOKEN",
}
# Meme regle pour la ou les configs Store : c'est le fichier REELLEMENT lu.
for _p in _MSIX_CFG:
    EXPECTED_VAULT_KEY[str(_p)] = "FORGE_TOKEN_CLAUDE"

# Un 64-hex n'est pas un secret par sa FORME. Ces noms de champ designent des
# identifiants ou des empreintes publiques ; les effacer casse le client sans
# rien proteger (mesure 2026-09-03 : 4 « residus » sur 4 en etaient).
NON_SECRET_FIELDS = (
    "userid", "machineid", "deviceid", "installid", "installationid",
    "sha256", "fingerprint", "checksum", "digest",
)


def cleanup(apply: bool = False) -> int:
    """Etape 5 : purge des .bak-rot-* + traitement des residus de config.

    QUATRE classes, jamais une suppression aveugle (mesure 2026-09-03 : deux
    « residus » se sont reveles des cles VIVES — l'inventaire les affichait
    vault=- parce qu'il n'enumere que les cles dont le NOM contient TOKEN) :
      LAISSE   valeur egale a une valeur vive du coffre = config saine.
      REMPLACE 64-hex REFUSE par le hub, sur une ligne qui reference bien le hub,
               dans un fichier client connu -> jeton perime remis a la valeur du
               coffre. Le SUPPRIMER laisserait ce client sans authentification.
      RETIRE   ligne COMMENTEE portant un secret dont le coffre a deja la copie.
      SIGNALE  tout le reste. On n'efface pas un secret dont le coffre n'a pas de
               copie : ce serait la derniere, et le cout des deux erreurs n'est
               pas symetrique.
    """
    ok, v_neg, v_pos = _probe_is_discriminant()
    if not ok:
        print("STOP : sonde hub NON discriminante (bidon=%s, coffre=%s)." % (v_neg, v_pos))
        print("  Sans elle, « perime » ne se distingue pas de « je n'ai pas pu voir ».")
        return 2
    _, vault = _vault_tokens()
    live = set(vault.values())
    tag = "APPLY" if apply else "DRY-RUN"
    print("=== CLEANUP ETAPE 5 (%s) ===" % tag)

    n_bak = n_repl = n_line = n_flag = n_blind = n_ident = 0
    for f in CONFIG_FILES:
        st, toks = _scan_text(f)
        if st.startswith("illisible"):
            # Le repertoire l'est aussi : un glob y rend une liste VIDE, ce qui se
            # lirait « aucun backup » alors qu'on n'a PAS PU regarder. On ne compte
            # donc rien ici — on declare l'angle mort.
            n_blind += 1
            print("  ILLISIBLE %-26s %s -> console OWNER (backups non enumerables)" % (
                f.name, st))
            continue
        try:
            baks = sorted(f.parent.glob(f.name + ".bak-rot-*"))
        except OSError as e:
            baks = []
            print("  BAK      %s : enumeration ILLISIBLE (%s)" % (
                f.parent, e.__class__.__name__))
        for bak in baks:
            n_bak += 1
            if not apply:
                print("  BAK      %s" % bak)
                continue
            try:
                bak.unlink()
                print("  BAK      %s : supprime" % bak)
            except OSError as e:
                print("  BAK      %s : ECHEC %s (%s)" % (bak, e.__class__.__name__, e))
        if not toks:
            continue
        lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
        drop: set[int] = set()
        subs: dict[str, str] = {}
        for t in toks:
            if t in live:
                continue
            commented = [i for i, l in enumerate(lines)
                         if t in l and l.lstrip().startswith(("#", "//", ";"))]
            if commented and any(t in v for v in live):
                drop.update(commented)
                n_line += 1
                print("  RETIRE   %-26s %s ligne(s) %s (commentee, copie au coffre)" % (
                    f.name, fp(t), [i + 1 for i in commented]))
                continue
            # Garde : ne remplacer que si la ligne parle BIEN du hub. Un 64-hex
            # quelconque REFUSE par le hub n'est pas pour autant un jeton hub —
            # l'ecraser casserait le service auquel il appartient.
            _ligne = next((l for l in lines if t in l), "")
            # Le NOM porte par la ligne prime sur le mapping par fichier : un meme
            # fichier peut servir plusieurs services. Mesure 2026-09-03 : la config
            # Claude Desktop porte le bearer du pont (hub :8766) ET celui de netcfg
            # (:8767, sonde discriminante) — deduire la cle du fichier ecraserait
            # l'un avec l'autre.
            _par_nom = next((k for k in vault if k and k in _ligne), None)
            # Marqueurs volontairement ETROITS : ils doivent designer le hub et LUI
            # SEUL, pour le cas ou la ligne ne nomme aucune cle connue.
            ctx_hub = any(t in l and any(m in l.lower() for m in (
                "bearer", "8766", "laforge", "forge_token", "forge_mcp_token",
                "forge_bridge_token")) for l in lines)
            if _par_nom and vault.get(_par_nom):
                subs[t] = vault[_par_nom]
                n_repl += 1
                print("  REMPLACE %-26s %s -> %s (cle %s, nommee sur la ligne)" % (
                    f.name, fp(t), fp(vault[_par_nom]), _par_nom))
                continue
            key = EXPECTED_VAULT_KEY.get(str(f))
            if ctx_hub and key and vault.get(key) and _hub_probe(t) == "REFUSE":
                subs[t] = vault[key]
                n_repl += 1
                print("  REMPLACE %-26s %s -> %s (jeton hub perime, cle %s)" % (
                    f.name, fp(t), fp(vault[key]), key))
            else:
                # Sans la ligne porteuse, le signalement est un cul-de-sac : il ne
                # permet pas de distinguer un secret d'un identifiant, et invite
                # donc a effacer un identifiant legitime. TOUS les 64-hex de la
                # ligne sont masques — elle peut en porter un autre que celui-ci.
                ctx = next((TOKEN_RE.sub("<64HEX>", l).strip()[:88]
                            for l in lines if t in l), "")
                low = ctx.lower()
                if any(w in low for w in NON_SECRET_FIELDS):
                    n_ident += 1
                    print("  IDENTIFIANT %-23s %s : %s" % (f.name, fp(t), ctx))
                    continue
                n_flag += 1
                print("  SIGNALE  %-26s %s : hors coffre%s -> a la main" % (
                    f.name, fp(t), "" if ctx_hub else ", hors contexte hub"))
                if ctx:
                    print("           ctx: %s" % ctx)
        if not apply or (not drop and not subs):
            continue
        txt = "".join(l for i, l in enumerate(lines) if i not in drop)
        for old, new in subs.items():
            txt = txt.replace(old, new)
        try:
            f.write_text(txt, encoding="utf-8")
            print("           ECRIT %s" % f.name)
        except OSError as e:
            print("           ECHEC ECRITURE %s : %s (%s)" % (
                f.name, e.__class__.__name__, e))

    # Variables d'environnement : SIGNALEES, jamais supprimees ici. Modifier
    # l'environnement systeme est une action OWNER, et la portee Machine exige une
    # elevation. Un process n'en herite qu'a sa CREATION : apres suppression, tout
    # process deja lance garde l'ancienne valeur (mesure 2026-09-03, deux faux
    # diagnostics avant de tuer le bon process).
    e_state, e_vars = _env_registry()
    print("  [env] portee User inspectee = celle de %s ; relancer en console OWNER "
          "pour couvrir la sienne" % e_state)
    n_env = 0
    for portee, nom, val in e_vars:
        verdict = _hub_probe(val)
        if val in live and verdict != "REFUSE":
            continue
        n_env += 1
        print("  ENV      %-8s %-22s %s  hub=%s" % (portee, nom[:22], fp(val), verdict))
        print("           -> supprimer (action OWNER%s), puis RELANCER les clients :"
              " un process garde l'environnement de sa creation"
              % (", console admin" if portee == "Machine" else ""))
    if e_state.startswith("partiel"):
        print("  /!\\ registre %s — des variables n'ont PAS pu etre lues." % e_state)

    print("--- %s : %d backup(s), %d remplacement(s), %d ligne(s) retiree(s), "
          "%d signale(s), %d identifiant(s) laisse(s), %d variable(s) d'env, "
          "%d fichier(s) ILLISIBLE(s)" % (
              tag, n_bak, n_repl, n_line, n_flag, n_ident, n_env, n_blind))
    if n_blind:
        print("  /!\\ %d fichier(s) non lu(s) : leur etat est INCONNU, pas sain." % n_blind)
    if not apply:
        print("Relancer avec --cleanup --apply pour ecrire.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="rotation owner-driven des tokens hub")
    ap.add_argument("--execute", action="store_true",
                    help="rotation effective (défaut = inventaire sans écriture)")
    ap.add_argument("--keys", nargs="+", default=["FORGE_TOKEN_CLAUDE", "FORGE_MCP_TOKEN"],
                    help="clés vault à roter (défaut: FORGE_TOKEN_CLAUDE FORGE_MCP_TOKEN)")
    ap.add_argument("--no-probe", action="store_true", help="inventaire sans sonder le hub")
    ap.add_argument("--cleanup", action="store_true",
                    help="etape 5 : purge des .bak-rot-* et des residus de config")
    ap.add_argument("--apply", action="store_true",
                    help="avec --cleanup : ecrit reellement (defaut = dry-run)")
    args = ap.parse_args(argv)
    if args.cleanup:
        return cleanup(apply=args.apply)
    if args.execute:
        return execute(args.keys)
    inventory(probe=not args.no_probe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
