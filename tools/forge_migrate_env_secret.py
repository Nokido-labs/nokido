#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Migre un secret de Nokido.env vers le vault DPAPI sous un nom PROPRE, puis RETIRE la ligne en clair.

Cas d'usage : une clé collée avec un nom malformé (espaces/URL) dans .env ->
la relire et la stocker sous un nom canonique au vault. La VALEUR ne sort JAMAIS
(ni stdout ni contexte) : on n'imprime que la longueur + un bool de cohérence.

RETRAIT DU CLAIR (owner 15/10 : « tu dois le faire toi systematiquement si present au coffre ») : une fois
le secret RELU identique au coffre, la ligne en clair de Nokido.env est remplacee par un commentaire SANS
valeur (nom, cible, date) -- jamais supprimee sans trace, jamais copiee ailleurs. Relecture non conforme :
rien n'est retire, et c'est dit (rc 3).

Usage: trusted_script path=tools/forge_migrate_env_secret.py
       script_args="'<nom source dans .env>' <NOM_CIBLE_VAULT> [--commentee]"
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def lire_source(env: Path, src: str, commentee_ok: bool = False) -> tuple:
    """(valeur, provenance) de la ligne `src=...` ; (None, "") si absente.

    LIGNE COMMENTEE : jamais par defaut. Dans ce fichier, un `#` devant une clef signifie le plus souvent
    « perimee, remplacee, ou migree ailleurs » -- la lire sans le vouloir ressusciterait un secret mort et
    ferait diagnostiquer un `401` pendant des heures. Le drapeau rend l'intention EXPLICITE."""
    for num, line in enumerate(env.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        est_commentee = s.startswith("#")
        if est_commentee:
            if not commentee_ok:
                continue
            s = s.lstrip("#").strip()
        if "=" not in s:
            continue
        name, _, v = s.partition("=")
        if name.strip() == src and v.strip():
            return v.strip(), f"ligne {num}" + (" (COMMENTEE -- lue sur demande explicite)"
                                                if est_commentee else "")
    return None, ""


def retirer_du_clair(env: Path, src: str, val: str, tgt: str, commentee_ok: bool = False) -> int:
    """Remplace par un commentaire SANS valeur chaque ligne `src=<val>` ; rend le nombre de lignes retirees.

    Au niveau des OCTETS : seule la ligne visee change ; une autre ligne a l'encodage atypique n'est jamais
    re-encodee (un `errors="replace"` sur tout le fichier aurait pu abimer d'autres secrets). Une ligne dont la
    valeur DIFFERE de celle migree n'est pas touchee (ce n'est pas le secret qu'on a relu au coffre)."""
    initial = env.read_bytes()
    lignes = initial.splitlines(keepends=True)
    retirees = 0
    for i, brut in enumerate(lignes):
        try:
            line = brut.decode("utf-8")
        except UnicodeDecodeError:  # muet-ok : une ligne non UTF-8 n'est pas la ligne relue au coffre -- intacte
            continue
        s = line.strip()
        if s.startswith("#") and not commentee_ok:
            continue
        corps = s.lstrip("#").strip()
        if "=" in corps and corps.partition("=")[0].strip() == src and corps.partition("=")[2].strip() == val:
            fin = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
            lignes[i] = ("# %s -> migre au coffre %s le %s (valeur retiree du clair)%s" % (
                src, tgt, time.strftime("%Y-%m-%d"), fin)).encode("utf-8")
            retirees += 1
    if retirees:
        _ecrire(env, initial, b"".join(lignes))
    return retirees


def _ecrire(env: Path, initial: bytes, nouveau: bytes) -> None:
    """Ecriture atomique (fichier voisin + `os.replace`) ; a defaut, EN PLACE puis relecture.

    Mesure du 15/10 : `LaForgeTrusted` n'a pas le droit de CREER un fichier a la racine du depot
    (`PermissionError` sur `Nokido.env.tmp`). Repli : reecriture en place, relue ; non conforme -> le contenu
    d'origine est remis et l'echec est leve. Aucune copie de sauvegarde : elle porterait les secrets en clair
    ailleurs. Un voisin temporaire qui n'a pas pu remplacer la cible est supprime (il les porte aussi)."""
    tmp = env.with_suffix(".env.tmp")
    try:
        tmp.write_bytes(nouveau)
        os.replace(tmp, env)
        return
    except OSError:
        try:
            tmp.unlink()
        except FileNotFoundError:  # muet-ok : jamais cree, rien a effacer
            pass
    with open(env, "r+b") as f:
        f.write(nouveau)
        f.truncate()
    if env.read_bytes() != nouveau:
        with open(env, "r+b") as f:
            f.write(initial)
            f.truncate()
        raise OSError("reecriture en place non conforme -- contenu d'origine remis, rien n'est retire")
    print("[env] ecriture atomique refusee (droit de creation) -- reecrit EN PLACE puis relu conforme")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: forge_migrate_env_secret.py '<source_name>' <TARGET_NAME> [--commentee]")
        return 2
    src, tgt = argv[0], argv[1]
    commentee_ok = "--commentee" in argv[2:]
    env = ROOT / "Nokido.env"
    val, provenance = lire_source(env, src, commentee_ok)
    if not val:
        print(f"source '{src}' introuvable dans Nokido.env"
              + ("" if commentee_ok else " (lignes commentees ignorees : ajouter --commentee)"))
        return 1
    print(f"[source] {src} <- {provenance}, longueur {len(val)} (valeur jamais affichee)")

    from nokido_agent.app.forge_secrets import get_secret, set_secret

    set_secret(tgt, val)
    chk = get_secret(tgt) or ""
    print(f"[vault] {tgt} stocke (len={len(chk)} match={chk == val}) -- valeur jamais affichee")
    if chk != val:
        print("[env] ligne en clair CONSERVEE : la relecture du coffre ne correspond pas -- a instruire")
        return 3
    n = retirer_du_clair(env, src, val, tgt, commentee_ok)
    print(f"[env] {n} ligne(s) en clair retiree(s) de Nokido.env (remplacee(s) par un commentaire sans valeur)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
