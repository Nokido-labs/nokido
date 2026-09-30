"""forge_env_alias.py — shim de renommage progressif LAFORGE_* -> NOKIDO_* (dual-read).

Phase 3a du rebrand Nokido (reversible, zero casse). Au boot, miroir bidirectionnel
des variables d'environnement :
  - pour chaque NOKIDO_<X> defini, cree LAFORGE_<X> s'il manque (les ~90 sites qui
    lisent os.environ["LAFORGE_*"] continuent de marcher) ;
  - pour chaque LAFORGE_<X> defini, expose NOKIDO_<X> (le nouveau code/config peut
    utiliser le nom moderne).
Le premier defini gagne (jamais d'ecrasement). Idempotent.

Reversible : retirer l'appel apply() = comportement d'origine (LAFORGE_ seul). A
appeler tot au boot, APRES le chargement du .env, AVANT les lectures d'env. Zero
dependance (stdlib) pour rester importable au tout debut du boot.
"""
from __future__ import annotations

import os

_OLD = "LAFORGE_"
_NEW = "NOKIDO_"


def apply(environ=None) -> int:
    """Miroir bidirectionnel LAFORGE_ <-> NOKIDO_. Retourne le nb d'alias crees."""
    env = os.environ if environ is None else environ
    created = 0
    for key in list(env.keys()):  # snapshot : on mute env pendant l'iteration
        if key.startswith(_NEW):
            legacy = _OLD + key[len(_NEW):]
            if legacy not in env:
                env[legacy] = env[key]
                created += 1
        elif key.startswith(_OLD):
            modern = _NEW + key[len(_OLD):]
            if modern not in env:
                env[modern] = env[key]
                created += 1
    return created


if __name__ == "__main__":
    os.environ.pop("LAFORGE_FOO_SELFTEST", None)
    os.environ.pop("NOKIDO_FOO_SELFTEST", None)
    os.environ["NOKIDO_FOO_SELFTEST"] = "1"
    os.environ["LAFORGE_BAR_SELFTEST"] = "2"
    n = apply()
    assert os.environ.get("LAFORGE_FOO_SELFTEST") == "1", "NOKIDO_->LAFORGE_ KO"
    assert os.environ.get("NOKIDO_BAR_SELFTEST") == "2", "LAFORGE_->NOKIDO_ KO"
    print("OK forge_env_alias selftest (alias crees=" + str(n) + ")")
