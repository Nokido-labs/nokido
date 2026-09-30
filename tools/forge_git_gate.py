#!/usr/bin/env python3
"""forge_git_gate.py — Filtre git CENTRAL de Nokido (routé par .githooks/).

Tout ce qui s'enregistre en local passe par CE filtre unique : les hooks shell ne
sont que des shims minces (zéro logique dupliquée). Composé des modules EXISTANTS
(anti-dup) :
  - secrets : scripts/precommit_secret_scan.py          -> BLOCK (fail-closed)
  - désync  : forge_swarm_blackboard (zone tree_locks)  -> WARN + auto-claim
  - qualité : forge_quality_gate                         -> WARN (fail-open)
  - egress  : app/forge_git_egress.py (pre-push)         -> son propre hook = filtre
              CENTRAL avant push (secrets/manifest/entropy/host-leak, profils par remote)

ANTI-PERTE (règle user) : au COMMIT on ne BLOQUE que les secrets. Désync + qualité
= warn. Jamais empêcher de SAUVER en local (= ne jamais perdre le travail). Le block
strict vit au PUSH (forge_git_egress), filtre central avant GitHub/Codeberg.

Sous-commandes (appelées par les hooks) :
  precommit            scan staged : secrets(block) + désync(warn+claim) + qualité(warn)
  prepare-msg <file>   injecte trailer X-Agent / X-Agent-Channel (auteur git = user)
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

__FORGE_COLOR__ = "immunitaire/guard : filtre git central (routes .githooks)"  # organe declare le 2026-09-06 (audit de raccordement)

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# nom agent -> canal (réutilise la nomenclature network de nokido_hub)
#
# ⚠️ N'INSCRIRE ICI QUE DES AGENTS AU TRANSPORT UNIVOQUE. Cette table est le REPLI
# consulté quand `LAFORGE_AGENT_CHANNEL` n'est pas posé : elle DÉDUIT, elle ne mesure
# pas. `CLAUDE` en a été RETIRÉ le 2026-09-06 (owner : « comment stdio ? claude code
# est mcp http ! ») : le même nom couvre Claude Desktop, qui passe bien par le pont
# stdio, ET Claude Code, qui parle au hub en HTTP. La table tranchait pour
# `STDIO_CLAUDE`, donc elle étiquetait FAUX tout commit Claude Code dont le chemin ne
# posait pas le canal — mesuré sur `5e8b34884`. Le hook rend `UNKNOWN` pour un agent
# absent d'ici, et c'est le comportement voulu : un repli qui INVENTE une valeur
# précise se lit ensuite comme une mesure, alors qu'un `UNKNOWN` se voit et se corrige.
# `BRIDGE` reste : le pont stdio EST stdio, son transport ne dépend pas de l'appel.
_CHANNEL = {
    "BRIDGE": "STDIO_CLAUDE", "COWORK": "COWORK",
    "GEMINI": "GEMINI_OAUTH", "CLINE": "CLINE_MCP", "CODEX": "CODEX", "COPILOT": "COPILOT",
    "ANTIGRAVITY": "GEMINI_OAUTH", "AGY": "GEMINI_OAUTH",
}


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=str(ROOT), errors="replace")


def _staged_files() -> list[str]:
    r = _git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    return [f.strip() for f in r.stdout.splitlines() if f.strip()]


def _agent() -> str:
    """Identité de l'agent courant : env LAFORGE_AGENT / ANTIGRAVITY_AGENT, sinon marqueur .nokido.agent du worktree,
    sinon UNKNOWN."""
    for _var in ("LAFORGE_AGENT", "FORGE_AGENT_NAME", "LAFORGE_AGENT_NAME"):
        if os.environ.get(_var, "").strip():
            return os.environ[_var].strip().upper()
    if os.environ.get("ANTIGRAVITY_AGENT") == "1" or os.environ.get("GEMINI_CLI") == "1":
        return "ANTIGRAVITY"
    m = ROOT / ".nokido.agent"
    if m.exists():
        for line in m.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("agent="):
                return line.split("=", 1)[1].strip() or "UNKNOWN"
    # Repli mesure 2026-07-30 : sous le compte sandbox (commits via le hub) aucune
    # des sources ci-dessus n'est definie et le claim sortait anonyme — un verrou
    # qui ne nomme pas son porteur ne coordonne rien. On NE codifie PAS un agent en
    # dur (le depot est partage : ce serait mentir pour les autres surfaces) ; on
    # rend l'identite GIT reelle, prefixee pour ne pas la confondre avec un agent
    # declare du registre.
    try:
        _who = subprocess.run(["git", "config", "user.name"], capture_output=True,
                              text=True, timeout=10, errors="replace").stdout.strip()
        if _who:
            return f"GIT:{_who}".upper()
    except Exception as e:  # noqa: BLE001
        print(f"[gate] identite git illisible ({type(e).__name__})")
    return "UNKNOWN"


# ── pre-commit : secrets(block) + désync(warn+claim) + qualité(warn) ────────────


def _scan_secrets() -> int:
    scan = ROOT / "scripts" / "precommit_secret_scan.py"
    if not scan.exists():
        return 0
    return subprocess.run([PY, str(scan)], cwd=str(ROOT)).returncode


def _desync_warn_and_claim(files: list[str]) -> None:
    """Best-effort, JAMAIS bloquant. Lit la zone tree_locks du blackboard, signale les
    fichiers déjà claim par un AUTRE agent (collision = désync), puis auto-republie le
    claim de l'agent courant. C'est la 2e couche anti-désync (enforced au choke-point,
    quel que soit le canal), complément du protocole coopératif de RULES_SHARED."""
    if str(ROOT / "app") not in sys.path:
        sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_swarm_blackboard import apply_fact, read_zone  # type: ignore

    agent = _agent().upper()
    try:
        z = read_zone("tree_locks")
        facts = z.get("facts", []) if isinstance(z, dict) else []
    except Exception:
        facts = []
    for fact in facts:
        owner = str(fact.get("worker_id", "")).upper()
        if owner and owner != agent:
            val = str(fact.get("value", ""))
            hit = [f for f in files if f in val]
            if hit:
                print(f"[gate][DESYNC] {', '.join(hit[:5])} déjà claim par {owner} "
                      f"-> collision possible (warn, NON bloquant). Coordonner/rebase.")
    try:
        import asyncio

        asyncio.run(apply_fact(
            "tree_locks",
            f"{agent} commit: {', '.join(files[:20])}",
            # `source=` et non `worker_id=` (parametre inexistant : l'appel levait
            # un TypeError avale par le except, donc AUCUN claim n'a jamais ete
            # publie). `ring=2` obligatoire : tree_locks n'est pas dans la table
            # des zones, donc le defaut trusted-only (2) s'applique et le defaut
            # du parametre (4) serait refuse par l'ACL. Revele le 2026-07-30 par
            # la journalisation de ce meme chemin d'erreur.
            key=agent.lower(), category="edit_claim", source=agent, ring=2,
        ))
    except Exception as e:
        print(f"[gate] claim tree_locks NON publie: {str(e)[:80]}")


def _quality_warn(files: list[str]) -> None:
    pys = [f for f in files if f.endswith(".py")]
    if not pys:
        return
    if str(ROOT / "app") not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_quality_gate import block_if_failing  # type: ignore
    except Exception:
        return
    for f in pys:
        try:
            block_if_failing(str(ROOT / f))
        except Exception as e:
            # Le MOTIF avant le chemin : un chemin de depot consomme ~90 des
            # 100 caracteres et coupait la cause, si bien que l'avertissement
            # semblait designer le fichier commite. Mesure du 2026-09-12 : la
            # cause reelle etait `WORKSPACE_GUARD: subprocess.Popen interdit`,
            # levee pour TOUS les fichiers -- le gate n'avait donc rien
            # verifie, et le disait d'une facon qui accusait le code.
            print(f"[gate][quality][warn] {type(e).__name__}: "
                  f"{str(e)[:200]} (fichier: {f})")


def _firehose_warn(files: list[str]) -> None:
    """Garde anti-régression (incident 47GB/OOM 2026-06-11) : subprocess sans errors=,
    readTextFile-whole en .ts, CREATE TABLE sans purge. WARN, jamais bloquant."""
    try:
        if str(ROOT / "tools") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_firehose_guard import scan  # type: ignore

        warns = scan(files)
        if warns:
            print("[gate][firehose][warn] anti-régression incident 47GB :")
            for w in warns:
                print(f"  ! {w}")
    except Exception as e:
        print(f"[gate][firehose] skip: {str(e)[:80]}")


def _syntax_warn(files: list[str]) -> None:
    """AST-parse les .py stagés. Un .py cassé qui atteint HEAD fait fail-close le hub
    au reboot SANS message (incident 2026-06-16 : firewall + forge_mcp_registry commités
    cassés). WARN LOUD, jamais bloquant (anti-perte) ; le hard-gate est au boot
    (forge_boot_syntax_check.py)."""
    import ast

    bad: list[str] = []
    for f in files:
        if not f.endswith(".py"):
            continue
        try:
            ast.parse((ROOT / f).read_text(encoding="utf-8", errors="replace"), filename=f)
        except SyntaxError as e:
            bad.append(f"{f}:{e.lineno}: {e.msg}")
        except Exception as e:  # illisible n'est PAS sain : on le dit au lieu de passer
            print(f"[gate][syntax] {f}: NON verifie ({type(e).__name__})")
            continue
    if bad:
        print("[gate][syntax][warn] *** .py CASSE commite -> hub fail-close au reboot ***")
        for b in bad:
            print(f"  BROKEN {b}")
        print("  (non bloquant - anti-perte - mais CORRIGE avant reboot/reload)")


def _recidive_warn(files: list[str]) -> None:
    """Garde anti-RECIDIVE (mandat owner 2026-07-29, mesure forge_recurrence_audit).

    Deux motifs d'echec sont re-consignes depuis mai sans jamais cesser, parce que
    leur seul garde-fou etait une note a se rappeler. Ce qui a effectivement tenu
    cette annee, ce sont les regles CABLEES (bash_guard, hook_recon_first,
    forge_tool_gate) : on ne les viole pas, on s'y adapte. D'ou ce check.

      1. `chemin_erreur_muet` (74 memoires, mai -> juillet) : un handler dont le
         corps est un `pass`/`continue` nu rend le defaut INDIAGNOSTICABLE. Paye
         encore le 29-07 : la branche NotFound de readOneHeartbeat etait muette,
         ce qui a coute plusieurs tours juste pour ELIMINER une piste.
      2. `mauvaise_cible_ecriture` (25 memoires, mai -> juillet) : ecrire dans
         `rag_fts` n'indexe RIEN pour le moteur, qui lit `rag_chunks_fts` (FTS a
         contenu externe, sans trigger). Paye le 29-07 : une these ingeree,
         embeddee, et pourtant invisible a la recherche.

    WARN, jamais bloquant : la doctrine du gate est anti-perte, et ce fichier
    lui-meme contient des `except: pass` legitimes. Echappatoire explicite :
    `# muet-ok` sur la ligne du handler quand le silence est voulu.
    """
    import ast

    muets: list[str] = []
    cibles: list[str] = []
    for f in files:
        if not f.endswith(".py") or f.startswith("tests/") or "/tests/" in f:
            continue
        try:
            src = (ROOT / f).read_text(encoding="utf-8", errors="replace")
            arbre = ast.parse(src, filename=f)
        except Exception as e:
            print(f"[gate][recidive] {f} illisible/non parsable: {str(e)[:60]}")
            continue
        lignes = src.splitlines()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.ExceptHandler):
                continue
            corps = noeud.body
            if len(corps) == 1 and isinstance(corps[0], (ast.Pass, ast.Continue)):
                # Le marqueur se lit sur la ligne du HANDLER **ou** sur celle de
                # son corps. C'est le `pass` qui est muet, et c'est la que
                # l'auteur l'ecrit spontanement : sept marqueurs poses de bonne
                # foi n'avaient RIEN marque (mesure 2026-09-21), et leurs sites
                # restaient signales commit apres commit.
                #
                # On elargit ou le gate LIT, jamais ce qu'il EXIGE : `muet-ok`
                # reste une declaration explicite, et un marqueur eloigne
                # n'absout rien (verifie par un test symetrique).
                a_lire = {noeud.lineno, corps[0].lineno}
                if any("muet-ok" in lignes[n - 1]
                       for n in a_lire if 0 < n <= len(lignes)):
                    continue
                muets.append(f"{f}:{noeud.lineno}")
        if "INSERT INTO rag_fts" in src.upper().replace("INSERT  INTO", "INSERT INTO"):
            if "rag_chunks_fts" not in src:
                cibles.append(f)

    if muets:
        print(f"[gate][recidive][warn] chemin d'erreur MUET (motif re-consigne 74x "
              f"depuis mai) — {len(muets)} site(s) :")
        for m in muets[:12]:
            print(f"  ! {m} — avale sans trace ; journalise, ou marque `# muet-ok`")
        if len(muets) > 12:
            # UNE BORNE DIT COMBIEN, PAS SEULEMENT TROP.
            #
            # Mesure du 2026-09-21 : `tools/nokido_hub.py` portait 22 sites, le
            # gate en montrait 12 et se taisait sur les 10 autres. Huit sites
            # corriges -> le gate reaffiche 12, dont neuf jamais vus. Un compte
            # identique d'un commit a l'autre se lit « rien n'a bouge », alors
            # que le travail avait porte : une borne muette transforme un
            # PROGRES en SURPLACE.
            #
            # Meme motif que le `text[:3000]` qui avait detruit le corps de 377
            # documents de veille. Borner est legitime ; taire la coupure, non.
            print(f"  ... et {len(muets) - 12} autre(s) NON affiche(s) — "
                  f"la liste est bornee, le defaut ne l'est pas")
    if cibles:
        print("[gate][recidive][warn] MAUVAISE cible d'indexation (motif re-consigne 25x) :")
        for c in cibles:
            print(f"  ! {c} — ecrit dans rag_fts sans toucher rag_chunks_fts,")
            print("      or c'est rag_chunks_fts que forge_rag_engine._lexical() lit.")


def _alignment_warn(files) -> None:
    """P6 non-regression d'alignement : surface le verdict alignment_health au commit.
    WARN seulement (coherent avec l'anti-perte du gate : seul un secret bloque ; bloquer
    la derive empecherait de commit le fix de la derive). Best-effort, ne leve jamais."""
    try:
        try:
            from nokido_agent.tools.forge_alignment_invariants import alignment_health
        except Exception:
            import importlib.util as _u
            _p = Path(__file__).resolve().parent / "forge_alignment_invariants.py"
            _s = _u.spec_from_file_location("forge_alignment_invariants", _p)
            _m = _u.module_from_spec(_s)
            _s.loader.exec_module(_m)
            alignment_health = _m.alignment_health
        h = alignment_health()
        v = h.get("verdict")
        if v != "ALIGNED":
            print(f"[gate][ALIGNEMENT] DERIVE: {v} ({h.get('enforced')}/{h.get('total')} enforced) -> verifier avant push")
        else:
            print(f"[gate][ALIGNEMENT] OK {h.get('enforced')}/{h.get('total')} ENFORCED")
    except Exception as e:
        print(f"[gate][ALIGNEMENT] NON verifie ({type(e).__name__}: {str(e)[:60]})")


def _ps1_parse_gate(files: list[str]) -> int:
    """Parse-check les .ps1 stages via l'analyseur PowerShell. BLOQUE sur erreur.

    Meme raison que _ts_parse_gate, autre organe : un .ts casse tue le SUPERVISEUR,
    un .ps1 casse tue le DEMARRAGE — nokido_start.ps1 amorce les 55 services, et une
    erreur de syntaxe y rend la flotte injoignable sans qu'aucun gate en aval ne le
    voie. Mesure 2026-08-26 : un tiret cadratin et des guillemets typographiques
    ajoutes dans ce fichier ASCII PUR le rendaient non parsable sous PS 5.1 — le
    commit serait passe, le prochain demarrage aurait echoue.

    Discipline identique : preuve POSITIVE seulement (l'analyseur rend des erreurs),
    powershell introuvable = skip ANNONCE, et le denominateur est imprime — « rien
    trouve » ne doit jamais se lire comme « tout verifie ».
    """
    import shutil as _shutil

    ps = [f for f in files if f.lower().endswith((".ps1", ".psm1"))]
    if not ps:
        return 0
    exe = _shutil.which("powershell") or _shutil.which("pwsh") or ""
    if not exe:
        print(f"[gate][ps1] powershell introuvable — {len(ps)} .ps1 NON verifie(s) "
              f"(skip, pas un blocage)")
        return 0

    casses: list[str] = []
    vus = 0
    for f in ps:
        cible = str(ROOT / f).replace("'", "''")
        script = (
            "$e=$null;$t=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{cible}',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|Select-Object -First 3|ForEach-Object{"
            "Write-Output ('L'+$_.Extent.StartLineNumber+': '+$_.Message)}}"
            "else{Write-Output 'PARSE_OK'}"
        )
        try:
            pr = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60,
            )
        except Exception as e:  # noqa: BLE001 — outil injouable != code casse
            print(f"[gate][ps1] {f}: analyse injouable ({str(e)[:60]}) — non bloquant")
            continue
        sortie = (pr.stdout or "").strip()
        if "PARSE_OK" in sortie:
            vus += 1
            continue
        if not sortie:
            # Ni OK ni erreur : on n'a PAS PU regarder. Ce n'est pas un feu vert.
            print(f"[gate][ps1] {f}: analyseur muet — NON verifie")
            continue
        vus += 1
        for ligne in sortie.splitlines()[:3]:
            casses.append(f"{f}: {ligne[:130]}")

    if casses:
        print("[gate][ps1] *** .ps1 NON PARSABLE -> le demarrage de la flotte echouerait ***")
        for c in casses:
            print(f"  BROKEN {c}")
        print(_conseil_bloque("ps1"))
        return 1
    if vus < len(ps):
        print(f"[gate][ps1] {vus}/{len(ps)} .ps1 analyses — le reste n'a PAS pu etre verifie")
    else:
        print(f"[gate][ps1] OK — {vus} fichier(s) .ps1 parsent")
    return 0


def _ts_parse_gate(files: list[str]) -> int:
    """Parse-check les .ts stagés via `deno lint --json`. BLOQUE sur erreur de PARSE.

    Pourquoi BLOQUANT, à la différence de _syntax_warn (.py = warn) : un .py cassé fait
    fail-close le hub, mais un .ts cassé tue LE SUPERVISEUR — et les 52 services avec
    lui — sans qu'aucun hard-gate n'existe en aval (le superviseur n'a pas d'équivalent
    de forge_boot_syntax_check). Mesure 2026-07-29 : ni les hooks ni les 7 workflows CI
    ne validaient le moindre .ts, et les deux patchs de supervisor.ts du jour ont dû
    être lintés À LA MAIN. L'anti-perte reste servi : `git commit --no-verify`.

    On ne bloque QUE sur une preuve POSITIVE d'erreur de parse (champ `errors` du JSON).
    Le style est ignoré : supervisor.ts porte 12 diagnostics préexistants (imports
    `https:`, `catch {}` vides, `tierFor` inutilisée) qui feraient échouer tout commit.
    deno introuvable = skip ANNONCÉ, jamais un blocage : « je ne peux pas voir » n'est
    pas « c'est cassé » (le compte sandbox, lui, ne voit pas le binaire du profil owner).
    """
    import json as _json
    import os as _os
    import re as _re
    import shutil as _shutil

    ts = [f for f in files if f.endswith((".ts", ".tsx"))]
    if not ts:
        return 0
    deno = ""
    try:  # source unique : la déclaration ${DENO} de services.toml
        _toml = (ROOT / "proxy_deno" / "core" / "services.toml").read_text("utf-8", "ignore")
        _m = _re.search(r'^\s*DENO\s*=\s*"([^"]+)"', _toml, _re.M)
        if _m and _os.path.exists(_m.group(1)):
            deno = _m.group(1)
    except Exception:  # noqa: BLE001 — muet-ok : le repli ci-dessous couvre le cas
        pass
    # Repli MACHINE-WIDE. Mesure 2026-07-30 : ${DENO} de services.toml pointe le
    # profil owner (C:/Users/<owner>/.deno), INVISIBLE des comptes de service —
    # donc le gate .ts skippait sur TOUT commit passant par le hub, parse comme
    # types. Une copie sous ProgramData est lisible par tous les comptes. On ne
    # modifie surtout PAS ${DENO} lui-meme : il pilote le superviseur, un chemin
    # faux y couperait les 52 services.
    if not deno:
        for _cand in ("C:/ProgramData/deno/deno.exe", "C:/ProgramData/Nokido/deno.exe"):
            if _os.path.exists(_cand):
                deno = _cand
                break
    deno = deno or _shutil.which("deno") or ""
    if not deno:
        print(f"[gate][ts] deno introuvable — {len(ts)} .ts NON verifie(s) (skip, pas un blocage)")
        return 0

    # DENO_DIR PARTAGE -- sans lui, ce gate n'a jamais rendu de verdict de TYPE
    # sur un commit passant par un compte de service. Chaine mesuree le
    # 2026-09-02, en trois temps :
    #   1. le cache par defaut se resout sous le profil du compte courant ; pour
    #      un compte sandbox (HOME = C:\\Users\\Default) le chemin est INVALIDE
    #      -> `deno check` sort rc=1 avec « La syntaxe du nom de fichier [...]
    #      est incorrecte », SANS code TSxxxx, donc classe « ignore » plus bas ;
    #   2. avec un DENO_DIR valide mais VIDE, le check doit telecharger
    #      deno.land/std -> WinError 10013, l'egress etant ferme a ce compte ;
    #   3. cache peuple UNE FOIS depuis un compte en ligne -> le check passe
    #      hors ligne, en deux secondes.
    # Autrement dit : le gate trouvait bien deno et l'executait, mais son verdict
    # de type etait structurellement inatteignable. Il l'annoncait honnetement
    # (« absence de verdict, pas un feu vert ») -- il ne mentait pas, il ne
    # protegeait simplement personne sur ce chemin-la.
    _env = dict(_os.environ)
    if not _env.get("DENO_DIR"):
        _partage = "C:/ProgramData/deno/cache"
        if _os.path.isdir(_partage):
            _env["DENO_DIR"] = _partage
        else:
            print("[gate][ts] DENO_DIR partage absent (%s) -- le type-check peut "
                  "ne rendre AUCUN verdict sous un compte de service" % _partage)

    broken: list[str] = []
    verifies = 0
    for f in ts:
        try:
            pr = subprocess.run(
                [deno, "lint", "--json", str(ROOT / f)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=90, env=_env,
            )
        except Exception as e:  # noqa: BLE001 — outil injouable != code casse
            print(f"[gate][ts] {f}: lint injouable ({str(e)[:60]}) — non bloquant")
            continue
        if pr.returncode == 0:
            verifies += 1
            continue
        errs = []
        try:
            _j = _json.loads(pr.stdout or "{}") or {}
            errs = _j.get("errors") or []
            if _j.get("checked_files"):
                verifies += 1
        except Exception:  # noqa: BLE001 — JSON illisible : on n'invente pas une panne
            errs = []
        for e in errs[:3]:
            broken.append(f"{e.get('filename') or f}: {str(e.get('message', ''))[:120]}")
        # rc != 0 SANS `errors` = diagnostics de style seulement -> on laisse passer

    if broken:
        print("[gate][ts] *** .ts NON PARSABLE -> le superviseur ne demarrerait plus ***")
        for b in broken:
            print(f"  BROKEN {b}")
        print(_conseil_bloque("ts"))
        return 1

    # TYPE-check (2026-07-30). Le parse ne prouve que la LISIBILITE : un .ts qui parse
    # avec une erreur de type passait, et le superviseur tombe au runtime. Mesure du
    # jour : `deno check` sortait 18 diagnostics sur proxy_deno la ou le lint disait OK
    # (err `unknown` deference, surcharge WebAssembly, worker type comme une fenetre).
    # Stock ramene a 0 par le commit 17dd2327 -> on peut BLOQUER sans refuser tout.
    # Restreint a proxy_deno : le reste du depot porte le corpus SWE-bench (eval_repos),
    # qui n'est pas notre code et n'a pas a passer nos regles.
    vivants = [f for f in ts if f.replace("\\", "/").startswith("proxy_deno/")]
    mal_types: list[str] = []
    types_vus = 0  # compte les fichiers REELLEMENT type-checkes (cf. faux vert ci-dessous)
    for f in vivants:
        try:
            pr = subprocess.run(
                [deno, "check", str(ROOT / f)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180, env=_env,
            )
        except Exception as e:  # noqa: BLE001 — outil injouable != code casse
            print(f"[gate][ts] {f}: check injouable ({str(e)[:60]}) — non bloquant")
            continue
        if pr.returncode == 0:
            types_vus += 1
            continue
        sortie = (pr.stderr or "") + (pr.stdout or "")
        # preuve POSITIVE seulement : un code TSxxxx. Sinon (reseau, cache, permission)
        # on n'invente pas une panne de typage.
        codes = _re.findall(r"TS\d{4}", sortie)
        if not codes:
            print(f"[gate][ts] {f}: check rc={pr.returncode} sans code TS — ignore")
            continue
        types_vus += 1
        premiere = next((l.strip() for l in sortie.splitlines() if "TS" in l and "ERROR" in l), codes[0])
        mal_types.append(f"{f}: {premiere[:130]}")
    if mal_types:
        print("[gate][ts] *** ERREUR DE TYPE -> le superviseur peut tomber au runtime ***")
        for m in mal_types:
            print(f"  TYPE {m}")
        print(_conseil_bloque("ts"))
        return 1
    # « aucune erreur » n'est PAS « verifie » : un check injouable laisse la liste
    # vide exactement comme un fichier sain. Regression introduite puis mesuree le
    # 2026-07-30 — le gate annoncait « types OK » sur 0 fichier reellement analyse.
    if types_vus:
        print(f"[gate][ts] types OK — {types_vus}/{len(vivants)} fichier(s) proxy_deno")
    if vivants and types_vus < len(vivants):
        print(f"[gate][ts] {len(vivants) - types_vus} fichier(s) NON type-checkes "
              f"— absence de verdict, pas un feu vert")

    if verifies < len(ts):
        # « rien trouve » n'est pas « je ne peux pas voir » : on ne rassure jamais a tort.
        print(f"[gate][ts] {verifies}/{len(ts)} .ts analyses — le reste n'a PAS pu etre verifie")
    else:
        print(f"[gate][ts] OK — {verifies} fichier(s) .ts parsent")
    return 0


# ── Soupape ANTI-PERTE ETROITE (decision owner 2026-09-24) ──────────────────────
# « Ne jamais empecher de SAUVER » (regle user), mais la soupape precedente -- conseiller
# `--no-verify` quand un .ts/.ps1 bloque -- desarmait AUSSI le scan de secrets. La derogation
# vise desormais LE CONTROLE FAUTIF, nommement, et laisse une TRACE : sans trace ecrite, pas de
# derogation (fail-closed). Le scan de secrets n'est JAMAIS derogeable : il tourne avant tout.
_DEROGEABLES = ("ts", "ps1")
_TRACE_DEROGATIONS = ROOT / "sandbox" / "git_gate_derogations.jsonl"


def _derogations() -> set:
    """Controles que `LAFORGE_GATE_DEROGATION` (liste separee par des virgules) autorise a sauter."""
    demande = {x.strip().lower() for x in os.environ.get("LAFORGE_GATE_DEROGATION", "").split(",") if x.strip()}
    refuses = sorted(demande - set(_DEROGEABLES))
    if refuses:
        print(f"[gate] derogation IGNOREE pour {refuses} : seuls {list(_DEROGEABLES)} sont derogeables "
              f"(le scan de secrets ne l'est jamais)")
    return demande & set(_DEROGEABLES)


def _tracer_derogation(controle: str, files: list[str]) -> bool:
    """Ecrit la derogation AVANT de l'accorder. False si la trace ne peut pas s'ecrire."""
    import json
    try:
        _TRACE_DEROGATIONS.parent.mkdir(parents=True, exist_ok=True)
        with open(_TRACE_DEROGATIONS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"), "controle": controle,
                                 "agent": _agent(), "nb_fichiers": len(files), "fichiers": files[:50]},
                                ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        print(f"[gate] trace de derogation IMPOSSIBLE ({type(e).__name__}) -> derogation REFUSEE")
        return False


def _conseil_bloque(controle: str) -> str:
    return (f"  commit BLOQUE par le controle {controle}. Corrige ; pour SAUVER le travail sans CE "
            f"controle seulement : LAFORGE_GATE_DEROGATION={controle} git commit ...\n"
            f"  (scan de secrets toujours actif, derogation tracee dans sandbox/git_gate_derogations.jsonl ;"
            f" pas de --no-verify : il desarme aussi le scan de secrets)")


def _bloquant_ou_derogation(controle: str, rc: int, files: list[str]) -> int:
    if rc == 0:
        return 0
    if controle in _derogations() and _tracer_derogation(controle, files):
        print(f"[gate][{controle}] DEROGATION tracee -> commit AUTORISE sans ce controle "
              f"(scan de secrets deja passe)")
        return 0
    return rc


def _precommit() -> int:
    files = _staged_files()
    if not files:
        return 0
    rc = _scan_secrets()
    if rc != 0:
        print("[gate] SECRET détecté -> commit BLOQUÉ (corrige puis re-commit).")
        return rc  # block (avec _ts_parse_gate) — tout le reste reste warn (anti-perte)
    try:
        _desync_warn_and_claim(files)
    except Exception as e:
        print(f"[gate] désync skip: {str(e)[:80]}")
    try:
        _quality_warn(files)
    except Exception as e:
        print(f"[gate] quality skip: {str(e)[:80]}")
    try:
        _firehose_warn(files)
    except Exception as e:
        print(f"[gate] firehose skip: {str(e)[:80]}")
    try:
        _syntax_warn(files)
    except Exception as e:
        print(f"[gate] syntax skip: {str(e)[:80]}")
    try:
        _alignment_warn(files)
    except Exception:  # muet-ok : le gate ne casse jamais sur son propre outil
        pass
    try:
        _recidive_warn(files)
    except Exception as e:
        print(f"[gate][recidive] skip: {str(e)[:80]}")
    # BLOQUANT, en dernier pour que tous les diagnostics soient affiches d'abord.
    try:
        rc_ts = _ts_parse_gate(files)
    except Exception as e:  # noqa: BLE001 — le gate ne casse jamais sur son propre outil
        print(f"[gate][ts] skip: {str(e)[:80]}")
        rc_ts = 0
    rc_ts = _bloquant_ou_derogation("ts", rc_ts, files)
    if rc_ts != 0:
        return rc_ts
    try:
        rc_ps = _ps1_parse_gate(files)
    except Exception as e:  # noqa: BLE001 — le gate ne casse jamais sur son propre outil
        print(f"[gate][ps1] skip: {str(e)[:80]}")
        rc_ps = 0
    rc_ps = _bloquant_ou_derogation("ps1", rc_ps, files)
    if rc_ps != 0:
        return rc_ps
    return 0


# ── prepare-commit-msg : trailer RFC LaForge-Agent-Name (auteur git reste user) ──


def _strip_agent_signatures(txt: str) -> str:
    """Retire toute signature d'agent IA du message de commit (Co-Authored-By Claude/
    Anthropic, ligne 'Generated with Claude Code'). Demande user 2026-06-12 :
    l'attribution voulue est user via le trailer X-Agent, jamais de signature Claude."""
    out = []
    for ln in txt.splitlines():
        low = ln.strip().lower()
        if low.startswith("co-authored-by:") and ("claude" in low or "anthropic" in low):
            continue
        if "generated with" in low and "claude code" in low:
            continue
        out.append(ln)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)


_UNTESTED = re.compile(r"\b(wip|untested|not tested|non[ -]?test[eé]{1,2}s?)\b", re.IGNORECASE)


def _untested_gate(txt: str) -> int:
    """REFUSE un commit qui s'annonce LUI-MÊME non testé, sauf aveu explicite.

    Mesuré : `wip(docker): pivot Docker Desktop -> dockerd natif WSL (AGY, UNTESTED)` est
    entré sur `alpha` le 01/08. Il a coûté une session entière — searxng injoignable, cinq
    modes réseau essayés, un reboot — avant qu'un `git log` ne montre que la version d'avant
    marchait. Le gate savait détecter un secret, un firehose et une dérive d'alignement,
    mais pas le mot par lequel l'auteur annonçait lui-même le risque.

    Seul le SUJET est examiné : un corps qui explique ce qui n'a pas été testé est
    souhaitable, jamais suspect. Deux échappatoires assumées — une ligne `Untested-Ack:
    <raison>` dans le corps, ou `NOKIDO_ALLOW_UNTESTED=1`. On n'interdit pas de livrer du
    non testé ; on interdit que ça passe SILENCIEUSEMENT.
    """
    lignes = [ln for ln in txt.splitlines() if not ln.lstrip().startswith("#")]
    sujet = next((ln for ln in lignes if ln.strip()), "")
    m = _UNTESTED.search(sujet)
    if not m:
        return 0
    if os.environ.get("NOKIDO_ALLOW_UNTESTED") == "1":
        print(f"[gate][untested] « {m.group(0)} » dans le sujet — laisse passer (NOKIDO_ALLOW_UNTESTED=1)")
        return 0
    if any(ln.strip().lower().startswith("untested-ack:") for ln in lignes):
        print(f"[gate][untested] « {m.group(0)} » assume par Untested-Ack — OK")
        return 0
    print(
        f"[gate][untested] REFUS — le sujet annonce « {m.group(0)} ».\n"
        f"  Sujet : {sujet[:100]}\n"
        f"  Mesure : un commit tague UNTESTED a coute une session entiere le 01-02/08\n"
        f"  (pivot Docker -> WSL, searxng injoignable, revert final 3aec1500).\n"
        f"  Trois issues, dans l'ordre de preference :\n"
        f"    1. TESTER, puis committer sans le mot ;\n"
        f"    2. assumer par ecrit — ligne « Untested-Ack: <ce qui n'a pas ete verifie> »\n"
        f"       dans le corps du message (elle reste dans l'historique, donc visible) ;\n"
        f"    3. NOKIDO_ALLOW_UNTESTED=1 pour cette commande (echappatoire de derniere main).",
        file=sys.stderr,
    )
    return 1


def _prepare_msg(msg_path: str) -> int:
    try:
        p = Path(msg_path)
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    rc = _untested_gate(txt)
    if rc:
        return rc
    # Strip signatures Claude/IA AVANT tout (s'applique même si X-Agent déjà présent).
    stripped = _strip_agent_signatures(txt)
    if stripped != txt:
        txt = stripped
        try:
            p.write_text(txt + "\n", encoding="utf-8")
        except Exception as e:
            print(f"[gate] strip signatures NON ecrit: {str(e)[:80]}")
    # L'identité de l'agent n'est PLUS écrite dans le message (décision owner
    # 2026-08-29). Elle est posée en NOTE git par `.githooks/post-commit`
    # (refs/notes/laforge-agent), qui réutilise `_agent()` / `_CHANNEL` ci-dessus.
    #
    # Pourquoi le trailer a été retiré : le contrat « identité locale, anonyme au
    # push » n'était pas tenu — les sha distants étaient IDENTIQUES aux locaux,
    # donc les trailers partaient en clair sur GitHub. Le tenir par réécriture au
    # push (`forge_anon_push`) produit des sha différents du local, or le superrepo
    # bumpe un gitlink qui doit exister au distant : il pointerait un commit absent
    # et le submodule serait irrécupérable au clone. Une note n'entre pas dans le
    # hash — elle identifie sans déplacer le commit — et `refs/notes/*` n'est pas
    # dans le refspec de push par défaut, donc elle reste locale.
    #
    # Provenance par acteur : `git log --notes=laforge-agent` (plus `--grep`).
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: forge_git_gate.py precommit | prepare-msg <file>")
        return 0
    cmd = argv[0]
    if cmd == "precommit":
        return _precommit()
    if cmd == "prepare-msg":
        return _prepare_msg(argv[1]) if len(argv) > 1 else 0
    print(f"[gate] sous-commande inconnue: {cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
