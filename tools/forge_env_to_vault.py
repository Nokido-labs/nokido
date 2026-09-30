#!/usr/bin/env python3
"""forge_env_to_vault.py — migre les secrets du .env vers le coffre DPAPI, SANS CASSE.

POURQUOI CET OUTIL (et pas `vault set` a la main) — incident 2026-08-18 :
`vault_set` **ECRASE EN SILENCE**. Une migration faite « sous le nom lu dans le
.env » a detruit un PAT deja au coffre. Deux garde-fous ici, non negociables :

  1. **JAMAIS de valeur en argument.** Le hub journalise les args de `run` :
     passer un secret en `script_args` l'ecrit dans un log. Le script lit le
     .env lui-meme.
  2. **REFUS d'ecraser par defaut.** Si la cle existe deja au coffre, on
     COMPARE (par empreinte, jamais en clair) et on n'ecrit que si `--force`
     est donne ET que les valeurs different. Devant deux secrets du meme
     format, on ne tranche pas sur le nom.

Aucune valeur n'est imprimee : ni en clair, ni tronquee. Seulement des
empreintes courtes et des longueurs.

Usage :
    run trusted_script path=tools/forge_env_to_vault.py script_args="--plan"
    run trusted_script path=tools/forge_env_to_vault.py script_args="--appliquer --cles CLOUDFLARE_ACCOUNT_ID"
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENV_DEFAUT = ROOT / "Nokido.env"

# CLES QUI DOIVENT RESTER DANS LE FICHIER, quelle que soit leur empreinte.
# Le coffre ne PEUPLE PAS l'environnement : une cle lue par `os.environ.get(...)` brut
# n'a aucun repli si sa ligne est videe. Mesure du 2026-09-06 : PRIVATE_KEY_PATH est lu
# ainsi dans `brain_worker` (L1192) et `forge_mesh_memory` (L302), et le repli de
# brain_worker relit le fichier avec `startswith("PRIVATE_KEY_PATH=")`, que le `#` de
# neutralisation casse aussi. Vider cette ligne coupe la synchronisation SSH au
# prochain demarrage.
# Cette liste existe parce que --restaurer seul ne suffit pas : la cle restauree a
# desormais la MEME empreinte que le coffre, donc le passage suivant de --neutraliser
# la reprend. Le savoir doit vivre ICI, pas dans la memoire de celui qui lance l'outil.
# AVANT D'AJOUTER UNE ENTREE : verifier par lecture du code que la cle est bien lue
# hors coffre, et citer le fichier et la ligne.
# LEVEE le 2026-09-25 pour PRIVATE_KEY_PATH (et les autres acces SSH) : brain_worker et
# forge_mesh_memory lisent desormais par forge_secrets.get_secret (coffre d'abord), et le cliquet
# tests/nr/test_acces_ssh_au_coffre_nr.py::test_aucun_lecteur_brut_des_acces_ssh_hors_du_coffre
# REFUSE tout nouveau `os.environ.get("SSH_*"/"PRIVATE_KEY_PATH")` brut dans app/. Le repli de
# brain_worker qui relit un fichier ne vise que `app/Nokido.env`, pas `Nokido/Nokido.env`.
JAMAIS_NEUTRALISER: set = set()


def _emp(v: str) -> str:
    """Empreinte courte — permet de COMPARER sans jamais exposer."""
    return hashlib.sha256((v or "").encode("utf-8")).hexdigest()[:12]


def _valeur_reelle(reste: str) -> str:
    """La valeur s'arrete au premier commentaire de FIN DE LIGNE.

    Sans cette coupe, la marque laissee par `--neutraliser` (`# CLE=   # valeur retiree
    le ...`) est relue comme une VALEUR. Paye le 2026-09-06 : une sonde de verification a
    compte 41 lignes « portant encore un secret » la ou il y en avait 30 -- elle lisait le
    marqueur que l'outil venait d'ecrire. 7e occurrence du motif « un instrument lit son
    propre vocabulaire ».
    """
    return reste.split(" #", 1)[0].strip().strip('"').strip("'")


def lire_env(chemin: Path, inclure_commentees: bool = False) -> dict:
    """Lit le fichier d'environnement.

    `inclure_commentees` : une cle DESACTIVEE mais portant encore sa valeur est encore
    PRESENTE dans le fichier -- donc encore exposee. Mesure du 2026-09-06 : 30 lignes dans
    ce cas, dont une cle de 110 caracteres et un jeton de 35, ABSENTS du coffre. Sans ce
    drapeau la migration ne les voyait pas, donc ne pouvait pas les mettre a l'abri.
    """
    out: dict[str, str] = {}
    for ligne in chemin.read_text(encoding="utf-8", errors="ignore").splitlines():
        ligne = ligne.strip()
        if not ligne or "=" not in ligne:
            continue
        if ligne.startswith("#"):
            if not inclure_commentees:
                continue
            ligne = ligne.lstrip("#").strip()
            if "=" not in ligne:
                continue
        k, v = ligne.split("=", 1)
        k, v = k.strip(), _valeur_reelle(v)
        if not v:
            continue
        if not k.replace("_", "").isalnum():
            continue
        if k in out and out[k] != v:
            # Doublon DIVERGENT : mesure 2026-08-20, CLOUDFLARE_ACCOUNT_ID
            # figurait deux fois. La derniere ligne gagne, en silence.
            print("[!] %s est DUPLIQUE avec des valeurs DIFFERENTES "
                  "(emp %s vs %s) — la derniere lue l'emporte"
                  % (k, _emp(out[k]), _emp(v)), flush=True)
        out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Migre des secrets .env -> coffre DPAPI")
    ap.add_argument("--env", default=str(ENV_DEFAUT))
    ap.add_argument("--cles", default=None,
                    help="liste de cles separees par des virgules (defaut : toutes celles qui ressemblent a un secret)")
    ap.add_argument("--appliquer", action="store_true", help="sans ce drapeau : PLAN seulement")
    ap.add_argument("--force", action="store_true",
                    help="autorise l'ECRASEMENT d'une cle deja au coffre (a n'utiliser qu'en connaissance de cause)")
    ap.add_argument("--inclure-commentees", action="store_true", dest="inclure_commentees",
                    help="voit aussi les lignes DESACTIVEES qui portent encore leur valeur : "
                         "une cle commentee avec sa valeur est encore exposee")
    ap.add_argument("--restaurer", default=None,
                    help="RETABLIT dans le .env, depuis le coffre, les cles nommees "
                         "(separees par des virgules). Pour une cle lue par os.environ "
                         "BRUT : la vider casse son consommateur au prochain demarrage.")
    ap.add_argument("--neutraliser", action="store_true",
                    help="RETIRE du .env la valeur des cles dont l'empreinte est DEJA celle "
                         "du coffre (ligne active -> commentee et videe ; ligne deja "
                         "commentee mais portant encore sa valeur -> videe). "
                         "Sans --appliquer : plan seulement.")
    a = ap.parse_args()

    from nokido_agent.app.forge_machine_vault import vault_get, vault_set  # noqa: E402

    env = lire_env(Path(a.env), inclure_commentees=a.inclure_commentees)
    if a.cles:
        vises = [k.strip() for k in a.cles.split(",") if k.strip()]
    else:
        # Heuristique PRUDENTE : on ne migre pas la config, seulement ce qui
        # ressemble a un secret. Mieux vaut en oublier que d'en deplacer un
        # qui n'en est pas.
        motifs = ("KEY", "TOKEN", "SECRET", "PASSWORD", "ACCOUNT_ID", "ACCESS")
        vises = [k for k in env if any(m in k.upper() for m in motifs)]

    plan = []
    for k in sorted(vises):
        if k not in env:
            plan.append((k, "ABSENT du .env", None))
            continue
        nouvelle = env[k]
        try:
            ancienne = vault_get(k)
        except Exception:  # noqa: BLE001
            ancienne = None
        if not ancienne:
            plan.append((k, "NOUVEAU au coffre", nouvelle))
        elif _emp(ancienne) == _emp(nouvelle):
            plan.append((k, "IDENTIQUE (rien a faire)", None))
        else:
            plan.append((k, "CONFLIT : coffre=%s / env=%s" % (_emp(ancienne), _emp(nouvelle)),
                         nouvelle if a.force else None))

    ecrits = 0
    for k, etat, valeur in plan:
        marque = "->ECRIT" if (valeur is not None and a.appliquer) else ""
        print("  %-34s %-42s %s" % (k, etat, marque), flush=True)
        if valeur is not None and a.appliquer:
            vault_set(k, valeur)
            ecrits += 1

    print("\n%d cle(s) examinee(s), %d ecrite(s)%s"
          % (len(plan), ecrits, "" if a.appliquer else "  [PLAN — rien n'a ete ecrit]"),
          flush=True)
    if a.restaurer:
        _restaurer(Path(a.env), vault_get,
                   [k.strip() for k in a.restaurer.split(",") if k.strip()],
                   appliquer=a.appliquer)

    if a.neutraliser:
        _neutraliser(Path(a.env), vault_get, appliquer=a.appliquer,
                     limiter_a=set(vises) if a.cles else None)

    conflits = [k for k, e, _v in plan if e.startswith("CONFLIT")]
    if conflits and not a.force:
        print("CONFLITS NON RESOLUS (le coffre a deja une valeur DIFFERENTE) : %s\n"
              "  -> verifier LEQUEL est le bon AVANT d'utiliser --force. "
              "Un ecrasement est irreversible." % ", ".join(conflits), flush=True)
    return 0


def _restaurer(chemin: Path, vault_get, cles: list, appliquer: bool) -> int:
    """Retablit dans le .env, depuis le coffre, une cle qu'on n'aurait pas du vider.

    POURQUOI CETTE FONCTION EXISTE. `--neutraliser` s'appuie sur une heuristique de NOM
    (KEY, TOKEN, SECRET...) pour decider ce qui est un secret. Le 2026-09-06 elle a retenu
    `PRIVATE_KEY_PATH` -- qui n'est pas une cle mais un CHEMIN, et surtout qui est lu par
    `os.environ.get("PRIVATE_KEY_PATH", "")` BRUT dans `brain_worker` et
    `forge_mesh_memory`, sans passer par le coffre. Le repli de `brain_worker` relit meme
    le fichier avec `startswith("PRIVATE_KEY_PATH=")`, que le `#` de neutralisation casse.
    Vider cette ligne aurait donc coupe la synchronisation SSH au prochain demarrage.

    LA LECON, generale : avant de retirer une valeur d'un `.env`, verifier COMMENT elle est
    lue. Une cle resolue par `get_secret` est couverte par le coffre ; une cle lue par
    `os.environ` ne l'est pas -- le coffre ne peuple pas l'environnement.
    """
    import re as _re

    lignes = chemin.read_text(encoding="utf-8", errors="ignore").splitlines()
    motif_par_cle = {k: _re.compile(r"^(\s*)#\s*(%s)\s*=" % _re.escape(k)) for k in cles}
    sortie, remis, introuvables = [], [], []
    for k in cles:
        if not vault_get(k):
            introuvables.append(k)
    for ligne in lignes:
        pose = False
        for k, mot in motif_par_cle.items():
            if k in introuvables or k in remis:
                continue
            m = mot.match(ligne)
            if m:
                sortie.append("%s%s=%s" % (m.group(1), k, vault_get(k)))
                remis.append(k)
                pose = True
                break
        if not pose:
            sortie.append(ligne)

    print("\n-- RESTAURATION --")
    print("  a retablir depuis le coffre : %s" % (", ".join(remis) or "-"))
    if introuvables:
        print("  INTROUVABLES au coffre (rien a retablir) : %s" % ", ".join(introuvables))
    if not appliquer:
        print("  [PLAN — le fichier n'a PAS ete modifie]")
        return 0
    if not remis:
        print("  rien a faire")
        return 0
    import os as _os

    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text("\n".join(sortie) + "\n", encoding="utf-8")
    _os.replace(tmp, chemin)
    relu = chemin.read_text(encoding="utf-8", errors="ignore").splitlines()
    print("  ECRIT : %d ligne(s) retablie(s) ; fichier relu : %d lignes (avant %d)"
          % (len(remis), len(relu), len(lignes)))
    return len(remis)


def _neutraliser(chemin: Path, vault_get, appliquer: bool, limiter_a=None) -> int:
    """Retire du .env la valeur des cles DEJA au coffre avec la MEME empreinte.

    POURQUOI. Ecrire au coffre ne reduit AUCUNE surface tant que la valeur reste en clair
    dans le fichier. Mesure du 2026-09-06 : sur 63 lignes commentees, 31 portaient encore
    leur valeur -- dont un jeton de 37 caracteres et une cle de 110. Commenter avait
    DESACTIVE la ligne, pas retire le secret.

    LA GARDE EST L'EMPREINTE, et elle seule. On ne vide une ligne que si le hache de sa
    valeur est EXACTEMENT celui du coffre pour la meme cle. Consequences voulues :
      - une cle absente du coffre n'est jamais touchee (on ne detruit pas la seule copie) ;
      - une cle dont le coffre a une valeur DIFFERENTE n'est jamais touchee (on ne sait pas
        laquelle est la bonne -- c'est un CONFLIT, il se tranche a la main) ;
      - un commentaire narratif contenant un `=` ne correspondra jamais a une empreinte,
        donc le faux positif de lecture est structurellement impossible.

    Le nom de la cle est CONSERVE, commente et date : un fichier ou la ligne disparait
    laisse le lecteur suivant sans indice sur ou la valeur est passee.
    """
    import datetime
    import os
    import re as _re

    marque = datetime.date.today().isoformat()
    lignes = chemin.read_text(encoding="utf-8", errors="ignore").splitlines()
    sortie, vides, gardees, exceptions, hors_perimetre = [], [], [], [], []
    motif = _re.compile(r"^(\s*)(#\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
    for ligne in lignes:
        m = motif.match(ligne)
        if not m:
            sortie.append(ligne)
            continue
        indent, deja_commentee, cle, reste = m.groups()
        # `_valeur_reelle` coupe au commentaire de fin de ligne : sans cela, la marque
        # posee par un passage PRECEDENT (`# CLE=   # valeur retiree le ...`) serait relue
        # comme une valeur -- l'instrument lirait son propre vocabulaire.
        valeur = _valeur_reelle(reste)
        if not valeur:
            sortie.append(ligne)
            continue
        try:
            coffre = vault_get(cle)
        except Exception:  # noqa: BLE001
            coffre = None
        if cle in JAMAIS_NEUTRALISER:
            exceptions.append(cle)
            sortie.append(ligne)
            continue
        # PERIMETRE (2026-09-25) : avec --cles, seules ces cles sont touchees. Sans lui, un
        # « migre mes acces SSH » aurait vide 5 autres secrets, possiblement lus en brut.
        if limiter_a is not None and cle not in limiter_a:
            hors_perimetre.append(cle)
            sortie.append(ligne)
            continue
        if not coffre or _emp(coffre) != _emp(valeur):
            if deja_commentee is None:
                gardees.append(cle)
            sortie.append(ligne)
            continue
        sortie.append("%s# %s=   # valeur retiree le %s -- lire au coffre DPAPI"
                      % (indent, cle, marque))
        vides.append(cle)

    print("\n-- NEUTRALISATION --")
    print("  a vider (empreinte identique au coffre) : %d  %s"
          % (len(vides), ", ".join(sorted(set(vides))) or "-"))
    print("  laissees en clair (absentes du coffre ou divergentes) : %d  %s"
          % (len(set(gardees)), ", ".join(sorted(set(gardees))[:12]) or "-"))
    if exceptions:
        print("  EXEMPTEES (lues hors coffre, doivent rester dans le fichier) : %s"
              % ", ".join(sorted(set(exceptions))))
    if limiter_a is not None:
        print("  HORS PERIMETRE --cles (non touchees) : %d" % len(set(hors_perimetre)))
    if not appliquer:
        print("  [PLAN — le fichier n'a PAS ete modifie]")
        return 0
    if not vides:
        print("  rien a faire")
        return 0
    # Ecriture ATOMIQUE : un .env tronque en plein vol coute plus cher que le gain.
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text("\n".join(sortie) + "\n", encoding="utf-8")
    os.replace(tmp, chemin)
    relu = chemin.read_text(encoding="utf-8", errors="ignore").splitlines()
    print("  ECRIT : %d ligne(s) videe(s) ; fichier relu : %d lignes (avant %d)"
          % (len(vides), len(relu), len(lignes)))
    return len(vides)


if __name__ == "__main__":
    sys.exit(main())
