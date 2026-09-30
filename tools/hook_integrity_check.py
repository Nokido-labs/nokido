#!/usr/bin/env python3
"""hook_integrity_check.py — SessionStart : vérifie le filet de hooks AVANT la session.

Pourquoi : skipAutoPermissionPrompt + skipDangerousModePermissionPrompt sont actifs
dans ~/.claude/settings.json => AUCUN prompt de permission de secours. Les hooks
(bash_guard, hook_search_guard, forge_tool_gate, ...) sont l'UNIQUE garde. Claude
Code IGNORE un hook dont la commande échoue : un script supprimé/déplacé/cassé =
garde morte EN SILENCE. Ce hook rend la panne BRUYANTE au démarrage de session.

Trois états par cible, jamais deux (RULES_SHARED 2026-07-30) :
  OK        — le script existe et compile (compile() en mémoire, pas py_compile
              qui échoue sur __pycache__ sous ACL restreinte)
  MORT      — prouvé absent OU SyntaxError
  ILLISIBLE — pas pu regarder (ACL/IO) : ne se lit JAMAIS comme un OK

Anti-dup : forge_embolie_scanner._check_hooks_integrity ne vérifie que l'UTF-8 de
2 hooks Gemini côté corps ; ici = existence+compile de TOUS les hooks câblés côté
client Claude Code, au moment utile (SessionStart). Recouvrement quasi nul.

Câblé : ~/.claude/settings.json -> hooks.SessionStart (PREMIER hook, timeout 5s).
Auto-test : LAFORGE_PYTHON tools/hook_integrity_check.py --settings <f.json> --json
Doc : docs/claude_hooks_architecture.md
"""

__FORGE_COLOR__ = "immunitaire/garde-integrite-hooks-client"

import json
import os
import re
import sys
from pathlib import Path

_TOKEN_RE = re.compile(r'"([^"]+)"|(\S+)')
_CHECKABLE_EXT = (".py", ".exe", ".ps1", ".bat", ".cmd")


def _iter_hook_commands(settings):
    for _event, entries in (settings.get("hooks") or {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for h in entry.get("hooks") or []:
                cmd = isinstance(h, dict) and h.get("command")
                if cmd:
                    yield _event, entry.get("matcher", ""), cmd


def _targets_from_command(cmd):
    """Chemins vérifiables d'une commande hook (interpréteur + script)."""
    out = []
    for m in _TOKEN_RE.finditer(cmd):
        tok = os.path.expandvars((m.group(1) or m.group(2) or "").strip())
        if tok and not tok.startswith("-") and tok.lower().endswith(_CHECKABLE_EXT):
            out.append(tok)
    return out


def _check_target(path_str):
    """-> (etat, detail), etat dans {ok, mort, illisible}."""
    p = Path(path_str)
    try:
        if not p.exists():
            return "mort", "absent"
    except OSError as e:
        return "illisible", "exists() en erreur: %s" % e
    if p.suffix.lower() != ".py":
        return "ok", "present (non-python)"
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "illisible", "lecture refusee: %s" % e
    try:
        compile(src, str(p), "exec")
    except SyntaxError as e:
        return "mort", "SyntaxError l.%s: %s" % (e.lineno, e.msg)
    return "ok", "present + compile"


def _settings_files(cli_paths):
    if cli_paths:
        return [Path(x) for x in cli_paths]
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return [
        Path.home() / ".claude" / "settings.json",
        Path(proj) / ".claude" / "settings.json",
        Path(proj) / ".claude" / "settings.local.json",
    ]


def _inventaire_settings(cli_paths=None):
    """-> [(chemin, etat)], etat dans {lu, absent, illisible: <raison>}.

    Un fichier de settings qu'on ne lit pas ne dit rien de lui-meme. Mesure
    2026-08-29 : sous le compte de service du hub, `~/.claude/settings.json`
    ressort ABSENT alors qu'il EXISTE (ACL du profil owner). Une enumeration faite
    de la se lit comme « pas de hooks » au lieu de « pas pu regarder » : trois
    etats, jamais deux (RULES_SHARED 2026-07-30).
    """
    out = []
    for sf in _settings_files(cli_paths):
        try:
            sf.read_text(encoding="utf-8")
            out.append((str(sf), "lu"))
        except FileNotFoundError:
            out.append((str(sf), "absent"))
        except OSError as e:
            out.append((str(sf), "illisible: %s" % e))
    return out


def _settings_orphelins(cli_paths=None):
    """Settings PRESENTS sur le disque mais HORS du perimetre lu.

    Mesure 2026-08-29, payee trois tours : deux `.claude/settings.local.json`
    coexistent — racine du projet et sous-dossier `Nokido/` — et SEUL celui de la
    racine est charge. Deux matchers morts ont ete corriges dans l'autre, verifies
    dans l'autre, et annonces repares : ils sont restes morts. Un fichier de config
    CORRECT n'est pas un fichier de config CHARGE, et rien ne le disait.
    """
    inspectes = {str(p).replace("\\", "/").lower() for p in _settings_files(cli_paths)}
    racine = Path(__file__).resolve().parent.parent
    orphelins = []
    for base in (racine, racine.parent, Path.home()):
        for nom in ("settings.json", "settings.local.json"):
            p = base / ".claude" / nom
            try:
                if not p.exists():
                    continue
            except OSError:  # muet-ok : ACL -> on ne peut rien affirmer sur ce chemin
                continue
            if str(p).replace("\\", "/").lower() not in inspectes:
                orphelins.append(str(p))
    return sorted(set(orphelins))


# Scripts de garde du dépôt : hook_*.py + *_guard.py. Un garde qui existe sur le
# disque mais qu'AUCUN settings inspecté ne câble est soit DORMANT (jamais branché),
# soit câblé HORS périmètre (plugin, managed-settings) — mesuré le 2026-08-02 :
# bash_guard MORD alors qu'il n'est dans aucun des 3 fichiers inspectés, et
# hook_posttool_validate (validation AST promise par CLAUDE.md) n'était câblé nulle
# part. Le check d'origine ne voyait QUE les scripts câblés : il ne pouvait pas
# signaler un garde promis-mais-absent. On croise donc l'existant avec le câblé.
# Hooks CLIENT uniquement : préfixe `hook_` + exceptions nommées (bash_guard n'a pas
# le préfixe mais EST un hook PreToolUse:Bash). On EXCLUT volontairement les
# `forge_*_guard.py` (firehose/license/log) : ce sont des modules INTERNES du gate,
# pas des hooks Claude Code — les lister ferait crier le garde à faux, et un garde
# qui crie à faux se fait désarmer (RULES_SHARED 2026-07-30).
_HOOKS_SANS_PREFIXE = {"bash_guard.py"}

# Le CABLAGE ATTENDU, versionne dans le depot. Pourquoi : les settings qui pilotent
# reellement les hooks vivent dans le PROFIL OWNER (~/.claude/settings.json), hors
# depot, donc hors CI et hors revue -- personne ne voit un matcher se retrecir.
# Mesure 2026-08-29 : hook_posttool_validate etait cable sur "Write|Edit" alors que
# l'enforce thin-client deny justement Write/Edit sur Nokido. Le script existait et
# compilait, donc ce verificateur le comptait OK ("18 cibles, toutes OK") pendant
# qu'il ne tournait sur AUCUNE edition du depot. Verifier la CIBLE ne dit rien de la
# COUVERTURE : un garde branche sur un evenement que plus personne n'emet est mort.
_REFERENCE = Path(__file__).resolve().parent.parent / "docs" / "claude_hooks_expected.json"


def _reference():
    """-> (ref|None, etat). Trois etats, jamais deux : presente / absente / illisible."""
    try:
        return json.loads(_REFERENCE.read_text(encoding="utf-8")), "ok"
    except FileNotFoundError:
        return None, "absente"
    except (OSError, json.JSONDecodeError) as e:
        return None, "illisible: %s" % e


def _est_hook(cible):
    """Un INTERPRETEUR n'est pas un hook. `_targets_from_command` rend aussi
    python.exe : le figer dans la reference lui attribue le matcher du PREMIER hook
    qui l'invoque, donc un simple reordonnancement des entrees crierait DERIVE sans
    qu'aucun cablage n'ait bouge. Un garde qui crie a faux se fait desarmer
    (RULES_SHARED 2026-07-30) : on garde les SCRIPTS, pas ce qui les execute."""
    return not Path(cible).name.lower().endswith(".exe")


def _ecarts_au_reference(rows, ref):
    """Cablage REEL vs cablage versionne. Rend [(genre, cle, attendu, reel)]."""
    reels = {}
    for r in rows:
        if r.get("cible") and _est_hook(r["cible"]):
            reels[(r.get("event", ""), Path(r["cible"]).name)] = r.get("matcher", "")
    ecarts = []
    for att in ref.get("cablage", []):
        cle = (att.get("event", ""), att.get("script", ""))
        libelle = "%s -> %s" % cle
        if cle not in reels:
            ecarts.append(("ABSENT", libelle, att.get("matcher", ""), "(non cable)"))
        elif reels[cle] != att.get("matcher", ""):
            ecarts.append(("DERIVE", libelle, att.get("matcher", ""), reels[cle]))
    return ecarts


def _capture(rows):
    """Fige le cablage courant comme reference. JAMAIS automatique : une reference
    qui suit la derive ne garde plus rien (c'est le principe du cliquet)."""
    cablage = [{"event": r.get("event", ""), "script": Path(r["cible"]).name,
                "matcher": r.get("matcher", "")}
               for r in rows if r.get("cible") and _est_hook(r["cible"])]
    cablage.sort(key=lambda d: (d["event"], d["script"]))
    _REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    _REFERENCE.write_text(json.dumps(
        {"_note": "Cablage hooks attendu. Regenerer SCIEMMENT via "
                  "hook_integrity_check.py --capture, jamais en automatique.",
         "cablage": cablage}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(cablage)


def _guardes_du_depot():
    tools = Path(__file__).resolve().parent
    vus = {}
    try:
        for p in tools.iterdir():
            n = p.name
            if p.suffix == ".py" and (n.startswith("hook_") or n in _HOOKS_SANS_PREFIXE):
                vus[n] = p
    except OSError:  # muet-ok : tools/ illisible -> 0 garde listé, le check principal a déjà parlé
        pass
    return vus


def _dormants(rows):
    """Gardes présents sur disque mais référencés par AUCUNE commande câblée."""
    cables = {Path(r["cible"]).name for r in rows if r.get("cible")}
    dormants = []
    for nom, chemin in sorted(_guardes_du_depot().items()):
        if nom in cables:
            continue
        etat, _ = _check_target(str(chemin))
        # Un garde dont le script est cassé compte double : dormant ET mort.
        dormants.append({"garde": nom, "compile": etat})
    return dormants


def _doublons(rows):
    """Meme (event, matcher, cible) declare dans PLUSIEURS settings lus.

    Le dedup de `run_check` est volontairement PAR FICHIER (cf. son commentaire du
    2026-08-29 : deux settings peuvent cabler le meme script avec des matchers
    DIFFERENTS, et fusionner rendrait le second invisible). Le croisement ci-dessous
    est ce qu'il ne dit PAS : a matcher IDENTIQUE, le hook tire une fois par fichier.

    Mesure 2026-09-19 : 11 hooks declares a la fois dans ~/.claude/settings.json et
    dans <projet>/.claude/settings.local.json -- dont ce verificateur lui-meme, qui
    annoncait "60 cablages verifies, tous OK" sans jamais regarder d'un fichier a
    l'autre. Un instrument aveugle a sa propre duplication.
    """
    par_cle = {}
    for r in rows:
        if "event" not in r:  # ligne d'erreur (settings illisible/mort) : pas un cablage
            continue
        cle = (r["event"], r.get("matcher", ""), r["cible"])
        par_cle.setdefault(cle, set()).add(r["settings"])
    return sorted(((cle, sorted(f)) for cle, f in par_cle.items() if len(f) > 1),
                  key=lambda x: (x[0][0], x[0][2], x[0][1]))


def _recouvrements(rows):
    """Meme (event, cible) dans PLUSIEURS settings, avec des matchers DIFFERENTS.

    Ce n'est PAS un doublon certain : ce peut etre le cas legitime du 2026-08-29
    (deux matchers complementaires), ou deux regex qui SE RECOUVRENT -- auquel cas
    le hook tire bien deux fois sur les outils communs. Decider de l'inclusion de
    deux regex n'est pas a la portee de ce verificateur : on NOMME le cas au lieu
    de trancher, troisieme etat entre "doublon" et "distinct".

    Mesure 2026-09-19 : `hook_capability_gate` est cable `...__run|Bash` d'un cote
    et `...__run|Bash|PowerShell|mcp__playwright__.*` de l'autre. Le second CONTIENT
    le premier, le garde s'affichait deux fois sur un simple appel Bash, et le test
    d'egalite des matchers ne voyait rien. Un garde ne vaut que par le nombre de
    portes qu'il tient.
    """
    par_cle = {}
    for r in rows:
        if "event" not in r:  # ligne d'erreur : pas un cablage
            continue
        par_cle.setdefault((r["event"], r["cible"]), set()).add(
            (r["settings"], r.get("matcher", "")))
    out = []
    for cle, paires in par_cle.items():
        if len({s for s, _ in paires}) > 1 and len({m for _, m in paires}) > 1:
            out.append((cle, sorted(paires)))
    return sorted(out, key=lambda x: (x[0][0], x[0][1]))


def run_check(cli_paths=None):
    # Dedup par CABLAGE (fichier, event, matcher, cible) et non par cible : un meme
    # script peut etre cable plusieurs fois avec des matchers DIFFERENTS, et n'en
    # retenir qu'un rend les autres invisibles. Mesure 2026-08-29 :
    # hook_posttool_validate etait cable dans le profil owner ET dans le
    # settings.local.json du projet ; le matcher du second, reste mort, n'apparaissait
    # nulle part. Meme cas pour bash_guard (Bash + PowerShell).
    # Le resultat de _check_target reste mis en cache PAR CIBLE : on ne recompile pas
    # le meme fichier N fois pour autant.
    rows, seen, cache = [], set(), {}
    for sf in _settings_files(cli_paths):
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except FileNotFoundError:  # muet-ok : settings absent = legitime (pas de local)
            continue
        except OSError as e:
            rows.append({"settings": str(sf), "cible": str(sf),
                         "etat": "illisible", "detail": str(e)})
            continue
        except json.JSONDecodeError as e:
            rows.append({"settings": str(sf), "cible": str(sf),
                         "etat": "mort", "detail": "JSON invalide: %s" % e})
            continue
        for event, matcher, cmd in _iter_hook_commands(data):
            for tgt in _targets_from_command(cmd):
                cle = (str(sf), event, matcher, tgt)
                if cle in seen:
                    continue
                seen.add(cle)
                if tgt not in cache:
                    cache[tgt] = _check_target(tgt)
                etat, detail = cache[tgt]
                rows.append({"settings": str(sf), "event": event,
                             "matcher": matcher, "cible": tgt,
                             "etat": etat, "detail": detail})
    return rows


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", action="append", default=[],
                    help="fichier(s) settings a verifier (defaut: global+projet)")
    ap.add_argument("--json", action="store_true", help="sortie JSON (tests)")
    ap.add_argument("--capture", action="store_true",
                    help="fige le cablage courant dans docs/claude_hooks_expected.json")
    args = ap.parse_args(argv)

    rows = run_check(args.settings)
    morts = [r for r in rows if r["etat"] == "mort"]
    illisibles = [r for r in rows if r["etat"] == "illisible"]

    if args.json:
        # `ok` ne bascule PAS sur les doublons : on observe avant d'enforcer.
        print(json.dumps({"ok": not morts and not illisibles, "n": len(rows),
                          "morts": morts, "illisibles": illisibles,
                          "doublons": [{"event": e, "matcher": m, "cible": c,
                                        "settings": f, "n_executions": len(f)}
                                       for (e, m, c), f in _doublons(rows)],
                          "recouvrements": [{"event": e, "cible": c,
                                             "cablages": [{"settings": s,
                                                           "matcher": m}
                                                          for s, m in paires]}
                                            for (e, c), paires in _recouvrements(rows)]},
                         ensure_ascii=False))
        return 0

    if not rows:
        # Rien vu ≠ tout va bien : le dire explicitement (source qui se tait).
        print("[hook-integrity] ALERTE : AUCUN hook trouve dans les settings — "
              "verifier chemins/CLAUDE_PROJECT_DIR (rien vu != rien a garder).")
        return 0
    if args.capture:
        print("[hook-integrity] reference capturee : %d entrees -> %s"
              % (_capture(rows), _REFERENCE))
        return 0
    inv = _inventaire_settings(args.settings)
    n_lus = sum(1 for _, e in inv if e == "lu")
    for chemin, etat in inv:
        if etat.startswith("illisible"):
            print("[hook-integrity] settings %s -- %s (pas pu regarder != pas de hooks)"
                  % (chemin, etat))
    for orph in _settings_orphelins(args.settings):
        print("[hook-integrity] SETTINGS ORPHELIN %s : present sur le disque mais HORS "
              "du perimetre lu -- l'editer n'a AUCUN effet sur les hooks actifs" % orph)
    for (event, matcher, cible), fichiers in _doublons(rows):
        # NON bloquant : un doublon ne troue pas le filet, il le fait tirer deux fois
        # (latence doublee sur CHAQUE appel d'outil, sorties dupliquees en contexte).
        print("[hook-integrity] DOUBLON %s / matcher=%s -> %s : declare dans %d "
              "settings, donc EXECUTE %d fois par evenement (%s)"
              % (event, matcher or "*", cible, len(fichiers), len(fichiers),
                 " + ".join(fichiers)))
    for (event, cible), paires in _recouvrements(rows):
        # Troisieme etat : ni doublon certain, ni distinct. A INSTRUIRE, pas a trancher.
        print("[hook-integrity] RECOUVREMENT A INSTRUIRE %s -> %s : cable dans %d "
              "settings avec des matchers DIFFERENTS -- s'ils se recouvrent, le hook "
              "tire deux fois sur les outils communs :" % (event, cible, len(paires)))
        for s, m in paires:
            print("    %s  matcher=%s" % (s, m or "*"))
    dormants = _dormants(rows)
    if morts or illisibles:
        print("[hook-integrity] ⚠️ FILET DE HOOKS TROUE — prompts de permission "
              "DESACTIVES, ces gardes sont l'unique filet :")
        for r in morts:
            print("  MORT      %s — %s" % (r["cible"], r["detail"]))
        for r in illisibles:
            print("  ILLISIBLE %s — %s (pas pu verifier != OK)" % (r["cible"], r["detail"]))
        print("[hook-integrity] Reparer AVANT toute action sensible. "
              "Carte: LaForge/docs/claude_hooks_architecture.md")
    else:
        print("[hook-integrity] %d cablages hook verifies, tous OK (%d settings lus)"
              % (len(rows), n_lus))
    ref, etat_ref = _reference()
    if ref is not None:
        for genre, cle, attendu, reel in _ecarts_au_reference(rows, ref):
            print("[hook-integrity] CABLAGE %s : %s\n    attendu: %s\n    reel   : %s"
                  % (genre, cle, attendu, reel))
    elif etat_ref == "absente":
        # Ne PAS se taire : sans reference, la couverture n'est pas gardee du tout.
        # Un garde qui attend en silence un fichier que personne n'a cree est dormant.
        print("[hook-integrity] aucune reference de cablage -- la COUVERTURE des hooks "
              "n'est pas gardee. Figer l'etat courant : "
              "LAFORGE_PYTHON tools/hook_integrity_check.py --capture")
    else:
        # Illisible n'est pas OK : le dire (source qui se tait).
        print("[hook-integrity] reference de cablage %s -- couverture NON verifiee"
              % etat_ref)
    if dormants:
        # NON bloquant, mais visible : un garde existe et n'est câblé nulle part
        # dans les settings inspectés. Peut être normal (câblé via plugin/managed,
        # hors des 3 fichiers) — à vérifier, jamais à ignorer par défaut.
        print("[hook-integrity] gardes PRESENTS mais NON cables dans les settings "
              "inspectes (dormant, OU cable hors perimetre plugin/managed) :")
        for d in dormants:
            suff = "" if d["compile"] == "ok" else " [%s]" % d["compile"]
            print("  DORMANT   %s%s" % (d["garde"], suff))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # fail-LOUD : un verificateur casse muet = pire que rien
        print("[hook-integrity] PANNE DU VERIFICATEUR (%s: %s) — le filet de hooks "
              "n'est PAS verifie ce demarrage." % (type(e).__name__, e))
        sys.exit(0)
