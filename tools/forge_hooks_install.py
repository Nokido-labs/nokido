#!/usr/bin/env python3
"""forge_hooks_install.py -- installe le FILET de gardes chez qui clone le depot.

POURQUOI
========
Mesure 2026-08-29 : `.gitignore` ignore tout `.claude/`, et les hooks Claude Code
vivent dans le profil de l'owner. Un clone nu n'herite donc d'AUCUN garde agent, et
les hooks git de `.githooks/` restent DORMANTS tant que `core.hooksPath` n'est pas
pose. Le depot presente l'auto-controle comme son argument central : sans cette
etape, la promesse n'est pas reproductible chez celui qui l'evalue.

SOURCE UNIQUE
=============
Le cablage attendu est lu dans `docs/claude_hooks_expected.json` (versionne,
regenere par `hook_integrity_check.py --capture`). Ce module ne DECRIT pas le
cablage, il le LIT : deux descriptions finissent toujours par diverger, une seule
ne peut pas. Les commandes sont reconstruites avec l'interpreteur et la racine
LOCAUX -- la reference ne porte que (event, script, matcher), jamais un chemin
absolu qui n'aurait de sens que sur la machine d'origine.

CE QU'IL NE FAIT PAS
====================
- Il ne REMPLACE jamais un cablage existant : fusion seulement. Un settings local
  porte aussi des choix propres a son proprietaire.
- Il n'ecrit rien sans `--apply` (dry-run par defaut, comme le reste du depot).

Usage :
    forge_hooks_install.py                 # etat, n'ecrit rien
    forge_hooks_install.py --apply         # pose core.hooksPath + cablages manquants
    forge_hooks_install.py --projet <dir>  # cible un autre repertoire de projet
"""

__FORGE_COLOR__ = "immunitaire/installation-du-filet-client"

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "docs" / "claude_hooks_expected.json"


def _git(*args):
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=30)
    return r.returncode, r.stdout.strip()


def _reference():
    """-> (cablage|None, motif). Trois etats : lue / absente / illisible."""
    try:
        return json.loads(REFERENCE.read_text(encoding="utf-8")).get("cablage", []), "lue"
    except FileNotFoundError:
        return None, "absente (lancer hook_integrity_check.py --capture)"
    except (OSError, json.JSONDecodeError) as e:
        return None, "illisible: %s" % e


def _script_path(nom):
    """Chemin LOCAL du script d'un cablage, ou None s'il est introuvable."""
    for d in ("tools", "app"):
        p = ROOT / d / nom
        if p.exists():
            return p
    return None


def _commande(nom, python_bin):
    return '"%s" "%s"' % (python_bin, str(_script_path(nom)).replace("\\", "/"))


def _cible(projet):
    return Path(projet) / ".claude" / "settings.local.json"


def _perimetre(projet):
    """Tous les settings que le client LIT, pas seulement celui qu'on ecrit.

    Claude Code fusionne le profil utilisateur ET les settings du projet : un
    cablage deja fourni par l'un ne doit pas etre re-ajoute dans l'autre, sinon le
    garde s'execute DEUX fois par evenement. Regression causee le 2026-08-29 :
    11 cablages du profil owner ont ete dupliques dans le settings du projet parce
    que l'installeur ne comparait qu'a sa cible.
    """
    return [
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.local.json",
        Path(projet) / ".claude" / "settings.json",
        _cible(projet),
    ]


def _deja_ailleurs(projet):
    """{(event, script)} fournis par un AUTRE settings que la cible."""
    cible = str(_cible(projet)).replace("\\", "/").lower()
    out = set()
    for p in _perimetre(projet):
        if str(p).replace("\\", "/").lower() == cible:
            continue
        data, _ = _charge(p)
        if data:
            out |= _presents(data)
    return out


def _charge(p):
    """-> (data, motif). Un fichier illisible n'est PAS un fichier vide."""
    try:
        return json.loads(p.read_text(encoding="utf-8")), "lu"
    except FileNotFoundError:
        return {}, "absent (sera cree)"
    except (OSError, json.JSONDecodeError) as e:
        return None, "illisible: %s" % e


def _presents(data):
    """{(event, script)} deja cables dans ce settings."""
    out = set()
    for event, entries in (data.get("hooks") or {}).items():
        for entry in entries or []:
            for h in entry.get("hooks") or []:
                cmd = h.get("command") or ""
                for token in cmd.replace("\\", "/").split("/"):
                    if token.strip('"').endswith(".py"):
                        out.add((event, token.strip('"')))
    return out


def etat(projet, python_bin):
    """Rapport SANS aucune ecriture."""
    ref, motif_ref = _reference()
    rc, hp = _git("config", "--get", "core.hooksPath")
    cible = _cible(projet)
    data, motif_data = _charge(cible)
    rapport = {
        "reference": motif_ref,
        "hooksPath": hp if rc == 0 and hp else "(non pose)",
        "settings": str(cible),
        "settings_etat": motif_data,
        "manquants": [],
        "scripts_absents": [],
    }
    if ref is None or data is None:
        # Une liste VIDE se lirait « rien ne manque ». Ici on n'a pas pu regarder :
        # le dire, sinon un settings illisible passe pour un filet complet.
        rapport["manquants"] = "(non evaluable -- reference ou settings illisible)"
        rapport["scripts_absents"] = "(non evaluable)"
        return rapport
    presents = _presents(data) | _deja_ailleurs(projet)
    for e in ref:
        nom, event = e.get("script", ""), e.get("event", "")
        if _script_path(nom) is None:
            rapport["scripts_absents"].append(nom)
            continue
        if (event, nom) not in presents:
            rapport["manquants"].append("%s/%s" % (event, nom))
    return rapport


def elague(projet):
    """Retire de la CIBLE les cablages qu'un AUTRE settings fournit deja.

    Un doublon n'est pas inerte : le hook s'execute une fois par declaration. Le
    profil utilisateur reste la source ; c'est la copie locale qui degage.
    """
    cible = _cible(projet)
    data, motif = _charge(cible)
    if not data:
        return {"ok": False, "raison": "settings %s" % motif}
    ailleurs, retires = _deja_ailleurs(projet), []
    for event, entries in list((data.get("hooks") or {}).items()):
        gardees = []
        for entry in entries or []:
            scripts = {s.strip('"') for h in entry.get("hooks") or []
                       for s in (h.get("command") or "").replace("\\", "/").split("/")
                       if s.strip('"').endswith(".py")}
            if scripts and all((event, s) in ailleurs for s in scripts):
                retires.append("%s/%s" % (event, ", ".join(sorted(scripts))))
            else:
                gardees.append(entry)
        data["hooks"][event] = gardees
    cible.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "retires": retires, "settings": str(cible)}


def applique(projet, python_bin):
    ref, motif = _reference()
    if ref is None:
        return {"ok": False, "raison": "reference %s" % motif}
    _git("config", "core.hooksPath", ".githooks")
    cible = _cible(projet)
    data, motif_data = _charge(cible)
    if data is None:
        return {"ok": False, "raison": "settings %s -- refus d'ecraser" % motif_data}
    hooks = data.setdefault("hooks", {})
    # Presents = ceux de la cible ET ceux que tout autre settings du perimetre
    # fournit deja : reinstaller un cablage existant le fait tirer DEUX fois.
    presents = _presents(data) | _deja_ailleurs(projet)
    ajoutes = []
    for e in ref:
        nom, event, matcher = e.get("script", ""), e.get("event", ""), e.get("matcher", "")
        if (event, nom) in presents or _script_path(nom) is None:
            continue
        hooks.setdefault(event, []).append({
            "matcher": matcher,
            "hooks": [{"type": "command", "command": _commande(nom, python_bin)}],
        })
        ajoutes.append("%s/%s" % (event, nom))
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    rc, hp = _git("config", "--get", "core.hooksPath")
    return {"ok": True, "hooksPath": hp, "ajoutes": ajoutes, "settings": str(cible)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--projet", default=str(ROOT.parent),
                    help="repertoire de projet cible (defaut: parent du depot)")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreteur a inscrire dans les commandes de hook")
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut: dry-run)")
    ap.add_argument("--prune", action="store_true",
                    help="retire de la cible les cablages qu'un autre settings fournit deja")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.prune:
        res = elague(args.projet)
    elif args.apply:
        res = applique(args.projet, args.python)
    else:
        res = etat(args.projet, args.python)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    for k, v in res.items():
        print("  %-16s %s" % (k, v if not isinstance(v, list) else (", ".join(v) or "(aucun)")))
    if not args.apply:
        print("\nDRY-RUN : rien ecrit. Relancer avec --apply pour installer le filet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
