"""Non-regression : le corps ARBITRE les reclamations de piliers, le client obeit.

Defaut mesure le 2026-09-01 (incident owner). Le vocabulaire d'intention
`sandbox/*.wanted` donnait un declarant aux gardes, mais AUCUN arbitre : le client
posait le drapeau au moment ou il echouait, et le corps ne pouvait pas refuser.
Boucle payee : `_embed_llama8099` echoue -> `embed.wanted` -> le keeper rallume
NokidoLlamaEmbed -> le resource manager l'evince pour rendre la RAM -> le drain ne
trouve plus :8099 et repose le drapeau 19 s plus tard. Machine a 98 % de RAM.

Ces tests portent sur l'EFFET, pas sur la presence des champs :

  1. sans politique, le corps NE REFUSE RIEN (trois etats, jamais deux : une source
     qui se tait ne vaut pas un refus, sinon un fichier absent couperait en silence) ;
  2. politique illisible = meme regle -- INCONNU, pas REFUSE ;
  3. un pilier refuse l'est AVEC son substitut : un refus muet renvoie le client a
     son echec, donc a reposer le drapeau ;
  4. le drapeau n'est PLUS pose quand le corps refuse ;
  5. la porte locale :8099 est fermee AU RAS DU SOCKET, pas seulement dans la
     cascade `PROVIDERS` -- `embed_batch` tape ce port en dur, hors cascade ;
  6. la cascade n'essaie QUE les backends autorises (un essai local qui echoue
     RECLAME le pilier : le seul moyen de ne pas reclamer est de ne pas essayer).

Zero service externe : ecritures confinees a tmp_path, reseau remplace par une
sonde qui echoue si elle est atteinte.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_embed_router as router  # noqa: E402
import forge_pillar_arbiter as arbitre  # noqa: E402


def _politique(monkeypatch, tmp_path, contenu) -> Path:
    """Pointe l'arbitre sur une politique jetable et invalide son cache."""
    cible = tmp_path / "pillar_policy.json"
    if contenu is not None:
        cible.write_text(
            contenu if isinstance(contenu, str) else json.dumps(contenu),
            encoding="utf-8")
    monkeypatch.setattr(arbitre, "_POLITIQUE", cible)
    monkeypatch.setattr(arbitre, "_CACHE", {"lu_a": 0.0, "mtime": None, "data": None})
    monkeypatch.setattr(arbitre, "_DERNIER_LOG", {})
    return cible


_POLITIQUE_MODAL = {
    "piliers": {"embed.wanted": {"accorde": False, "substitut": "modal",
                                 "motif": "embedding = Modal uniquement"}},
    "backends": {"embed": ["modal"]},
}


def test_politique_absente_n_est_pas_un_refus(monkeypatch, tmp_path):
    """Pas de fichier => INCONNU => accorde. Une absence ne coupe rien."""
    _politique(monkeypatch, tmp_path, None)
    verdict = arbitre.reclamer("embed.wanted")
    assert verdict["etat"] == arbitre.INCONNU
    assert verdict["accorde"] is True
    assert arbitre.backends_autorises("embed") is None


def test_politique_illisible_n_est_pas_un_refus(monkeypatch, tmp_path):
    """JSON casse => INCONNU. Un capteur muet ne doit jamais valoir un verdict."""
    _politique(monkeypatch, tmp_path, "{ ceci n'est pas du json")
    verdict = arbitre.reclamer("embed.wanted")
    assert verdict["etat"] == arbitre.INCONNU
    assert verdict["accorde"] is True


def test_refus_nomme_son_substitut(monkeypatch, tmp_path):
    """Un refus sans alternative renverrait le client a son echec."""
    _politique(monkeypatch, tmp_path, _POLITIQUE_MODAL)
    verdict = arbitre.reclamer("embed.wanted")
    assert verdict["etat"] == arbitre.REFUSE
    assert verdict["accorde"] is False
    assert verdict["substitut"] == "modal"
    assert verdict["motif"]
    # Un flag NON declare reste inconnu : la politique ne refuse que ce qu'elle nomme.
    assert arbitre.reclamer("docker.wanted")["etat"] == arbitre.INCONNU


def test_drapeau_non_pose_quand_le_corps_refuse(monkeypatch, tmp_path):
    """`declare_wanted` doit rendre False ET ne rien ecrire."""
    _politique(monkeypatch, tmp_path, _POLITIQUE_MODAL)
    monkeypatch.setattr(router, "_WANT_TS", {})
    depose = Path(router.__file__).resolve().parent.parent / "sandbox" / "embed.wanted"
    avant = depose.stat().st_mtime if depose.exists() else None

    assert router.declare_wanted("embed.wanted", cooldown=0.0) is False
    assert router.declare_embed_wanted(cooldown=0.0) is False

    apres = depose.stat().st_mtime if depose.exists() else None
    assert apres == avant, "le drapeau a ete (re)pose alors que le corps refuse"


def test_porte_locale_fermee_au_ras_du_socket(monkeypatch, tmp_path):
    """`embed_batch` tape :8099 en dur : filtrer PROVIDERS seul ne fermait rien."""
    _politique(monkeypatch, tmp_path, _POLITIQUE_MODAL)

    def _interdit(*_a, **_k):
        raise AssertionError("le reseau local :8099 a ete atteint malgre la politique")

    monkeypatch.setattr(router.urllib.request, "urlopen", _interdit)
    assert router._role_embed_local_autorise() is False
    assert router._embed_llama8099("bonjour") is None
    assert router._llama8099_call(["bonjour"]) is None


def test_cascade_n_essaie_que_les_backends_autorises(monkeypatch, tmp_path):
    """Ne pas reclamer un pilier = ne pas l'essayer. Le reste est du bruit."""
    _politique(monkeypatch, tmp_path, _POLITIQUE_MODAL)
    essais: list[str] = []

    def _local(_texte, timeout=30.0):
        essais.append("llama8099")
        return None

    def _modal(_texte, timeout=10.0):
        essais.append("modal")
        return [0.1] * 1024

    monkeypatch.setattr(router, "PROVIDERS",
                        [("llama8099", _local), ("modal", _modal)])
    monkeypatch.setattr(router, "_modal_url", lambda: "https://exemple.invalid/embed")
    monkeypatch.setattr(router, "_CB_STATE", {})
    # `embed()` ecarte un provider SANS credential avant meme de l'appeler. Sans ce
    # neutralisant, le test mesurait la presence d'une cle Modal dans le coffre au
    # lieu de mesurer la POLITIQUE -- il devenait rouge partout ou le coffre ne
    # repond pas (CI, compte sandbox), c'est-a-dire precisement la ou il tourne.
    # Un test de PURE_TESTS ne depend d'aucun secret ni d'aucun service.
    monkeypatch.setattr(router, "_provider_has_creds", lambda _nom: True)
    # Idem pour le BUDGET, et c'est celui-la qui a fait rougir la CI du 2026-09-01 :
    # `BudgetManager` rendait `(False, 'cooldown 156s remaining')` -- un cooldown arme
    # par les 404 Modal de la journee -- donc AUCUN provider n'etait appele et le test
    # echouait sans rapport avec l'arbitrage. Un test dont le verdict depend d'un etat
    # global vivant est FLAKY par construction : vert le matin, rouge le soir.
    import forge_llm_budget as _budget

    monkeypatch.setattr(_budget.BudgetManager, "can_call",
                        lambda self, *a, **k: (True, "budget neutralise (test)"))

    vec = router.embed("un texte a vectoriser")
    assert vec is not None and len(vec) == 1024
    assert essais == ["modal"], f"backends essayes : {essais}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
