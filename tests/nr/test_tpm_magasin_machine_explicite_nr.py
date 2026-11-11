"""NR 3/11 — le magasin MACHINE d'une cle TPM se choisit PAR APPEL, plus seulement par variable globale.

Pourquoi : `FORGE_TPM_MACHINE` est lue par le processus entier. Le hub (multitache, SYSTEM) ouvre plusieurs cles
(persona de forge_integrity, cle HUB de l'autorite OAuth) ; poser la variable pour l'une basculerait les autres, et
la poser/restaurer autour d'un appel (patron de forge_release_lock) laisse une fenetre ou un autre fil change de
magasin. D'ou un parametre `machine` explicite, sur le patron deja applique a etat_cle_tpm / descripteur_cle_tpm :
  machine=None -> la variable decide (comportement HISTORIQUE inchange) ; True -> MACHINE ; False -> UTILISATEUR.
Propage : _key_flags -> _open_key -> sign / sign_as / cle_publique_jwk / cle_publique_jwk_agent -> forge_dpop.CleTpm,
et le signataire OAuth du hub vise MACHINE (sa cle y vit, creee le 3/11 par forge_tpm_agent_keys --create HUB).
Aucune cle n'est ouverte : les appels NCrypt sont remplaces par des doublures.
"""
import pytest

from nokido_agent.app import forge_persona_tpm as T

MACHINE = T.NCRYPT_MACHINE_KEY_FLAG


@pytest.mark.parametrize("env,machine,attendu", [
    (None, None, False), ("1", None, True),              # historique : la variable decide
    (None, True, True), ("1", False, False),             # explicite : l'appel decide, la variable n'y peut rien
])
def test_key_flags(monkeypatch, env, machine, attendu):
    if env is None:
        monkeypatch.delenv("FORGE_TPM_MACHINE", raising=False)
    else:
        monkeypatch.setenv("FORGE_TPM_MACHINE", env)
    assert bool(T._key_flags(machine) & MACHINE) is attendu


def test_le_choix_est_propage_jusqu_a_l_ouverture(monkeypatch):
    monkeypatch.delenv("FORGE_TPM_MACHINE", raising=False)
    vus = []

    class Faux:
        def NCryptFreeObject(self, h):
            pass

    monkeypatch.setattr(T, "_ncrypt", lambda: (Faux(), None, None))
    monkeypatch.setattr(T, "_open_provider", lambda *a: object())
    monkeypatch.setattr(T, "_open_key", lambda nc, c, w, h, create=False, nom=None, machine=None:
                        vus.append(machine) or None)
    T.sign(b"x", nom="k", creer=False, machine=True)
    T.cle_publique_jwk("k", machine=True)
    assert vus and all(m is True for m in vus), vus


def test_signature_de_sign_as_inchangee():
    # deux gardes figent (agent_id, payload) : non-exportabilite != isolation. `machine` n'y entre PAS.
    import inspect
    assert list(inspect.signature(T.sign_as).parameters) == ["agent_id", "payload"]
    assert list(inspect.signature(T.cle_publique_jwk_agent).parameters) == ["agent_id"]


def test_cle_tpm_de_dpop_machine_par_nom_de_cle_d_agent(monkeypatch):
    from nokido_agent.app import forge_dpop as D
    vus = []
    monkeypatch.setattr(D, "_porteur_autorise", lambda a, j: True)
    monkeypatch.setattr(T, "nom_cle_agent", lambda a: "laforge-agent-%s-sign" % a)
    monkeypatch.setattr(T, "cle_publique_jwk", lambda nom=None, machine=None: vus.append(("jwk", nom, machine)) or
                        ({"kty": "EC", "crv": "P-256", "x": "AA", "y": "BB"}, ""))
    monkeypatch.setattr(T, "sign", lambda d, nom=None, creer=True, machine=None: vus.append(("sign", nom, machine))
                        or b"\x01" * 64)
    cle = D.CleTpm("HUB", "credential", machine=True)
    cle.sign(b"x")
    assert vus == [("jwk", "laforge-agent-HUB-sign", True), ("sign", "laforge-agent-HUB-sign", True)]


def test_cle_tpm_sans_machine_garde_le_chemin_historique(monkeypatch):
    from nokido_agent.app import forge_dpop as D
    vus = []
    monkeypatch.setattr(D, "_porteur_autorise", lambda a, j: True)
    monkeypatch.setattr(T, "cle_publique_jwk_agent", lambda a: vus.append("jwk_agent") or
                        ({"kty": "EC", "crv": "P-256", "x": "AA", "y": "BB"}, ""))
    monkeypatch.setattr(T, "sign_as", lambda a, d: vus.append("sign_as") or b"\x01" * 64)
    D.CleTpm("HUB", "credential").sign(b"x")
    assert vus == ["jwk_agent", "sign_as"]


def test_le_signataire_oauth_du_hub_vise_machine():
    from pathlib import Path
    from nokido_agent.app import forge_signature_hub as S
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert "machine=True" in src
