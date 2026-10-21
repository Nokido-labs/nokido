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


def test_les_faux_positifs_mesures_le_16_10_ne_sont_pas_des_secrets():
    """Balayage du 16/10 des 37 fichiers geles (bb:active_bugs/secu_secrets_cloud_lus_dans_env_37_fichiers_geles) :
    une DUREE (_TTL), un COMPTE (_MAX_TOKENS), un CHEMIN (_KEYFILE) et `_KEY` au milieu d'un mot (KEYSTONE)
    etaient pris pour des secrets -- un cliquet qui crie a faux se fait desarmer."""
    for nom in ("LAFORGE_KEY_QUOTA_TTL", "LAFORGE_KEY_BAD_TTL", "ONNXGENAI_MAX_TOKENS", "LAFORGE_VC_KEYFILE",
                "LAFORGE_KEYSTONE_PH2",
                # chemin d'un fichier PEM (defaut sandbox/tls/key.pem dans forge_tls_caddy / forge_tls_proxy)
                "LAFORGE_HUB_TLS_KEY"):
        assert g._RE_SECRET_ENV.search(nom) is None, nom


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


def _regle(src: str) -> list:
    return [f for f in g.scan_source("tools/x.py", src) if f["rule"] == "laforge-cloud-secret-from-env"]


def test_ecrire_un_secret_dans_l_env_n_est_pas_le_lire():
    """Balayage du 16/10 : tools/store_openrouter_key.py ECRIT `os.environ["OPENROUTER_API_KEY"] = key` (propagation
    au process apres l'avoir range au coffre) -- la regle poursuit une LECTURE prise pour autorite, pas une ecriture."""
    assert _regle('import os\nos.environ["OPENROUTER_API_KEY"] = "v"\n') == []
    assert _regle('import os\ndel os.environ["OPENROUTER_API_KEY"]\n') == []


def test_un_alias_de_get_secret_compte_comme_le_coffre():
    """Mesure 16/10 : tools/nokido_hub.py importe `get_secret as _gs_sup`, interroge le guichet PUIS replie sur
    l'environnement -- la forme prescrite -- et la regle l'accusait, faute de reconnaitre l'alias."""
    src = ("import os\n"
           "def f():\n"
           "    from nokido_agent.app.forge_secrets import get_secret as _gs_sup\n"
           "    v = _gs_sup('LAFORGE_SUPERVISOR_TOKEN')\n"
           "    return v or os.environ.get('LAFORGE_SUPERVISOR_TOKEN')\n")
    assert _regle(src) == []


def test_lire_un_secret_par_indice_reste_pris():
    assert len(_regle('import os\nk = os.environ["OPENROUTER_API_KEY"]\n')) == 1
