"""NR — `tools/forge_vault_mint_agent_token.py` : ses EFFETS, pas son import.

Cet outil frappe un secret. Ce qu'il ne doit JAMAIS faire pese plus lourd que ce
qu'il fait, et c'est cela qui est verrouille ici :

  1. il n'imprime JAMAIS la valeur -- ni entiere, ni tronquee. La sortie d'un
     `trusted_script` est journalisee par le hub (`_handle_trusted_script`
     consigne `script_args=%r`), donc tout ce qui sort finit ecrit quelque part ;
  2. il REFUSE une identite absente du registre : un secret frappe pour un nom
     inconnu serait resolu ring 4, sans effet, et pourtant bien reel ;
  3. il est IDEMPOTENT : un second passage ne remplace rien sans `--rotate` ;
  4. il ne conclut pas au succes sur une ecriture qu'il n'a pas pu relire.

HERMETIQUE : coffre injecte, registre construit dans `tmp_path`. Aucun secret
reel n'est lu ni ecrit, aucun fichier du depot n'est touche.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_secrets as fs  # noqa: E402
import forge_vault_mint_agent_token as mint  # noqa: E402

_AGENT = "AUTONOMOUS_LOOPS"
_CLE = "FORGE_TOKEN_AUTONOMOUS_LOOPS"


@pytest.fixture()
def coffre(monkeypatch):
    """Coffre en memoire. Le vrai vit dans `data/machine_vault.dat` : un test qui
    l'ouvrirait ecrirait un secret reel, et echouerait de toute facon sous le
    compte bac a sable (mesure : `[Errno 13]` sur le fichier temporaire)."""
    store: dict = {}
    ecritures: list = []

    def _set(cle, valeur, *a, **kw):
        ecritures.append(cle)
        store[cle] = valeur
        return True

    monkeypatch.setattr(fs, "get_secret", lambda k, *a, **kw: store.get(k))
    monkeypatch.setattr(fs, "set_secret", _set)
    monkeypatch.setattr(fs, "invalidate_cache", lambda *a, **kw: None)
    store["_ecritures"] = ecritures      # visible du test, ignore par l'outil
    return store


def _registre(tmp_path, monkeypatch, agents: dict) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "agent_identities.json").write_text(
        json.dumps({"agents": agents}), encoding="utf-8")
    monkeypatch.setattr(mint, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def declare(tmp_path, monkeypatch):
    return _registre(tmp_path, monkeypatch, {_AGENT: {"ring": 2}})


# ── ce que l'outil REFUSE ───────────────────────────────────────────────────
def test_1_identite_inconnue_REFUSEE_et_rien_ecrit(tmp_path, monkeypatch, coffre):
    """Frapper pour un nom inconnu creerait une identite fantome."""
    _registre(tmp_path, monkeypatch, {"UN_AUTRE": {"ring": 2}})
    assert mint.main(["--agent", _AGENT]) == 1
    assert coffre["_ecritures"] == []


def test_2_registre_ILLISIBLE_fait_refuser_pas_supposer(tmp_path, monkeypatch, coffre):
    """Illisible n'est pas « absent » : on ne frappe pas a l'aveugle."""
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "agent_identities.json").write_text("{pas du json",
                                                               encoding="utf-8")
    monkeypatch.setattr(mint, "ROOT", tmp_path)
    assert mint.main(["--agent", _AGENT]) == 1
    assert coffre["_ecritures"] == []


def test_3_registre_ABSENT_fait_refuser(tmp_path, monkeypatch, coffre):
    monkeypatch.setattr(mint, "ROOT", tmp_path / "vide")
    assert mint.main(["--agent", _AGENT]) == 1
    assert coffre["_ecritures"] == []


@pytest.mark.parametrize("nom", ["ag ent", "ag-ent", "ag.ent", "ag/ent"])
def test_4_nom_invalide_refuse_avant_toute_lecture(nom, coffre, declare):
    assert mint.main(["--agent", nom]) == 2
    assert coffre["_ecritures"] == []


# ── ce que l'outil FAIT ─────────────────────────────────────────────────────
def test_5_frappe_un_jeton_de_64_hex(coffre, declare):
    assert mint.main(["--agent", _AGENT]) == 0
    assert coffre["_ecritures"] == [_CLE]
    v = coffre[_CLE]
    assert len(v) == 64 and all(c in "0123456789abcdef" for c in v)


def test_6_IDEMPOTENT_un_second_passage_ne_remplace_rien(coffre, declare):
    assert mint.main(["--agent", _AGENT]) == 0
    premier = coffre[_CLE]
    assert mint.main(["--agent", _AGENT]) == 0
    assert coffre[_CLE] == premier
    assert coffre["_ecritures"] == [_CLE], "une seule ecriture pour deux passages"


def test_7_rotate_remplace_reellement(coffre, declare):
    mint.main(["--agent", _AGENT])
    premier = coffre[_CLE]
    assert mint.main(["--agent", _AGENT, "--rotate"]) == 0
    assert coffre[_CLE] != premier


def test_8_verify_n_ecrit_JAMAIS(coffre, declare):
    assert mint.main(["--agent", _AGENT, "--verify"]) == 0
    assert coffre["_ecritures"] == []
    assert _CLE not in coffre


# ── ce que l'outil ne conclut PAS ───────────────────────────────────────────
def test_9_ecriture_rapportee_OK_mais_relecture_VIDE_est_un_echec(
        monkeypatch, coffre, declare):
    """« set_secret a rendu True » n'est pas une preuve : on relit, et un vide
    apres une ecriture reussie doit sortir en echec, pas en succes."""
    monkeypatch.setattr(fs, "set_secret", lambda *a, **kw: True)   # n'ecrit rien
    assert mint.main(["--agent", _AGENT]) == 1


def test_10_rotation_qui_ne_change_pas_l_empreinte_est_un_echec(
        monkeypatch, coffre, declare):
    """Une rotation qui rend la MEME valeur n'a rien roule."""
    mint.main(["--agent", _AGENT])
    fige = coffre[_CLE]
    monkeypatch.setattr(fs, "set_secret", lambda k, v, *a, **kw: True)  # garde l'ancienne
    assert mint.main(["--agent", _AGENT, "--rotate"]) == 1
    assert coffre[_CLE] == fige


def test_11_echec_d_ecriture_du_coffre_sort_en_echec(monkeypatch, coffre, declare):
    monkeypatch.setattr(fs, "set_secret", lambda *a, **kw: False)
    assert mint.main(["--agent", _AGENT]) == 1


# ── L'INVARIANT DE SECURITE ─────────────────────────────────────────────────
def test_12_la_valeur_n_est_JAMAIS_imprimee(capsys, coffre, declare):
    """Tout ce qui sort d'un `trusted_script` est journalise par le hub.

    On verifie sur la sortie REELLE, pas sur une relecture du code : ni la valeur
    entiere, ni aucun prefixe assez long pour l'affaiblir.
    """
    assert mint.main(["--agent", _AGENT]) == 0
    sortie = capsys.readouterr().out
    v = coffre[_CLE]
    assert v not in sortie
    for n in (8, 12, 16, 32):
        assert v[:n] not in sortie, "un prefixe de %d caracteres a fuite" % n
    # Ce qui DOIT sortir : des metadonnees, et l'empreinte courte du sha256.
    assert "present" in sortie and "longueur" in sortie
    assert "empreinte_sha256_8" in sortie


def test_13_la_ligne_de_commande_n_accepte_AUCUNE_valeur_de_secret(declare, coffre):
    """`script_args` est journalise en clair par le hub : l'outil ne doit donc
    exposer aucun parametre capable de porter un secret."""
    with pytest.raises(SystemExit):
        mint.main(["--agent", _AGENT, "--token", "deadbeef"])
    with pytest.raises(SystemExit):
        mint.main(["--agent", _AGENT, "--valeur", "deadbeef"])
    assert coffre["_ecritures"] == []


def test_14_le_ring_lu_est_celui_du_registre(tmp_path, monkeypatch, coffre):
    """La source du ring doit rester `config/agent_identities.json` : une autre
    liste ferait diverger le coffre et le registre du hub."""
    _registre(tmp_path, monkeypatch, {_AGENT: {"ring": 2}})
    assert mint._ring_declare(_AGENT) == 2
    assert mint._ring_declare("INEXISTANT") is None
    _registre(tmp_path, monkeypatch, {_AGENT: {"ring": "pas_un_nombre"}})
    assert mint._ring_declare(_AGENT) is None
