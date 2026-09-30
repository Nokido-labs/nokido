"""NR -- la regle `laforge-cloud-secret-from-env` ne prend pas une DUREE pour un secret, et garde les vrais.

MESURE 2026-09-26 (CI de reference f6b3613bb) : cliquet golden-rules ROMPU, `app/forge_key_rotation.py
(3 -> 4)`. La 4e « violation » est `os.environ.get("LAFORGE_KEY_LEDGER_LOCK_S", "2")` (bddb3bc9a, 24/09) :
un delai de verrou en SECONDES, qui contient « _KEY » par hasard. `_RE_SECRET_ENV` accroche `_KEY` n'importe
ou dans le nom. Meme raison que l'exclusion deja faite pour `_PATH`/`_DIR`/`_FILE` : un garde qui crie sur
un reglage numerique se fait desarmer. Le symetrique est garde : les vrais noms de secret restent pris.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_golden_rules_ast as g  # noqa: E402


def test_une_duree_n_est_pas_un_secret():
    for nom in ("LAFORGE_KEY_LEDGER_LOCK_S", "LAFORGE_KEY_LEDGER_LOCK_MS", "LAFORGE_TOKEN_TTL_SECONDS"):
        assert g._RE_SECRET_ENV.search(nom) is None, nom


def test_les_vrais_secrets_restent_pris():
    for nom in ("GROQ_API_KEY", "LAFORGE_DB_KEY", "LANGFUSE_PUBLIC_KEY", "PRIVATE_KEY_PEM", "HF_TOKEN",
                "LAFORGE_SECRET", "DB_PASSWORD", "LAFORGE_KEYS"):
        assert g._RE_SECRET_ENV.search(nom) is not None, nom


def test_les_chemins_restent_exclus():
    for nom in ("LAFORGE_DB_PATH", "LAFORGE_KEY_DIR", "LAFORGE_TOKEN_FILE"):
        assert g._RE_SECRET_ENV.search(nom) is None, nom
