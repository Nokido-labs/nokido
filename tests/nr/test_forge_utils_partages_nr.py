# -*- coding: utf-8 -*-
"""NR -- utilitaires partages de forge_utils nes du cliquet clones (31/10).

valeur_option remplace claude_session_start._opt et forge_acp_router._val ; mapper_chaines remplace
acp_harness._caviarder_valeur et forge_db_sanitize._sanitize_dict_str_recursive. Le contrat est fige ici pour que
les quatre appelants ne divergent plus en silence.
"""
from forge_utils import mapper_chaines, valeur_option


def test_valeur_option_suit_l_option_ou_rend_none():
    argv = ["--racine", "C:/x", "--seul"]
    assert valeur_option(argv, "--racine") == "C:/x"
    assert valeur_option(argv, "--seul") is None      # option sans valeur
    assert valeur_option(argv, "--absente") is None


def test_mapper_chaines_ne_touche_que_les_chaines_imbriquees():
    v = {"a": "x", "b": ["y", 3, {"c": "z"}], "d": None}
    assert mapper_chaines(v, str.upper) == {"a": "X", "b": ["Y", 3, {"c": "Z"}], "d": None}
    assert mapper_chaines(7, str.upper) == 7
