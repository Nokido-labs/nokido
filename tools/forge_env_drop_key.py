#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Retire UNE cle de Nokido.env — et seulement si le coffre la detient deja.

`forge_vault_migrate --finalize` retire TOUTES les lignes secrets d'un coup et
laisse une sauvegarde en clair (qu'il faut ensuite purger). Quand on ne veut
sortir qu'une seule cle du clair — un PAT renouvele, par exemple — ce marteau
est trop large : il touche des lignes que personne n'a demande a bouger.

GARDE, non contournable : la ligne n'est retiree que si le coffre rend la MEME
valeur, comparee par empreinte. Sans cette confrontation, on supprimerait la
derniere copie d'un secret sur la foi d'un `ok:true` — la faute exacte que la
doctrine « verifier par le CONTENU » interdit. La cle du coffre peut porter un
AUTRE nom que celle du .env (`--vault-key`) : un secret colle sous un nom
approximatif reste le cas le plus frequent.

Aucune sauvegarde en clair n'est ecrite : la valeur vit au coffre, verifiee
juste avant. Un backup plaintext serait une copie de plus a purger.

Usage :
    run action=trusted_script path=tools/forge_env_drop_key.py
        script_args="GITHUB_TOKEN --vault-key GITHUB_MODELS_TOKEN"
        script_args="GITHUB_TOKEN --dry-run"
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _empreinte(valeur: str) -> str:
    """12 hex de sha256 : de quoi confronter deux secrets sans en montrer un."""
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:12] if valeur else ""


def _fichier_env() -> Path:
    for nom in ("Nokido.env", "nokido.env"):
        p = ROOT / nom
        if p.exists():
            return p
    raise SystemExit("ABORT: aucun Nokido.env sous la racine")


def _lignes_de(cle: str, lignes: list[str]) -> list[int]:
    trouvees = []
    for i, ligne in enumerate(lignes):
        s = ligne.strip()
        if s and not s.startswith("#") and "=" in s and s.partition("=")[0].strip() == cle:
            trouvees.append(i)
    return trouvees


def main() -> int:
    ap = argparse.ArgumentParser(description="Retirer une cle du .env, coffre verifie")
    ap.add_argument("cle", help="nom de la cle dans Nokido.env")
    ap.add_argument("--vault-key", default=None,
                    help="nom au coffre s'il differe de celui du .env")
    ap.add_argument("--dry-run", action="store_true", help="verifie sans ecrire")
    a = ap.parse_args()
    cible = a.vault_key or a.cle

    env = _fichier_env()
    lignes = env.read_text(encoding="utf-8", errors="replace").splitlines()
    index = _lignes_de(a.cle, lignes)
    if not index:
        print(f"[env] '{a.cle}' n'est pas une affectation active de {env.name} — rien a faire")
        return 1

    valeurs = {lignes[i].partition("=")[2].strip() for i in index}
    if len(valeurs) > 1:
        print(f"ABORT: '{a.cle}' apparait {len(index)} fois avec des valeurs DIFFERENTES "
              f"(lignes {[i + 1 for i in index]}) — trancher a la main")
        return 3
    valeur = valeurs.pop()

    # ⚠️ PAS `forge_secrets.get_secret` : sa chaine de resolution RETOMBE SUR LE
    # .env. La garde « ne retirer du clair que si le coffre rend la MEME valeur »
    # se validait donc avec la valeur qu'elle s'appretait a supprimer — un outil
    # de suppression de secret qui se donne raison a lui-meme. MESURE
    # 2026-08-18 : `get_secret("LMSTUDIO_MODEL")` rendait 'local-model' AVANT le
    # retrait et None APRES, alors que le coffre n'a jamais porte cette cle. La
    # valeur retiree du clair n'existait nulle part ailleurs : sur un vrai
    # secret, c'etait la perte seche — precisement ce que cet outil existe pour
    # empecher. Meme famille que le secret ecrase le matin meme.
    from nokido_agent.app.forge_machine_vault import vault_get

    au_coffre = vault_get(cible) or ""
    if not au_coffre:
        print(f"ABORT: '{cible}' est ABSENTE du coffre — retirer la ligne "
              f"supprimerait la derniere copie du secret")
        return 3
    if au_coffre != valeur:
        print(f"ABORT: '{cible}' au coffre ({_empreinte(au_coffre)}) DIFFERE de "
              f"{env.name}:{index[0] + 1} ({_empreinte(valeur)}) — migrer d'abord")
        return 3

    marque = (f"# {a.cle} -> coffre DPAPI sous '{cible}' (app/forge_machine_vault), "
              f"retire du clair le {date.today().isoformat()}")
    if a.dry_run:
        print(f"[dry-run] {env.name}:{index[0] + 1} serait remplacee par : {marque}")
        return 0

    for i in index:
        lignes[i] = marque
    env.write_text("\n".join(lignes) + "\n", encoding="utf-8")

    relu = env.read_text(encoding="utf-8", errors="replace")
    # ⚠️ MESURE 2026-08-18 : chercher la VALEUR declarait en ECHEC une ecriture
    # parfaitement reussie. `LMSTUDIO_MODEL` et `LLAMACPP_MODEL` valaient tous
    # deux `local-model` : la ligne visee etait bien retiree, mais la valeur
    # subsistait sur l'AUTRE cle. Un faux echec est couteux — il pousse a
    # rejouer une ecriture deja faite, ou fait douter d'un fichier sain.
    # Ce qui doit disparaitre, c'est l'ASSIGNATION de la cle visee.
    encore = [n for n, ligne in enumerate(relu.splitlines(), 1)
              if ligne.strip().startswith(f"{a.cle}=")]
    if encore:
        print(f"CRITIQUE: '{a.cle}' est TOUJOURS assignee apres ecriture "
              f"(ligne(s) {encore})")
        return 4
    # La valeur ailleurs n'est pas un echec, mais elle se DIT : une valeur
    # partagee entre deux cles se propage souvent d'un copier-coller, et la
    # suivante meritera peut-etre le meme traitement.
    autres = [ligne.split("=", 1)[0].strip()
              for ligne in relu.splitlines()
              if "=" in ligne and not ligne.strip().startswith("#")
              and ligne.split("=", 1)[1].strip() == valeur]
    if autres:
        print(f"[note] la meme valeur reste portee par : {', '.join(autres)}")
    print(f"[env] {env.name}:{index[0] + 1} — '{a.cle}' retiree du clair "
          f"(valeur confirmee au coffre sous '{cible}', empreinte {_empreinte(au_coffre)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
