"""NR — le verdict du cliquet de contexte ne depend pas de la MACHINE.

Defaut mesure le 2026-09-20. Le poste `descriptions_skills` lit quatre racines,
dont deux qui n'appartiennent pas au depot : le profil de l'utilisateur et le
cache de plugins. Consequence, le meme commit rend deux verdicts differents :

    poste local   45 603 o  (86 skills, 4 racines)
    runner CI     28 727 o  -> DEPASSE 16 000, la CI GitHub echoue

Le runner tourne sous son propre repertoire de travail, avec son propre profil
et son propre cache de plugins. Le denominateur change donc avec la machine.

⚠️ UN CLIQUET DONT LE DENOMINATEUR CHANGE AVEC LA MACHINE NE JUGE RIEN, et
surtout ne se rattache a aucun commit : c'est precisement ce que la phase 0
demande (« un statut FERME PAR COMMIT »). Le budget doit donc porter sur ce que
le DEPOT controle ; ce qui vient de la machine reste MESURE et RAPPORTE, mais
hors verdict — sinon on ferait echouer une CI pour des fichiers que le commit
ne contient pas et que personne ne peut corriger par un diff.

Pur : aucune ressource externe, aucun service. On simule un profil qui refuse.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_context_budget  # type: ignore

    return forge_context_budget


def _refuser(m, monkeypatch, noms):
    """Fait REFUSER les racines nommees, en simulant un refus et non une absence."""
    vrai = m._lire_racine
    cibles = {str(Path(ch)) for nom, ch in m.RACINES_SKILLS if nom in noms}

    def _lire(racine):
        if str(Path(racine)) in cibles:
            return {}, "PermissionError"
        return vrai(racine)

    monkeypatch.setattr(m, "_lire_racine", _lire, raising=True)


def test_les_racines_gouvernees_sont_celles_du_depot():
    """Le partage doit etre explicite et nomme, pas devine a la lecture."""
    m = _mod()
    assert hasattr(m, "RACINES_GOUVERNEES"), (
        "aucune declaration de ce que le depot GOUVERNE : le budget porterait "
        "alors sur des fichiers que le commit ne contient pas"
    )
    assert set(m.RACINES_GOUVERNEES) == {"projet", "depot"}, m.RACINES_GOUVERNEES
    noms = {nom for nom, _ in m.RACINES_SKILLS}
    assert set(m.RACINES_GOUVERNEES) <= noms, (
        "une racine gouvernee n'existe pas dans RACINES_SKILLS : %s" % noms
    )


def test_le_poste_separe_le_gouverne_de_l_informatif():
    """Les deux chiffres doivent voyager ENSEMBLE : cacher le hors-depot
    reviendrait a ne plus voir croitre ce qu'on a cesse de juger."""
    m = _mod()
    r = m.descriptions_skills()
    for cle in ("octets", "octets_gouvernes", "etat_gouverne"):
        assert cle in r, "le poste ne rend pas « %s » : %s" % (cle, sorted(r))
    if r["octets"] is not None and r["octets_gouvernes"] is not None:
        assert r["octets_gouvernes"] <= r["octets"], (
            "le gouverne depasse le total : %s" % r
        )


def test_le_volume_HORS_DEPOT_ne_change_PAS_le_verdict(monkeypatch):
    """LE COEUR. Deux machines, un seul commit, un seul verdict.

    ⚠️ CE TEST A D'ABORD ETE ECRIT « faire refuser le profil ne change pas le
    verdict » — et il PASSAIT DEJA, sans le correctif : sur ce poste le profil
    refuse deja pour de vrai, donc rien ne bougeait. Un test qui ne mord que sur
    les machines ou il est inutile ne garde rien ; c'est le defaut meme que ce
    fichier existe pour fermer. On INJECTE donc un volume hors depot enorme, ce
    qui mord sur TOUTE machine.
    """
    m = _mod()
    reference = m.mesurer()["depassements"]["descriptions_skills"]

    vrai = m._lire_racine
    hors = {str(Path(ch)) for nom, ch in m.RACINES_SKILLS
            if nom not in m.RACINES_GOUVERNEES}

    def _lire(racine):
        if str(Path(racine)) in hors:
            # Un profil obese : 400 skills de 1 000 o, trois fois le plafond.
            return {("skill_%03d" % i): 1000 for i in range(400)}, None
        return vrai(racine)

    monkeypatch.setattr(m, "_lire_racine", _lire, raising=True)
    r = m.mesurer()
    assert r["depassements"]["descriptions_skills"] == reference, (
        "400 000 o AJOUTES hors du depot ont change le verdict (%r -> %r) : le "
        "cliquet juge des fichiers que le commit ne contient pas, et le meme "
        "sha rendra des verdicts differents selon la machine"
        % (reference, r["depassements"]["descriptions_skills"])
    )
    assert m.descriptions_skills()["octets"] > 300_000, (
        "l'injection n'a pas mordu : le test ne prouve rien"
    )


def test_le_hors_depot_illisible_reste_DIT(monkeypatch):
    """Sortir du verdict n'est pas sortir du rapport. Un poste qu'on cesse de
    juger et qu'on cesse aussi de montrer disparait — c'est ainsi qu'une
    croissance devient invisible."""
    m = _mod()
    _refuser(m, monkeypatch, {"profil"})
    r = m.descriptions_skills()
    assert r.get("racines_illisibles"), (
        "une racine a refuse et le rapport ne le nomme pas : %s" % r
    )
    assert any("profil" in x for x in r["racines_illisibles"]), r["racines_illisibles"]
