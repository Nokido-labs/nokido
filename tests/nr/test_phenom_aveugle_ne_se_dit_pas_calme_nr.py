"""NR -- un flux phenomenologique dont AUCUN capteur n'est lisible ne se dit pas « calme » (UNKNOWN != NO).

Mesure 2026-10-16 : NokidoPhenomBuffer ecrivait « Je me sens calme, pose. » 60 fois sur 60, affect nul, depuis le
11/09 -- ses trois capteurs (tempo subjectif, humeur, hormones) levaient ModuleNotFoundError sous except/pass, et
l'etat vide se decrivait comme un arousal bas. Un capteur aveugle fabriquait du faux calme.
"""
import sys

from nokido_agent.app import forge_phenomenological_buffer as P

_CAPTEURS = ("nokido_agent.app.forge_subjective_time", "nokido_agent.app.forge_system_mood",
             "nokido_agent.app.forge_endocrine")


def _aveugler(monkeypatch, noms=_CAPTEURS):
    import importlib

    paquet = importlib.import_module("nokido_agent.app")
    for n in noms:
        monkeypatch.setitem(sys.modules, n, None)  # `import` leve ImportError
        # CI de reference bf3e70e29 : `from nokido_agent.app import x` rend l'ATTRIBUT du paquet quand un test
        # anterieur a deja importe x -- sys.modules seul n'aveuglait que les capteurs jamais charges.
        monkeypatch.delattr(paquet, n.rsplit(".", 1)[1], raising=False)


def test_sans_aucun_capteur_le_flux_dit_qu_il_ne_percoit_rien(monkeypatch):
    _aveugler(monkeypatch)
    desc = P._describe_deterministic(P.sense())
    assert "calme" not in desc.lower(), desc
    assert "illisible" in desc.lower(), desc


def test_un_capteur_manquant_est_nomme(monkeypatch):
    _aveugler(monkeypatch, ("nokido_agent.app.forge_endocrine",))
    etat = P.sense()
    assert "hormones" in etat.get("capteurs_illisibles", []), etat
