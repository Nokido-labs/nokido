"""NR -- UNE autorite OAuth, parametree par passerelle (connecteur des pairs cloud, 2026-09-28).

`forge_bridge_oauth` etait soude a la passerelle GitHub (chemin fixe, audience, portee, depot).
Le connecteur des pairs (claude.ai, ChatGPT) a besoin de la MEME autorite -- DCR, consentement par
code d'appariement, jetons courts relus a chaque requete -- avec d'autres valeurs, dans un autre
processus. Contrat :
  - sans NOKIDO_OAUTH_PASSERELLE : la passerelle GitHub, inchangee (le connecteur ChatGPT ne bouge pas) ;
  - avec : la passerelle nommee, et SEULEMENT un `tools/forge_passerelle_*.py` (jamais un chemin
    arbitraire -- sinon l'environnement choisirait qui signe les habilitations) ;
  - une habilitation d'une passerelle est REFUSEE par l'autre (audience) ;
  - la mecanique (sceau, expiration, revocation) n'est pas recopiee : la passerelle pair emprunte
    `forge_github_bridge.lire_capacite`.
Cles de test factices.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _charger(chemin: Path, nom: str):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _oauth(monkeypatch, passerelle=None):
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", "cle-de-test-passerelle")
    if passerelle is None:
        monkeypatch.delenv("NOKIDO_OAUTH_PASSERELLE", raising=False)
    else:
        monkeypatch.setenv("NOKIDO_OAUTH_PASSERELLE", passerelle)
    return _charger(ROOT / "tools" / "forge_bridge_oauth.py", "nr_oauth_passerelle")


def _jeton(pont, **surcharge):
    charge = {"sub": "client-test", "aud": pont.AUDIENCE, "scope": pont.SCOPE,
              "resource": sorted(pont.DEPOTS_AUTORISES)[0], "exp": int(time.time()) + 300,
              "jti": "jti-test-%s" % pont.AUDIENCE, "replay": "multi"}
    charge.update(surcharge)
    return pont.forger_capacite(charge)


def test_sans_reglage_c_est_le_pont_github_inchange(monkeypatch):
    oauth = _oauth(monkeypatch)
    assert Path(oauth._CHEMIN_PONT).name == "forge_github_bridge.py"
    gh = _charger(ROOT / "tools" / "forge_github_bridge.py", "nr_gh_ref")
    assert oauth.PONT.AUDIENCE == gh.AUDIENCE and oauth.PONT.SCOPE == gh.SCOPE


def test_la_passerelle_pair_a_ses_valeurs_et_accepte_ses_jetons(monkeypatch):
    oauth = _oauth(monkeypatch, "forge_passerelle_pair.py")
    pont = oauth.PONT
    assert (pont.AUDIENCE, pont.SCOPE) == ("nokido-pair", "pair:collaborer")
    assert oauth.depot_unique() == "nokido:pair"
    charge, motif = oauth.verifier(_jeton(pont))
    assert motif is None and charge["sub"] == "client-test"


def test_une_habilitation_ne_passe_pas_d_une_passerelle_a_l_autre(monkeypatch):
    gh = _oauth(monkeypatch)
    pair = _oauth(monkeypatch, "forge_passerelle_pair.py")
    jeton_gh = _jeton(gh.PONT)
    jeton_pair = _jeton(pair.PONT)
    assert pair.verifier(jeton_gh)[0] is None
    assert gh.verifier(jeton_pair)[0] is None


@pytest.mark.parametrize("chemin", ["../app/forge_secrets.py", "C:/tmp/forge_passerelle_x.py",
                                    "forge_github_bridge_mcp.py", "forge_passerelle_pair.py/../x.py"])
def test_seul_un_module_forge_passerelle_de_tools_est_accepte(monkeypatch, chemin):
    with pytest.raises(SystemExit):
        _oauth(monkeypatch, chemin)
