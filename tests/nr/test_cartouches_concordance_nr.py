"""NR — la concordance cartouches/coffre ÉNUMÈRE le coffre et ne devine jamais.

Mesure 2026-09-06 : j'ai déclaré la clé `SILICONFLOW` absente après avoir deviné seize
noms, alors que le coffre en porte **87** et qu'elle s'y trouvait. `forge_secrets.
diagnostic()` ne coche qu'une liste de 26 noms écrite en dur : son silence n'était pas
une absence, c'était un angle mort. Conséquence dans l'autre sens : neuf capacités
possédées (Modal, SiliconFlow, DeepInfra, Together, Voyage, Jina, Mammouth, Tavily,
Smithery) n'étaient annoncées par aucune cartouche du README.

Quatre garanties :
  1. un coffre illisible rend INDÉTERMINÉ, jamais une liste vide rassurante ;
  2. `CARTOUCHE_SANS_CLEF` est classé « à justifier », pas « à supprimer » — un modèle
     peut être routé via un agrégateur sans clé propre ;
  3. les cartouches de socle (Python, Deno…) ne sont jamais comptées comme fournisseurs ;
  4. l'outil ne lit ni n'imprime aucune VALEUR de secret.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_cartouches_concordance as C  # noqa: E402


def _poser_coffre(monkeypatch, faux) -> None:
    """Pose le faux coffre sur TOUS les noms par lesquels il est atteint.

    ⚠️ DEFAUT MESURE le 2026-09-10, CI de reference sur f8d71d2d5. Les deux
    clefs `sys.modules` etaient posees, mais `forge_cartouches_concordance`
    fait `from nokido_agent.app import forge_machine_vault as MV` (L103) —
    cette forme lit l'ATTRIBUT du paquet AVANT `sys.modules`. Le VRAI coffre
    repondait donc, et le test qui simule un coffre ILLISIBLE recevait une
    vraie liste : `['PYPI_TOKEN', 'TESTPYPI_TOKEN'] == []`.

    Le plus instructif : ces tests PASSAIENT sur ma machine, ou le coffre est
    muet pour ce compte. Ils etaient verts POUR LA MAUVAISE RAISON, et seule la
    CI de reference — dont le compte voit un coffre peuple — l'a revele. Un
    test qui simule une panne doit la SIMULER, pas l'emprunter a son
    environnement.
    """
    monkeypatch.setitem(sys.modules, "forge_machine_vault", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_machine_vault", faux)
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None and hasattr(paquet, "forge_machine_vault"):
        monkeypatch.setattr(paquet, "forge_machine_vault", faux)


def test_un_coffre_illisible_rend_indetermine_et_non_une_liste_vide(monkeypatch):
    faux = type(sys)("forge_machine_vault")
    faux.available = lambda: False
    faux.vault_list = lambda: []
    _poser_coffre(monkeypatch, faux)
    cles, souci = C.clefs_coffre()
    assert cles == [] and "INDETERMINE" in souci, (cles, souci)


def test_le_coffre_est_enumere_pas_devine(monkeypatch):
    """`vault_list()` est la source : aucune liste de noms en dur dans le module."""
    faux = type(sys)("forge_machine_vault")
    faux.available = lambda: True
    faux.vault_list = lambda: ["SILICONFLOW", "DEEPINFRA", "FORGE_TOKEN_CLAUDE"]
    _poser_coffre(monkeypatch, faux)
    cles, souci = C.clefs_coffre()
    assert souci == "" and "SILICONFLOW" in cles


def test_les_quatre_etats_sont_distingues(monkeypatch):
    faux = type(sys)("forge_machine_vault")
    faux.available = lambda: True
    # DeepInfra possede sa clef ; OpenAI non (routage via agregateur)
    faux.vault_list = lambda: ["DEEPINFRA", "CEREBRAS_API_KEY", "FORGE_TOKEN_CLAUDE"]
    _poser_coffre(monkeypatch, faux)
    monkeypatch.setattr(C, "cartouches", lambda: ["Cerebras", "OpenAI", "Python"])
    d = C.concordance()
    assert "Cerebras" in d["ALIGNE"]
    assert "DeepInfra" in d["CLEF_SANS_CARTOUCHE"], d["CLEF_SANS_CARTOUCHE"]
    assert "OpenAI" in d["CARTOUCHE_SANS_CLEF"], d["CARTOUCHE_SANS_CLEF"]
    # une cartouche de socle n'est ni fournisseur ni anomalie
    assert "Python" not in d["cartouches_non_classees"]
    # un jeton interne n'est pas compte comme fournisseur externe
    assert d["clefs_externes"] == 2, d["clefs_externes"]


def test_aucune_valeur_de_secret_n_est_lue():
    src = (ROOT / "tools" / "forge_cartouches_concordance.py").read_text(
        encoding="utf-8", errors="replace")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "vault_get" not in code, "l'outil ne doit lire que des NOMS"
    assert "get_secret" not in code, "l'outil ne doit lire que des NOMS"
