"""NR — le prompt du digest ne transporte plus la carte interne, et le pont local vit.

DEUX DEFAUTS MESURES LE 2026-08-31, independants, qui bloquaient ensemble toute
mesure de la voie locale.

1. `_organs()` parcourait `data.values()` du census et appliquait `str(v)` a
   chaque valeur RACINE — dont `module_organ`, un dictionnaire de 1 280 modules.
   Mesure : **70 808 caracteres** injectes comme « ORGANES » dans chaque prompt
   biblio, pour 540 caracteres de matiere (99,3 % de decor). Un seul defaut, et
   quatre symptomes qu'on croyait distincts : le `413 Payload Too Large` de Groq,
   les refus DLP — c'est la carte interne du systeme qui partait au cloud, pas
   les articles —, les 51 appels historiques sans une seule suggestion, et
   l'impossibilite de tester la voie locale.

2. `forge_llamacpp._cfg()` appelait `get_secret` sans import a sa portee
   (NameError), et `_server_api_key()` le referencait AVANT un import local dans
   la meme fonction (UnboundLocalError). `is_available()` levait donc toujours,
   et le proxy rapportait « backend non pret (port ferme, modele non charge) »
   pendant que llama-server :8091 rendait `{"status":"ok"}` en 0,07 s avec
   4,7 Go residents. Un modele chaud, rendu inatteignable par un import manquant.

HERMETIQUE : aucun reseau, aucun LLM, aucun fichier du depot lu.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_llamacpp as fl  # noqa: E402
import forge_veille_digest as vd  # noqa: E402

# Le schema REEL au 2026-08-31, reproduit a l'identique : ce sont ses cles
# racine qui ont fait deraper l'ancienne lecture.
_TALLY = {
    "Infra/Bootstrap/Config": 176, "SNC (cerveau/moelle/SNP)": 165,
    "Memoire (hippocampe/RAG)": 139, "Cognition/Agentique/Raisonnement": 117,
    "Immunitaire (firewall/garde)": 88, "Observabilite/Trace": 74,
    "Locomoteur/Orchestration": 71, "Metabolisme LLM (routage/backends)": 66,
    "Qualite/Build/Spec": 61, "Digestif/Sens (ingestion/web)": 55,
    "Graph/Connaissances": 48, "Interface/UI (peau/expression)": 44,
    "Endocrine/Homeostat": 40, "Reproduction/Evolution": 33,
    "Circulatoire/Transport": 27, "non classe": 76,
}


def _census(**extra) -> dict:
    """Le census tel qu'il est REELLEMENT sur le disque."""
    d = {
        "module_organ": {"app/forge_%03d.py" % i: {"organ": "Infra/Bootstrap/Config",
                                                   "raison": "dossier", "poids": i}
                         for i in range(1280)},
        "tally": dict(_TALLY),
        "provenance": {"carte": 12, "mot_cle": 340, "dossier": 900, "declaration": 28},
        "generated_at": "2026-08-28T08:36:41+00:00",
        "generator": "tools/forge_module_census.py",
    }
    d.update(extra)
    return d


# ── CORRECTION 1 : la source canonique ──────────────────────────────────────

def test_1_les_organes_viennent_de_tally():
    noms = vd.noms_organes(_census())
    assert len(noms) == len(_TALLY)
    assert "Immunitaire (firewall/garde)" in noms
    assert noms == sorted(noms), "sortie deterministe"


def test_2_AUCUN_module_serialise_ne_ressort():
    """LA regression. `str(module_organ)` faisait 70 808 caracteres."""
    noms = vd.noms_organes(_census())
    rendu = ", ".join(noms)
    assert "module_organ" not in rendu
    assert "forge_000.py" not in rendu
    assert "{" not in rendu and "'organ'" not in rendu
    assert len(rendu) < 700, "70 808 chars mesures avant correction, %d apres" % len(rendu)


def test_3_la_garde_de_forme_rejette_une_structure_serialisee():
    """Le PROCHAIN changement de schema ne doit pas re-injecter un dict.

    Sans cette garde, un `tally` qui porterait autre chose que des noms courts
    reintroduirait silencieusement la panne — et un capteur qui se degrade en
    silence est exactement ce que ce fichier existe pour empecher.
    """
    empoisonne = _census(tally={
        "Immunitaire (firewall/garde)": 88,
        str({"app/forge_%d.py" % i: {"organ": "x"} for i in range(200)}): 1,
        "x" * 200: 1,
    })
    noms = vd.noms_organes(empoisonne)
    assert noms == ["Immunitaire (firewall/garde)"]


def test_4_schema_ANTERIEUR_encore_lisible():
    """Sans `tally`, les organes se deduisent des modules — pas de repli aveugle."""
    ancien = {"module_organ": {
        "a.py": {"organ": "Memoire (hippocampe/RAG)"},
        "b.py": {"organ": "Observabilite/Trace"},
        "c.py": {"organ": "Memoire (hippocampe/RAG)"},
    }}
    assert vd.noms_organes(ancien) == ["Memoire (hippocampe/RAG)", "Observabilite/Trace"]


@pytest.mark.parametrize("data", [None, [], "", 42, {}, {"tally": {}},
                                  {"tally": "pas un dict"}])
def test_5_un_census_inexploitable_rend_une_liste_VIDE(data):
    """Vide, pour que `_organs()` puisse basculer sur la liste stable en le SACHANT."""
    assert vd.noms_organes(data) == []


def test_6_organs_bascule_sur_le_repli_quand_le_census_est_illisible(tmp_path,
                                                                     monkeypatch):
    monkeypatch.setattr(vd, "ORGAN_MAP", tmp_path / "absent.json")
    rendu = vd._organs()
    assert rendu == ", ".join(vd._FALLBACK_ORGANS)
    assert len(rendu) < 700


def test_7_le_PROMPT_construit_reste_raisonnable(tmp_path, monkeypatch):
    """Mesure de bout en bout : 72 752 chars avant, ~1 600 apres, 3 documents."""
    import json as _j
    p = tmp_path / "organ_map_full.json"
    p.write_text(_j.dumps(_census()), encoding="utf-8")
    monkeypatch.setattr(vd, "ORGAN_MAP", p)
    monkeypatch.setattr(vd, "_roadmap", lambda: "x" * 600)
    docs = "\n".join("- titre %d — description" % i for i in range(3))
    prompt = vd._PROMPT.format(organs=vd._organs(), roadmap=vd._roadmap(), docs=docs)
    assert len(prompt) < 4000, "prompt de %d chars : le decor est revenu" % len(prompt)
    assert "module_organ" not in prompt
    assert "forge_000.py" not in prompt


# ── CORRECTION 2 : le pont local ────────────────────────────────────────────

def test_8_cfg_ne_leve_plus_NameError(monkeypatch):
    """`get_secret` est une dependance de MODULE, pas de fonction."""
    monkeypatch.setattr(fl, "get_secret", lambda _c: None)
    cfg = fl._cfg()
    assert isinstance(cfg, dict)
    assert cfg["max_tokens"] == 2048, "le defaut doit s'appliquer, pas exploser"


def test_9_cfg_lit_bien_le_coffre_quand_il_repond(monkeypatch):
    monkeypatch.setattr(fl, "get_secret",
                        lambda c: "512" if c == "LLAMACPP_MAX_TOKENS" else None)
    assert fl._cfg()["max_tokens"] == 512


def test_10_la_cle_serveur_ne_leve_plus_UnboundLocalError(monkeypatch):
    """Un import LOCAL place apres l'usage rend le nom local a toute la fonction :
    la ligne d'avant levait `UnboundLocalError`, pas `NameError`. Meme panne,
    autre nom — et invisible a une simple relecture."""
    monkeypatch.setattr(fl, "get_secret", lambda _c: None)
    assert fl._server_api_key() == ""
    monkeypatch.setattr(fl, "get_secret",
                        lambda c: "K1" if c == "FORGE_LLAMA_KEY" else None)
    assert fl._server_api_key() == "K1"
    monkeypatch.setattr(fl, "get_secret",
                        lambda c: "K2" if c == "LLAMACPP_API_KEY" else None)
    assert fl._server_api_key() == "K2", "le repli de compatibilite doit survivre"


def test_11_get_secret_est_resolvable_au_niveau_du_MODULE():
    """La preuve qui manquait : le symbole existe dans l'espace de noms du module.

    Un test qui n'appellerait que les fonctions ne distinguerait pas « importe »
    de « injecte par le test ».
    """
    assert callable(getattr(fl, "get_secret", None))


def test_12_la_cle_serveur_n_a_plus_d_import_local_qui_masque():
    """Garde de forme : reintroduire l'import local recreerait l'UnboundLocalError."""
    import inspect
    src = inspect.getsource(fl._server_api_key)
    assert "import get_secret" not in src, "l'import local est revenu"
