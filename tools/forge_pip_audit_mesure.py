# -*- coding: utf-8 -*-
"""Produit un rapport pip-audit DATE, la ou le reseau existe.

__FORGE_COLOR__ = "qualite/build : mesure deportee de la chaine d approvisionnement"

POURQUOI CE MODULE (2026-09-07). Le gate `pip-audit` de `ci_local` tourne sous le
compte de la CI, qui n'a PAS d'egress : `pypi.org` rend `WinError 10013`, l'audit meurt
en 1,3 s sans lire un paquet, et le gate etant `warn` son rc non nul s'affichait ✅.
Un domaine declare CRITIQUE n'avait donc AUCUN verdict depuis toujours.

⚠️ Et il n'existe AUCUN suppleant : `.github/workflows/ci-selfhosted.yml` INSTALLE
pip-audit (`pip install ... pip-audit`, ligne 93) et ne le LANCE jamais. La chaine
d'approvisionnement n'etait auditee nulle part.

La separation est donc : **ce script MESURE** (lance via `run_job online=true`, le seul
compte avec egress) et **le gate JUGE** la fraicheur de ce qu'il trouve. Le producteur
ecrit la ou `forge_deps_reconcilier.rapport_courant()` cherche deja -- on reutilise sa
selection du plus recent, corrigee le 2026-09-07, au lieu d'en ecrire une seconde.

🔑 **REGLE ABSOLUE : ne JAMAIS ecrire de rapport quand la mesure a echoue.** Un fichier
frais et vide se relirait comme « aucune vulnerabilite », et fabriquerait exactement le
faux calme que ce chantier supprime. Un echec sort en rc non nul, sans fichier.

    LAFORGE_PYTHON tools/forge_pip_audit_mesure.py        (via run_job online=true)
    LAFORGE_PYTHON tools/forge_pip_audit_mesure.py --tous-les-envs

PHASE 3 (2026-10-13) — `--tous-les-envs`. Le 12/10, l'environnement des SERVICES
(miniforge base, 835 paquets) portait 67 paquets vulnerables que personne ne voyait :
Dependabot ne lit que les manifestes du depot, et ce script ne decrivait que SON
interpreteur. Le drapeau audite ensuite chaque env conda (liste demandee a conda) et
chaque env `uv tool` de l'owner, un rapport par env (`sandbox/audit_envs_<env>_<date>.json`,
hors du glob `pip_audit*` que lisent le gate et `forge_deps_reconcilier`), plus une
synthese qui nomme aussi ce qui n'a PAS ete vu. Un env illisible n'est jamais un env sain.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "sandbox"
CACHE = SANDBOX / "pip_audit_cache"

# Marqueurs de NON-MESURE, identiques a ceux que `ci_local` lit dans la sortie du
# gate : une seule definition du symptome, deux lecteurs.
MOTIFS_NON_MESURE = (
    "NewConnectionError",
    "Max retries exceeded",
    "Failed to establish a new connection",
    "requests.exceptions.ConnectionError",
    "Failed to read from cache directory",
)


def enveloppe_meta(deps) -> dict:
    """Ce rapport est la propriete de QUEL environnement — et de combien.

    ⚠️ `OBSERVED(X) != PROPERTY_OF(X)`. Un rapport anonyme se lit comme « les
    dependances », alors qu'il ne decrit que CELLES D'UN interpreteur. Mesure du
    2026-09-20 : les `run_job` s'executent sous `miniforge3/envs/laforge_py314`
    (preuve dans le wrapper genere du job), donc cette mesure decrit la CI :

        laforge_py314 (CI)   226 paquets audites,  1 a 5 touches
        miniforge3    (hub)  835 paquets audites, 66 touches

    609 paquets de l'environnement qui fait tourner le corps n'etaient audites
    par personne, et le gate acceptait ce rapport en suppleant en jugeant sa
    FRAICHEUR et jamais sa PORTEE.

    Nommer ne corrige pas la portee. Mais une portee anonyme ne peut meme pas
    etre jugee : c'est le prealable.
    """
    deps = list(deps or [])
    touches = [d for d in deps if isinstance(d, dict) and d.get("vulns")]
    return {
        "interpreteur": sys.executable,
        "n_paquets_audites": len(deps),
        "n_paquets_touches": len(touches),
        "n_avis": sum(len(d.get("vulns") or []) for d in touches),
        # Un perimetre vide n'est pas « rien a signaler » : c'est un instrument
        # aveugle, et il doit se NOMMER tel plutot que de rendre un zero
        # rassurant que le gate lirait comme un succes.
        "portee": "AUCUNE" if not deps else "ENVIRONNEMENT_DE_CET_INTERPRETEUR",
    }


def _sortie(cible: Path, site=None) -> list:
    """Lance pip-audit en JSON. Rend (rc, texte_brut).

    `site` : le site-packages d'un AUTRE env. pip-audit tourne alors depuis cet
    interpreteur-ci et ne lit que les distributions de ce dossier (`--path`) : l'env
    audite n'a pas besoin de porter pip-audit (mesure du 12/10 : le base ne l'avait pas)."""
    cmd = [sys.executable, "-m", "pip_audit", "--progress-spinner=off",
           "--cache-dir", str(CACHE), "--format", "json", "--output", str(cible)]
    if site:
        cmd += ["--path", str(site)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       errors="replace", timeout=1800)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# --- PHASE 3 : l'inventaire des envs du poste ----------------------------------------

def _etat_dossier(p: Path) -> str:
    """`OK` | `ABSENT` | `ILLISIBLE (<cause>)` -- trois etats, jamais deux.

    `Path.is_dir()` rend False sur un acces refuse comme sur une absence : un env
    illisible se lirait « absent », donc « rien a auditer ». On LIT le contenu.
    Mesure du 2026-10-13 : le `%APPDATA%/uv/tools` de l'owner rend WinError 5 depuis
    LaForgeSbxOffline."""
    try:
        os.listdir(p)
        return "OK"
    except (FileNotFoundError, NotADirectoryError):
        return "ABSENT"
    except OSError as e:
        return "ILLISIBLE (%s)" % type(e).__name__


def _racine_conda():
    """La racine conda qui porte CET interpreteur (un job tourne dans un env de la racine)."""
    pref = Path(sys.prefix)
    if pref.parent.name == "envs":
        pref = pref.parent.parent
    return pref if _etat_dossier(pref / "conda-meta") == "OK" else None


def _envs_conda(racine: Path):
    """La liste des envs, demandee a conda LUI-MEME plutot que deduite de `envs/` :
    un env cree par `-p` ailleurs n'y figure pas. Rend (prefixes, erreur | None)."""
    py = racine / ("python.exe" if os.name == "nt" else "bin/python")
    try:
        r = subprocess.run([str(py), "-m", "conda", "env", "list", "--json"],
                           capture_output=True, text=True, errors="replace", timeout=180)
        envs = json.loads(r.stdout or "{}").get("envs") or []
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError) as e:
        return [], "conda env list illisible (%s)" % type(e).__name__
    if r.returncode != 0 or not envs:
        return [], "conda env list rc=%s, %d env(s) : %s" % (
            r.returncode, len(envs), (r.stderr or "").strip()[-200:])
    return [Path(e) for e in envs], None


def _dossier_uv_tools(racine, impose=None):
    """Ou vivent les envs `uv tool` de l'OWNER -- et d'ou vient ce chemin.

    Le job tourne sous un compte de sandbox : SON `%APPDATA%` n'est pas celui de
    l'owner, `uv tool dir` repondrait pour le mauvais profil. Ordre : `--uv-tools`,
    `UV_TOOL_DIR`, puis le profil qui porte la racine conda (miniforge s'installe dans
    le profil de l'owner) -- ce dernier est une DEDUCTION, et la synthese le dit."""
    if impose:
        return Path(impose), "--uv-tools"
    if os.environ.get("UV_TOOL_DIR"):
        return Path(os.environ["UV_TOOL_DIR"]), "UV_TOOL_DIR"
    if racine is None:
        return None, "aucune racine conda pour situer le profil de l'owner"
    origine = "deduit du profil de la racine conda"
    if os.name == "nt":
        return racine.parent / "AppData" / "Roaming" / "uv" / "tools", origine
    return racine.parent / ".local" / "share" / "uv" / "tools", origine


def _site_packages(prefix: Path):
    """(site-packages, etat) d'un env : `Lib/site-packages` (Windows) ou
    `lib/python3.*/site-packages` (POSIX). L'etat est celui du dossier LU."""
    win = prefix / "Lib" / "site-packages"
    etat = _etat_dossier(win)
    if etat != "ABSENT" or os.name == "nt":
        return win, etat
    lib = prefix / "lib"
    etat_lib = _etat_dossier(lib)
    if etat_lib != "OK":
        return lib, etat_lib
    cands = sorted(lib.glob("python3*/site-packages"))
    if not cands:
        return lib, "ABSENT"
    return cands[-1], _etat_dossier(cands[-1])


def _classer(env: dict, prefix: Path, ici: Path, cibles: list, non_vus: list,
             couverts: list) -> None:
    try:
        meme = prefix.resolve() == ici
    except OSError:
        meme = False
    if meme:
        couverts.append(dict(env, etat="COUVERT",
                             pourquoi="interpreteur auditeur : decrit par le rapport principal"))
        return
    site, etat = _site_packages(prefix)
    if etat == "OK":
        cibles.append(dict(env, site=str(site)))
    else:
        non_vus.append(dict(env, site=str(site), etat=etat))


def envs_a_auditer(uv_tools=None, ici=None) -> dict:
    """Tous les envs du poste : `{cibles, non_vus, couverts}`.

    Chaque env porte son ETAT. Un env qu'on n'a pas pu lire est un NON_VU nomme avec
    sa cause -- jamais un env sans faille, jamais un env oublie."""
    ici = Path(ici or sys.prefix).resolve()
    cibles, non_vus, couverts = [], [], []
    racine = _racine_conda()
    envs = []
    if racine is None:
        non_vus.append({"nom": "conda", "type": "conda", "etat": "NON_TROUVE",
                        "pourquoi": "l'interpreteur auditeur ne vit pas dans une racine conda"})
    else:
        envs, err = _envs_conda(racine)
        if err:
            non_vus.append({"nom": "conda", "type": "conda", "etat": "ILLISIBLE",
                            "pourquoi": err})
    for prefix in envs:
        nom = "base" if prefix == racine else prefix.name
        _classer({"nom": nom, "type": "conda", "prefix": str(prefix)},
                 prefix, ici, cibles, non_vus, couverts)
    dossier, origine = _dossier_uv_tools(racine, uv_tools)
    etat = _etat_dossier(dossier) if dossier is not None else "NON_TROUVE"
    if etat != "OK":
        non_vus.append({"nom": "uv-tools", "type": "uv_tool", "etat": etat,
                        "prefix": str(dossier) if dossier else None, "pourquoi": origine})
        return {"cibles": cibles, "non_vus": non_vus, "couverts": couverts}
    for t in sorted(os.listdir(dossier)):
        p = dossier / t
        if t.startswith(".") or _etat_dossier(p) == "ABSENT":
            continue  # `.lock`, `.gitignore` : des fichiers du dossier, pas des envs
        _classer({"nom": t, "type": "uv_tool", "prefix": str(p), "origine": origine},
                 p, ici, cibles, non_vus, couverts)
    return {"cibles": cibles, "non_vus": non_vus, "couverts": couverts}


# --- PHASE 3 : la mesure de chaque env, la synthese, le signal ------------------------

def _lire_mesure(provisoire: Path, rc: int, texte: str):
    """(donnees, deps, None) si la mesure a eu lieu, sinon (None, None, raison).
    Memes criteres de NON-MESURE que `main` : motif reseau, aucun fichier, rapport
    illisible, zero paquet lu."""
    motif = next((m for m in MOTIFS_NON_MESURE if m in texte), None)
    if motif:
        return None, None, motif
    if not provisoire.exists():
        return None, None, "aucun fichier produit (rc=%s) : %s" % (rc, texte.strip()[-300:])
    try:
        donnees = json.loads(provisoire.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, None, "rapport illisible (%s)" % type(e).__name__
    deps = donnees.get("dependencies") if isinstance(donnees, dict) else donnees
    if not deps:
        return None, None, "0 paquet audite -- instrument aveugle, pas un env sain"
    return donnees, deps, None


def _auditer_env(env: dict, jour: str) -> dict:
    """Un env : rapport `audit_envs_<nom>_<jour>.json` SEULEMENT si la mesure a eu lieu."""
    nom = re.sub(r"[^A-Za-z0-9_.-]+", "_",
                 ("uv-" if env.get("type") == "uv_tool" else "") + env["nom"])
    cible = SANDBOX / ("audit_envs_%s_%s.json" % (nom, jour))
    provisoire = cible.with_suffix(".partiel")
    rc, texte = _sortie(provisoire, env["site"])
    donnees, deps, raison = _lire_mesure(provisoire, rc, texte)
    if raison:
        provisoire.unlink(missing_ok=True)
        return dict(env, etat="NON_MESURE", pourquoi=raison)
    meta = enveloppe_meta(deps)
    # `interpreteur` y decrirait l'AUDITEUR : ce rapport est la propriete de l'env lu.
    meta["interpreteur_auditeur"] = meta.pop("interpreteur")
    meta.update(environnement=env.get("prefix"), site_packages=env["site"],
                type=env.get("type"), portee="SITE_PACKAGES_DE_CET_ENVIRONNEMENT")
    if isinstance(donnees, dict):
        donnees["_nokido_meta"] = meta
        try:
            provisoire.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            print("[audit-envs] %s : enveloppe NON ecrite (%s)" % (nom, type(e).__name__))
    provisoire.replace(cible)
    touches = [{"nom": d.get("name"), "version": d.get("version"),
                "avis": [v.get("id") for v in d.get("vulns") or []]}
               for d in deps if isinstance(d, dict) and d.get("vulns")]
    return dict(env, etat="MESURE", rapport=str(cible), n_paquets=meta["n_paquets_audites"],
                n_avis=meta["n_avis"], touches=touches)


def _publier_signal(fait: dict, jour: str) -> None:
    """Le signal au tableau noir : INTENT + POINTER, le detail reste dans la synthese.
    Un echec de publication se DIT ; il ne fait pas echouer la mesure."""
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))
        from forge_swarm_blackboard import apply_fact_sync
        r = apply_fact_sync("discovered_facts", json.dumps(fait, ensure_ascii=False),
                            key="audit_envs_%s" % jour, category="supply_chain",
                            trust=0.9, source="forge_pip_audit_mesure", ring=2)
    except Exception as e:  # noqa: BLE001 -- dit ci-dessous, jamais avale
        print("[audit-envs] signal NON publie au tableau noir : %s: %s" % (type(e).__name__, e))
        return
    if isinstance(r, dict) and (r.get("ok") or r.get("planifie")):
        print("[audit-envs] signal publie : discovered_facts/audit_envs_%s" % jour)
    else:
        print("[audit-envs] signal NON publie au tableau noir : %r" % (r,))


def tous_les_envs(jour: str, uv_tools=None) -> int:
    """Audite chaque env du poste. rc 0 = TOUT vu et mesure ; rc 3 = mesure PARTIELLE,
    chaque trou nomme dans la synthese (un env non vu n'est jamais compte sain)."""
    inv = envs_a_auditer(uv_tools)
    print("[audit-envs] %d env(s) a mesurer, %d non vu(s), %d couvert(s) par le rapport "
          "principal" % (len(inv["cibles"]), len(inv["non_vus"]), len(inv["couverts"])),
          flush=True)
    mesures = []
    for env in inv["cibles"]:
        r = _auditer_env(env, jour)
        mesures.append(r)
        if r["etat"] == "MESURE":
            print("[audit-envs] %-24s %4d paquet(s), %d avis%s" % (
                r["nom"], r["n_paquets"], r["n_avis"],
                (" : " + ", ".join("%s %s" % (t["nom"], t["version"]) for t in r["touches"]))
                if r["touches"] else ""), flush=True)
        else:
            print("[audit-envs] %-24s NON MESURE : %s" % (r["nom"], r["pourquoi"]), flush=True)
    for nv in inv["non_vus"]:
        print("[audit-envs] %-24s NON VU : %s %s" % (
            nv["nom"], nv["etat"], nv.get("pourquoi") or nv.get("site") or ""), flush=True)
    synthese = {"date": jour, "interpreteur_auditeur": sys.executable, "mesures": mesures,
                "non_vus": inv["non_vus"], "couverts": inv["couverts"]}
    chemin = SANDBOX / ("audit_envs_synthese_%s.json" % jour)
    provisoire = chemin.with_suffix(".partiel")
    provisoire.write_text(json.dumps(synthese, ensure_ascii=False, indent=1), encoding="utf-8")
    provisoire.replace(chemin)
    print("[audit-envs] synthese : %s" % chemin, flush=True)
    try:
        pointeur = chemin.relative_to(ROOT).as_posix()
    except ValueError:
        pointeur = str(chemin)
    trous = ([m["nom"] for m in mesures if m["etat"] != "MESURE"]
             + [n["nom"] for n in inv["non_vus"]])
    _publier_signal({"intent": "FACT_PROPOSED", "pointer_ref": "file:" + pointeur,
                     "envs_mesures": sum(1 for m in mesures if m["etat"] == "MESURE"),
                     "envs_touches": {m["nom"]: m["n_avis"] for m in mesures if m.get("n_avis")},
                     "non_vus": trous}, jour)
    return 3 if trous else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sortie", default=None,
                    help="chemin du rapport (defaut : sandbox/pip_audit_<date>.json)")
    ap.add_argument("--tous-les-envs", action="store_true",
                    help="apres la mesure de cet interpreteur, auditer chaque env conda et "
                         "uv tool du poste (sandbox/audit_envs_<env>_<date>.json + synthese) ; "
                         "rc 3 = mesure partielle, chaque trou nomme dans la synthese")
    ap.add_argument("--uv-tools", default=None,
                    help="dossier des envs uv tool de l'owner (defaut : UV_TOOL_DIR, sinon "
                         "deduit du profil qui porte la racine conda)")
    a = ap.parse_args(argv)

    try:
        CACHE.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print("[audit] cache non creable (%s) : pip-audit le dira lui-meme"
              % type(e).__name__)

    jour = _dt.date.today().isoformat()
    cible = Path(a.sortie) if a.sortie else SANDBOX / ("pip_audit_%s.json" % jour)
    # pip-audit tourne avec cwd=ROOT : un chemin relatif DOIT se resoudre contre le depot, sinon
    # `provisoire.exists()` le cherche dans le cwd de l'appelant (le circadien), rend « aucun
    # fichier » sur une mesure reussie et laisse un .partiel parasite (mesure du 2026-09-26).
    if not cible.is_absolute():
        cible = ROOT / cible
    # On ecrit d'abord a cote, et on ne PUBLIE le nom definitif qu'apres avoir
    # verifie que la mesure a eu lieu : un rapport partiel portant le nom attendu
    # serait lu comme une mesure valide par tout consommateur.
    provisoire = cible.with_suffix(".partiel")

    rc, texte = _sortie(provisoire)
    motif = next((m for m in MOTIFS_NON_MESURE if m in texte), None)

    if motif:
        print("[audit] NON MESURE : %s" % motif)
        print("        aucun rapport ecrit -- un fichier frais et vide se relirait "
              "comme « aucune vulnerabilite »")
        print("        ce compte a-t-il l'egress ? relancer en `run_job online=true`")
        provisoire.unlink(missing_ok=True)
        return 2

    if not provisoire.exists():
        print("[audit] NON MESURE : pip-audit n'a produit aucun fichier (rc=%s)" % rc)
        print("        derniere sortie : %s" % texte.strip()[-300:])
        return 2

    try:
        donnees = json.loads(provisoire.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("[audit] NON MESURE : rapport illisible (%s)" % type(e).__name__)
        provisoire.unlink(missing_ok=True)
        return 2

    deps = donnees.get("dependencies") if isinstance(donnees, dict) else donnees
    n_paquets = len(deps or [])
    if n_paquets == 0:
        # Zero paquet n'est pas « rien a signaler » : c'est un audit qui n'a rien lu.
        print("[audit] NON MESURE : 0 paquet audite -- ce n'est pas un depot sain, "
              "c'est un instrument aveugle")
        provisoire.unlink(missing_ok=True)
        return 2

    n_vulns = sum(len(d.get("vulns") or []) for d in deps if isinstance(d, dict))

    # L'enveloppe voyage AVEC les donnees : un rapport separe de sa portee se
    # retrouve tot ou tard lu sans elle. La cle est prefixee pour ne pas entrer
    # en collision avec le schema de pip-audit, et les consommateurs existants
    # lisent `dependencies` : ils ne voient pas la difference.
    meta = enveloppe_meta(deps)
    if isinstance(donnees, dict):
        donnees["_nokido_meta"] = meta
        try:
            provisoire.write_text(
                json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            print("[audit] enveloppe NON ecrite (%s) — le rapport reste "
                  "anonyme, sa portee devra etre deduite" % type(e).__name__)

    provisoire.replace(cible)
    print("[audit] MESURE : %d paquet(s) audite(s), %d vulnerabilite(s)"
          % (n_paquets, n_vulns))
    print("        interpreteur : %s" % meta["interpreteur"])
    print("        ⚠ cette mesure decrit CET environnement et aucun autre ; "
          "le hub peut tourner sous un interpreteur different")
    print("        rapport : %s" % cible)
    if a.tous_les_envs:
        # Seulement apres une mesure principale REUSSIE : meme compte, meme reseau --
        # un defaut d'egress ici aurait echoue pareil sur chaque env.
        return tous_les_envs(jour, a.uv_tools)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
