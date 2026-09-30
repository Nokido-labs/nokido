#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_coffre_rotation.py -- ROTATION des secrets exposes du coffre (etape 3, go owner 2026-09-28).

Ces valeurs ont ete lisibles par les comptes bac a sable (coffre machine DPAPI, registre
NSSM) : seule une rotation ferme la faille pour les valeurs deja lues. Sous SYSTEM
(profil ps_clm), dans la fenetre de maintenance owner :

- chaque nom recoit une valeur NEUVE, au format que ses consommateurs attendent ;
- nom encore en TRANSITION (lecteurs hors SYSTEM sans voie propre) : coffre reserve ET
  coffre machine (`vault_set`, qui met la copie reservee a jour d'abord) ;
- nom FERME : coffre reserve seulement, et la copie du coffre machine RETIREE -- c'est le
  retrait des copies de l'etape 2b-6 ;
- chaque ecriture est RELUE au coffre reserve ; aucune valeur n'est jamais affichee ; le
  journal ne porte que des noms.

Tout nom reserve a une decision : tourne ici (GENERATEURS), ou exclu avec son motif
(HORS_ROTATION). Apres la rotation : relancer la pile, resynchroniser les clients, puis
`tools/forge_secret_rotation_check.py` (les anciennes valeurs ne servent plus).

Usage : forge_coffre_rotation.py [--appliquer]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__FORGE_COLOR__ = "immunitaire/coffre-rotation : nouvelles valeurs des secrets exposes, sous SYSTEM"

GENERATEURS = {
    "FORGE_MCP_TOKEN": lambda: secrets.token_hex(32),
    "LAFORGE_SUPERVISOR_TOKEN": lambda: secrets.token_hex(32),
    "LAFORGE_ADMIN_TOKEN": lambda: secrets.token_hex(32),
    "LAFORGE_JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "MCP_DEV_SECRET": lambda: secrets.token_urlsafe(48),
    "HUB_JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "LAFORGE_PRIV_BRIDGE_HMAC": lambda: secrets.token_hex(32),
    # Le pare-feu decode la valeur en base64 et attend 32 octets (`_log_hmac_key`).
    "firewall_log_hmac": lambda: base64.b64encode(os.urandom(32)).decode("ascii"),
    # Inutilise tant que SQLCipher est absent (chiffrement au repos = volume VeraCrypt).
    "LAFORGE_DB_KEY": lambda: secrets.token_urlsafe(48),
}
HORS_ROTATION = {
    "FORGE_ENCRYPT_KEY": "des donnees chiffrees avec elle doivent etre re-chiffrees d'abord "
                         "(migration dediee)",
    "LAFORGE_JWT_ED25519_PRIVE": "nee le 2026-09-28 au coffre reserve, jamais exposee",
    "FORGE_PERSONA_HMAC_KEY": "forge_coffre_reserve_provision --appliquer --rotation-persona",
    "LAFORGE_VC_KEYFILE_B64": "forge_at_rest_veracrypt --rekey-preparer/verifier/finaliser",
}
JOURNAL = ROOT / "sandbox" / "rotation_coffre.jsonl"


def _journaliser(noms: list) -> None:
    try:
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "noms_tournes": noms}) + "\n")
    except OSError:
        pass


def _destination(nom: str, transition: frozenset) -> str:
    return ("coffre reserve + coffre machine (transition)" if nom in transition
            else "coffre reserve ; copie du coffre machine RETIREE")


def main(argv=None) -> int:
    from nokido_agent.app import forge_machine_vault as mv
    from nokido_agent.app import forge_secrets as fs

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--appliquer", action="store_true", help="ecrire (defaut : plan seulement)")
    a = ap.parse_args(argv)

    sid = mv._sid_courant()
    if sid != mv.RESERVE_COMPTE_SID:
        print(f"REFUS : compte {sid or 'ILLISIBLE'} -- la rotation se fait sous SYSTEM (ps_clm)")
        return 2
    sans_decision = fs.NOMS_RESERVES - set(GENERATEURS) - set(HORS_ROTATION)
    if sans_decision:
        print(f"REFUS : noms reserves sans decision de rotation : {sorted(sans_decision)}")
        return 2
    transition = fs.RESERVES_EN_TRANSITION
    print("rotation du coffre -- " + ("APPLICATION" if a.appliquer else "PLAN seulement"))
    for nom in GENERATEURS:
        print(f"  {nom:<26} -> {_destination(nom, transition)}")
    for nom, motif in HORS_ROTATION.items():
        print(f"  {nom:<26} HORS : {motif}")
    if not a.appliquer:
        print("rien n'est ecrit. Relancer avec --appliquer.")
        return 0

    echecs, tournes = [], []
    for nom, generer in GENERATEURS.items():
        valeur = generer()
        if nom in transition:
            ecrit = mv.vault_set(nom, valeur)
        else:
            ecrit = mv.reserve_set(nom, valeur)
            if ecrit:
                mv.vault_delete(nom)
        relu, _etat = mv.reserve_lire(nom)
        if ecrit and relu == valeur:
            tournes.append(nom)
            print(f"  {nom:<26} TOURNE et relu")
        else:
            echecs.append(nom)
            print(f"  {nom:<26} ECHEC (ecriture {'faite' if ecrit else 'refusee'}, relecture differente)")
        valeur = None
    _journaliser(tournes)
    print(f"bilan : {len(tournes)}/{len(GENERATEURS)} tournes" + (f" ; ECHECS {echecs}" if echecs else ""))
    print("suite : relancer la pile ; resynchroniser les clients (forge_mcp_json_sync, Claude Desktop) ;"
          " puis tools/forge_secret_rotation_check.py.")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())
