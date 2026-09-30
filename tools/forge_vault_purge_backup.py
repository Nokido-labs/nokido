#!/usr/bin/env python
"""tools/forge_vault_purge_backup.py — purge le backup PLAINTEXT laissé par --finalize.

__FORGE_COLOR__ = "immunitaire/secrets"

`forge_vault_migrate --finalize` retire les secrets de Nokido.env et laisse une copie
EN CLAIR sous `_backups/secrets/` en disant « SUPPRIMER une fois rassuré ». Ce script
est ce « une fois rassuré » — vérifié, pas ressenti.

POURQUOI UN SCRIPT ET PAS UN `del`
----------------------------------
Le compte sandbox n'a pas le droit d'écrire dans le dépôt hors zone agent : un `del`
y répond `Accès refusé` (mesuré 2026-07-29). Le chemin gouverné est `trusted_script`,
où le privilège vient du code revu — d'où ce fichier, committé.

LE GARDE QUI COMPTE
-------------------
On ne supprime QUE si chaque secret listé dans le backup est effectivement lisible au
coffre. Sinon le backup est la SEULE copie restante d'un secret que `--finalize` vient
de retirer du .env, et l'effacer le perdrait définitivement. Le coût des deux erreurs
n'est pas symétrique : garder un backup de trop se corrige, perdre une clé non.

Aucune valeur n'est jamais affichée — noms et longueurs seulement.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "_backups" / "secrets"

sys.path.insert(0, str(ROOT))


def _noms_du_backup(p: Path) -> list[str]:
    """Noms de clés présents dans le backup. Les valeurs ne sortent jamais d'ici."""
    noms: list[str] = []
    for ligne in p.read_text(encoding="utf-8", errors="replace").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        noms.append(ligne.partition("=")[0].strip())
    return noms


def main() -> int:
    if not BACKUP_DIR.is_dir():
        print(f"[purge] rien a faire : {BACKUP_DIR.relative_to(ROOT)} absent.")
        return 0

    cibles = sorted(BACKUP_DIR.glob("*backup*"))
    if not cibles:
        print("[purge] rien a faire : aucun backup present.")
        return 0

    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        print(f"ECHEC: coffre illisible ({type(e).__name__}) — on NE SUPPRIME RIEN.")
        return 2

    total_supprimes = 0
    for p in cibles:
        noms = _noms_du_backup(p)
        if not noms:
            print(f"[purge] {p.name}: aucune cle lisible — ABSTENTION (fichier inattendu).")
            continue

        manquants: list[str] = []
        for n in noms:
            try:
                val = get_secret(n) or ""
            except Exception:  # noqa: BLE001
                val = ""
            if not val:
                manquants.append(n)

        if manquants:
            print(f"[purge] {p.name}: ABANDON — {len(manquants)} secret(s) PAS au coffre : {manquants}")
            print("        Ce backup est leur derniere copie. Rejouer forge_vault_migrate --migrate.")
            continue

        print(f"[purge] {p.name}: {len(noms)} cle(s), toutes verifiees au coffre.")
        taille = p.stat().st_size
        p.unlink()
        total_supprimes += 1
        print(f"[purge] SUPPRIME {p.name} ({taille} octets de clair).")

    if total_supprimes:
        try:
            BACKUP_DIR.rmdir()  # ne retire le dossier QUE s'il est vide
            print(f"[purge] {BACKUP_DIR.relative_to(ROOT)} vide -> retire.")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
