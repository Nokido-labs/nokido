"""NR — une intention POSEE doit etre RELISIBLE, sinon elle n'est pas posee.

MESURE DU 2026-09-20 qui motive ce garde :

    sandbox/rerank.wanted      0 o   b''                        <- VIDE, mtime 25 min
    sandbox/embed.wanted      18 o   b'1789922503.1115315'
    sandbox/llama.wanted      54 o   b'{"ts": ..., "by": "forge_llm_ondemand"}'
    sandbox/snn.wanted      1229 o   b'Arme le capteur SNN des vitals (...)'

`forge_audit_intention_effet` rend `rerank: false` et `chaines=0` : un drapeau
de 0 octet ne se lit pas comme une intention, mais son ECRITURE avait rendu
`True`. C'est « attempt != success » applique a l'ecriture elle-meme -- le meme
motif que la substitution qui rate et qu'on croit appliquee (paye le 2026-09-18
sur 2 correctifs de securite sur 5).

PORTEE, dite explicitement : ce NR garde UN defaut -- l'ecriture non verifiee du
poseur COMMUN. Il ne garde PAS l'unification des formats (4 formats pour
5 drapeaux, N poseurs independants : forge_llm_ondemand._poser_drapeau,
forge_docker_agent, forge_exegol_mcp_server ecrivent sans passer par lui). C'est
un chantier distinct, NOMME ici pour qu'il ne se perde pas.
"""
from __future__ import annotations

import pathlib

import pytest


def _module():
    """Resout le module par SES DEUX noms d'import.

    Lecon du 2026-09-10 : `X` et `nokido_agent.app.X` sont DEUX instances avec
    DEUX etats -- patcher l'une laisse l'autre intacte et le test devient un
    faux vert. On resout a l'appel, jamais a l'import du fichier de test.
    """
    for nom in ("nokido_agent.app.forge_embed_router", "app.forge_embed_router",
                "forge_embed_router"):
        try:
            mod = __import__(nom, fromlist=["declare_wanted"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "declare_wanted"):
            return mod
    pytest.skip("forge_embed_router introuvable sous ses trois noms d'import")


def _sans_arbitre(monkeypatch, mod):
    """Neutralise l'arbitre : ce NR mesure l'ECRITURE, pas la politique."""
    for nom in ("nokido_agent.app.forge_pillar_arbiter", "app.forge_pillar_arbiter",
                "forge_pillar_arbiter"):
        try:
            arb = __import__(nom, fromlist=["reclamer"])
        except Exception:  # noqa: BLE001
            continue
        monkeypatch.setattr(arb, "reclamer",
                            lambda flag, motif="": {"accorde": True}, raising=False)
    monkeypatch.setattr(mod, "_WANT_TS", {}, raising=False)


FLAG = "nr_intention_ecriture_verifiee.wanted"


@pytest.fixture(autouse=True)
def cible(monkeypatch):
    mod = _module()
    _sans_arbitre(monkeypatch, mod)
    sb = pathlib.Path(mod.__file__).resolve().parent.parent / "sandbox"
    chemin = sb / FLAG
    yield chemin
    try:
        chemin.unlink()
    except OSError:
        pass


def test_une_ecriture_qui_laisse_zero_octet_ne_vaut_PAS_une_pose(monkeypatch, cible):
    """LE COEUR DU CONTRAT.

    Un `write_text` qui rend la main en laissant un fichier vide ne leve pas :
    sans relecture, le poseur annonce un succes et le corps croit l'intention
    posee. Mesure : `rerank.wanted` = 0 o pendant que le journal ne portait
    AUCUNE ligne « NON posee ».
    """
    mod = _module()

    def _write_vide(self, data, **kw):        # noqa: ANN001 - signature de Path
        with open(self, "w", encoding="utf-8"):
            pass                              # tronque, n'ecrit RIEN
        return 0

    monkeypatch.setattr(pathlib.Path, "write_text", _write_vide)
    pose = mod.declare_wanted(FLAG, cooldown=0.0, motif="NR ecriture vide")
    assert pose is False, (
        "une ecriture qui laisse 0 octet a ete rapportee comme une pose reussie "
        "-- c'est exactement la panne muette mesuree sur rerank.wanted")


def test_une_pose_reussie_est_RELISIBLE_et_non_vide(cible):
    """Le symetrique : on ne durcit pas au point de tout refuser."""
    mod = _module()
    assert mod.declare_wanted(FLAG, cooldown=0.0, motif="NR pose nominale") is True
    brut = cible.read_bytes()
    assert brut, "le drapeau existe mais il est VIDE apres une pose declaree reussie"
    assert float(brut.decode("utf-8").strip()) > 0, (
        "le contenu du drapeau n'est pas un horodatage exploitable")


def test_le_cooldown_reste_honore(cible):
    """La verification ne doit pas transformer un cooldown en echec d'ecriture."""
    mod = _module()
    assert mod.declare_wanted(FLAG, cooldown=0.0, motif="NR premiere") is True
    assert mod.declare_wanted(FLAG, cooldown=9999.0, motif="NR seconde") is False
    assert cible.read_bytes(), (
        "le cooldown a efface le drapeau -- un refus de reposer n'est pas un retrait")
