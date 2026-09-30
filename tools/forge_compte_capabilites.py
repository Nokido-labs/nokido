#!/usr/bin/env python3
"""forge_compte_capabilites — ce que CHAQUE compte d'execution peut reellement faire.

__FORGE_COLOR__ = "immunitaire/matrice-des-comptes"

POURQUOI
========
Nokido s'execute sous trois comptes — `LaForgeSbxOffline` (defaut), `LaForgeSbxOnline`
(`network=true`), `LaForgeTrusted` (`trusted_script`) — et PERSONNE ne mesurait ce que
chacun peut. Journee du 2026-09-03, quatre consequences payees :

  - la meme suite pytest rend 7 735/0 echec sous Offline et 7 735/11 sous Online ;
  - `git init` marche sous Offline, echoue sous Online (`cannot lock ref HEAD`) ;
  - `ls-tree HEAD` du superrepo est VIDE sous Trusted, donc « aucun drift » y est un
    faux negatif — j'ai declare un bump impossible que Offline a fait sans peine ;
  - le push du superrepo n'est possible sous AUCUN des trois : Offline le lit sans
    egress, Online a l'egress sans pouvoir lire son `.git`.

Un privilege qu'on ne mesure pas est un privilege qu'on ne surveille pas. Le P0 du
2026-09-01 — `sandbox=<valeur inconnue>` rendait `NT AUTHORITY\\SYSTEM`, une entree
INVALIDE obtenant plus de droits qu'une valide — n'etait pas subtil : c'etait
l'absence de test d'un privilege.

CE QUE CE MODULE FAIT
=====================
Lance sous un compte, il mesure les capacites de CE compte et ecrit sa fiche. Lance
avec `--rapport`, il agrege les fiches et les compare au socle : une capacite qui
APPARAIT est une elevation a instruire, une qui DISPARAIT est une panne a venir.
Les deux sont rouges — la surveillance ne va pas que dans un sens.

TROIS ETATS, jamais deux : `oui` · `non` · `indetermine` (avec la raison). Un test
qui n'a pas pu s'executer ne vaut pas un « non » : c'est ainsi qu'on fabrique des
faux negatifs indetectables.

Usage :
    LAFORGE_PYTHON tools/forge_compte_capabilites.py              # mesure ce compte
    LAFORGE_PYTHON tools/forge_compte_capabilites.py --rapport    # agrege + compare
    LAFORGE_PYTHON tools/forge_compte_capabilites.py --rapport --ecrire-socle
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
SUPER = ROOT.parent
FICHES = ROOT / "sandbox" / "capabilites_comptes"
SOCLE = ROOT / "tests" / "nr" / "_socle_capabilites_comptes.json"

OUI, NON, IND = "oui", "non", "indetermine"


def _compte() -> str:
    return "".join(c for c in (os.environ.get("USERNAME") or "anon")
                   if c.isalnum() or c == "_") or "anon"


def _ecriture(dossier: Path) -> tuple[str, str]:
    """Ecrire puis effacer un fichier temoin. Ne laisse rien derriere lui."""
    sonde = dossier / (".cap_%s_%d" % (_compte(), os.getpid()))
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass  # muet-ok : le dossier existe, c'est le cas nominal
    except OSError as e:
        # On n'a pas pu ATTEINDRE le dossier : ce n'est pas « ecriture refusee »,
        # c'est « je n'ai pas pu regarder ». Confondre les deux fabrique un faux
        # negatif indetectable — le defaut que cette matrice existe pour eviter.
        return IND, "dossier inatteignable: %s" % type(e).__name__
    try:
        sonde.write_text("x", encoding="utf-8")
    except OSError as e:
        return NON, type(e).__name__
    except Exception as e:  # noqa: BLE001
        return IND, "inattendu: %s" % type(e).__name__
    try:
        sonde.unlink()
    except OSError:
        pass  # muet-ok : le temoin survit au pire, la mesure est faite
    return OUI, ""


def _cmd(args: list[str], cwd: str | None = None) -> tuple[str, str]:
    try:
        import subprocess
        r = subprocess.run(args, capture_output=True, text=True, timeout=45,
                           errors="replace", cwd=cwd)
    except Exception as e:  # noqa: BLE001
        return IND, "non executable: %s" % type(e).__name__
    if r.returncode == 0:
        return OUI, ""
    return NON, (r.stderr or r.stdout or "").strip().splitlines()[-1][:120] if (
        r.stderr or r.stdout).strip() else "rc=%d sans message" % r.returncode


def _reseau(url: str) -> tuple[str, str]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as r:
            return (OUI, "") if r.status < 500 else (NON, "HTTP %d" % r.status)
    except Exception as e:  # noqa: BLE001
        return NON, type(e).__name__


def mesurer() -> dict:
    caps: dict[str, dict] = {}

    def pose(nom: str, res: tuple[str, str]) -> None:
        caps[nom] = {"etat": res[0], "detail": res[1]}

    for nom, d in (("ecrire_app", ROOT / "app"),
                   ("ecrire_tools", ROOT / "tools"),
                   ("ecrire_tests_nr", ROOT / "tests" / "nr"),
                   ("ecrire_sandbox", ROOT / "sandbox"),
                   ("ecrire_racine_depot", ROOT),
                   ("ecrire_racine_superrepo", SUPER)):
        pose(nom, _ecriture(d))

    pose("lire_git_superrepo",
         _cmd(["git", "-c", "safe.directory=*", "-C", str(SUPER), "rev-parse", "HEAD"]))
    pose("lire_git_depot",
         _cmd(["git", "-c", "safe.directory=*", "-C", str(ROOT), "rev-parse", "HEAD"]))

    bac = ROOT / "sandbox" / "capabilites_comptes" / ("gi_%s" % _compte())
    try:
        import shutil
        shutil.rmtree(bac, ignore_errors=True)
        bac.mkdir(parents=True, exist_ok=True)
        pose("git_init", _cmd(["git", "init", "-q", str(bac)]))
        shutil.rmtree(bac, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        pose("git_init", (IND, "bac indisponible: %s" % type(e).__name__))

    pose("egress_internet", _reseau("https://api.github.com"))
    pose("loopback_hub", _reseau("http://127.0.0.1:8766/health"))

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret
        pose("lire_coffre", (OUI, "") if (get_secret("FORGE_MCP_TOKEN") or "").strip()
             else (NON, "cle absente ou vide"))
    except Exception as e:  # noqa: BLE001
        pose("lire_coffre", (IND, "import impossible: %s" % type(e).__name__))

    # PRIVILEGES NOMMES, pas « la commande a repondu ». Mesurer que `whoami /priv`
    # s'execute rend « oui » pour TOUS les comptes, y compris un SYSTEM porteur de
    # SeDebug et SeTcb : c'est exactement la ligne qui n'aurait PAS vu le P0 du
    # 2026-09-01, ou une entree invalide obtenait NT AUTHORITY\\SYSTEM. Une capacite
    # toujours vraie ne surveille rien et donne l'illusion du contraire. On fige donc
    # chaque privilege SENSIBLE separement, present ou non.
    SENSIBLES = ("SeDebugPrivilege", "SeTcbPrivilege", "SeImpersonatePrivilege",
                 "SeBackupPrivilege", "SeRestorePrivilege", "SeTakeOwnershipPrivilege",
                 "SeLoadDriverPrivilege", "SeSecurityPrivilege")
    try:
        import subprocess
        r = subprocess.run(["whoami", "/priv"], capture_output=True, text=True,
                           timeout=45, errors="replace")
        sortie = (r.stdout or "") if r.returncode == 0 else ""
        lisible = r.returncode == 0 and bool(sortie.strip())
    except Exception as e:  # noqa: BLE001
        sortie, lisible = "", False
        caps["privileges_lecture"] = {"etat": IND, "detail": type(e).__name__}
    if lisible:
        caps["privileges_lecture"] = {"etat": OUI, "detail": ""}
        for p in SENSIBLES:
            caps["priv_" + p] = {"etat": OUI if p in sortie else NON, "detail": ""}
    else:
        # Illisible : on ne DECLARE PAS l'absence de privileges, on dit qu'on n'a
        # pas pu voir. « Aucun privilege detecte » et « je n'ai pas regarde » ne
        # doivent jamais rendre la meme valeur.
        caps.setdefault("privileges_lecture", {"etat": IND, "detail": "sortie vide"})
        for p in SENSIBLES:
            caps["priv_" + p] = {"etat": IND, "detail": "privileges non lus"}

    return {"compte": _compte(), "capacites": caps}


def _fiches() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        fichiers = sorted(FICHES.glob("*.json"))
    except OSError:
        return out
    for f in fichiers:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out[d["compte"]] = d["capacites"]
        except (OSError, ValueError, KeyError):
            continue
    return out


def rapport(ecrire_socle: bool = False) -> int:
    fiches = _fiches()
    if not fiches:
        print("aucune fiche : lancer ce script SOUS CHAQUE COMPTE d'abord "
              "(shell, shell network=true, trusted_script).")
        return 0
    noms = sorted({c for caps in fiches.values() for c in caps})
    comptes = sorted(fiches)
    print("=== MATRICE DES COMPTES (%d mesure(s)) ===" % len(comptes))
    print("%-26s %s" % ("capacite", "  ".join("%-14s" % c[:14] for c in comptes)))
    courant = {}
    for n in noms:
        ligne = []
        for c in comptes:
            e = (fiches[c].get(n) or {}).get("etat", IND)
            courant["%s::%s" % (c, n)] = e
            ligne.append("%-14s" % e)
        print("%-26s %s" % (n, "  ".join(ligne)))

    if ecrire_socle:
        SOCLE.parent.mkdir(parents=True, exist_ok=True)
        SOCLE.write_text(json.dumps(courant, indent=1, sort_keys=True), encoding="utf-8")
        print("\nsocle ECRIT : %d couple(s) compte::capacite" % len(courant))
        return 0

    try:
        socle = json.loads(SOCLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("\nsocle absent ou illisible : aucun verdict rendu. --ecrire-socle "
              "pour armer le cliquet.")
        return 0

    eleve = [k for k, v in courant.items()
             if socle.get(k) not in (None, v) and v == OUI and socle.get(k) == NON]
    perdu = [k for k, v in courant.items()
             if socle.get(k) == OUI and v == NON]
    inconnu = [k for k in courant if k not in socle]
    if eleve:
        print("\n/!\\ ELEVATION : %d capacite(s) ACQUISE(S) depuis le socle" % len(eleve))
        for k in eleve:
            print("      %s" % k)
    if perdu:
        print("\n/!\\ PERTE : %d capacite(s) DISPARUE(S) depuis le socle" % len(perdu))
        for k in perdu:
            print("      %s" % k)
    if inconnu:
        print("\n  %d couple(s) hors socle (mesure neuve) : regeler pour l'acter."
              % len(inconnu))
    if eleve or perdu:
        print("\nUne elevation est une faille a instruire ; une perte est une panne "
              "a venir. Les deux se regardent.")
        return 1
    print("\ncliquet OK — matrice conforme au socle (%d couple(s))." % len(socle))
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--rapport" in argv:
        return rapport(ecrire_socle="--ecrire-socle" in argv)
    fiche = mesurer()
    FICHES.mkdir(parents=True, exist_ok=True)
    cible = FICHES / ("%s.json" % fiche["compte"])
    cible.write_text(json.dumps(fiche, indent=1, ensure_ascii=False), encoding="utf-8")
    print("compte %s — fiche ecrite : %s" % (fiche["compte"], cible.name))
    for n, v in sorted(fiche["capacites"].items()):
        print("  %-26s %-12s %s" % (n, v["etat"], v["detail"][:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
