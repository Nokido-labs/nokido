"""NR — ce qui entre en ATTENTE doit pouvoir en SORTIR.

Mesure du 2026-09-20 :

    sandbox/generations_en_attente/   28 generations, la plus recente a 5 h
    docs/generations/                 12 generations, la derniere a 11,2 jours
    CLI forge_generation              {capturer, lister, plan, comparer}
    DOSSIER_ATTENTE                   reference par forge_generation.py SEUL

Le mecanisme de differe a ete pose le 2026-09-07 pour ne PAS perdre la mesure
quand l'ACL refuse `docs/`. Son commentaire annonce la suite -- « l'INSCRIPTION
reste a faire par un chemin gouverne » -- et ce chemin n'a jamais ete ecrit. Le
dossier d'attente est donc un CUL-DE-SAC : 28 mesures y entrent, aucune n'en
sort. C'est `produit(n) != consomme(n+1)`, avec 11,2 jours d'ecart.

Ce NR garde le PENDANT manquant, pas un nouveau mecanisme :

  - une generation en attente est promue quand la cible est inscriptible ;
  - l'op-log est ecrit A CE MOMENT -- et seulement la. L'invariant anterieur
    (`l'oplog ne consigne pas un gain qui n'a pas ete inscrit`) est ainsi
    respecte : c'est precisement l'inscription qui vient d'avoir lieu ;
  - le gain PERSISTE dans le fichier (pose plus tot ce jour) est reutilise tel
    quel, jamais recalcule -- l'empreinte a change depuis, la recalculer
    falsifierait une mesure passee ;
  - une generation deja inscrite n'est JAMAIS ecrasee : une generation est
    immuable, et deux mesures differentes ne doivent pas porter le meme numero ;
  - si la cible refuse encore, la promotion ECHOUE en le DISANT et ne detruit
    rien.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

fg = pytest.importorskip("app.forge_generation")


def _gen(num: int, gain=None) -> dict:
    d = {
        "generation": "GEN-%05d" % num,
        "cree_le": "2026-09-20T00:00:00+00:00",
        "statut": "STABLE",
        "statut_raison": "toutes les suites fournies sont vertes",
        "agent": "NR",
        "note": "nr promotion",
        "depot": {"sha": "abc123def456", "branche": "alpha", "propre": True},
        "environnement": {"empreinte": {"modules_forge": 10, "tests_nr": 5},
                          "lock_sha256": "deadbeef"},
        "tests": {"suite_temoin": "PASS"},
        "capacites": {}, "metriques": {},
    }
    if gain is not None:
        d["inscription_differee"] = {"cible": "docs/generations/%s.json" % d["generation"],
                                     "depot": "attente", "motif": "PermissionError: 13",
                                     "errno": 13, "gain": gain,
                                     "empreinte": {"modules_forge": 10, "tests_nr": 5}}
    return d


@pytest.fixture()
def deux_dossiers(monkeypatch, tmp_path):
    cible = tmp_path / "generations"
    attente = tmp_path / "en_attente"
    cible.mkdir(); attente.mkdir()
    monkeypatch.setattr(fg, "DOSSIER", cible, raising=False)
    monkeypatch.setattr(fg, "DOSSIER_ATTENTE", attente, raising=False)
    monkeypatch.setattr(fg, "DOSSIER_SEQUENCE", cible, raising=False)
    return cible, attente


def test_le_verbe_de_promotion_existe():
    """Sans point d'entree, les 28 mesures restent inatteignables."""
    assert hasattr(fg, "promouvoir"), (
        "aucune fonction `promouvoir` : le dossier d'attente reste un cul-de-sac "
        "(28 generations mesurees le 2026-09-20, aucune sortie)."
    )


def test_une_attente_est_promue_et_l_oplog_ECRIT(deux_dossiers):
    """L'inscription VIENT D'AVOIR LIEU : c'est le seul moment ou l'op-log parle."""
    cible, attente = deux_dossiers
    g = _gen(42, gain={"vs": "GEN-00041", "modules_forge": 2, "tests_nr": 7})
    (attente / "GEN-00042.json").write_text(json.dumps(g), encoding="utf-8")

    r = fg.promouvoir()
    assert (cible / "GEN-00042.json").is_file(), "la generation n'a pas ete inscrite"
    assert r.get("promues") == ["GEN-00042"], f"compte-rendu inattendu : {r}"

    op = cible / "oplog.jsonl"
    assert op.is_file(), "l'op-log n'a pas ete ecrit alors que l'inscription a eu lieu"
    entrees = [json.loads(l) for l in op.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entrees and entrees[0]["generation"] == "GEN-00042"
    assert entrees[0]["gain"] == {"vs": "GEN-00041", "modules_forge": 2, "tests_nr": 7}, (
        "le gain PERSISTE doit etre repris tel quel, jamais recalcule : l'empreinte "
        "a change depuis, le recalculer falsifierait une mesure passee."
    )


def test_une_generation_deja_inscrite_n_est_PAS_ecrasee(deux_dossiers):
    """Une generation est IMMUABLE. Deux mesures ne partagent pas un numero."""
    cible, attente = deux_dossiers
    (cible / "GEN-00007.json").write_text(json.dumps({"generation": "GEN-00007",
                                                      "origine": "deja la"}), encoding="utf-8")
    (attente / "GEN-00007.json").write_text(json.dumps(_gen(7)), encoding="utf-8")

    r = fg.promouvoir()
    relu = json.loads((cible / "GEN-00007.json").read_text(encoding="utf-8"))
    assert relu.get("origine") == "deja la", "une generation inscrite a ete ECRASEE"
    assert "GEN-00007" not in (r.get("promues") or []), "elle ne doit pas compter comme promue"
    assert any("GEN-00007" in str(x) for x in (r.get("conflits") or [])), (
        "le conflit doit etre DIT, pas tu"
    )


def test_un_refus_d_ecriture_est_DIT_et_ne_detruit_rien(deux_dossiers, monkeypatch):
    """Si l'ACL refuse encore, la mesure reste en attente et l'echec se declare."""
    cible, attente = deux_dossiers
    (attente / "GEN-00050.json").write_text(json.dumps(_gen(50)), encoding="utf-8")
    vrai = Path.write_text

    def refuse(self, *a, **k):
        if self.parent == cible:
            raise PermissionError(13, "Permission denied", str(self))
        return vrai(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", refuse)
    r = fg.promouvoir()
    assert (attente / "GEN-00050.json").is_file(), "la mesure a ete DETRUITE sur un refus"
    assert not r.get("promues"), "rien n'a pu etre inscrit"
    assert r.get("refusees"), "un refus d'ecriture doit etre DIT"
