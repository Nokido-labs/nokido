"""NR — une generation DIFFEREE doit quand meme etre REINJECTABLE.

Mesure du 2026-09-20 :

    docs/generations/                12 generations, la derniere a 11,2 jours
    sandbox/generations_en_attente/  28 generations, la derniere a 5 HEURES
    oplog.jsonl                      N'EXISTE NULLE PART

30 generations produites, ZERO entree d'op-log. Le gain de chacune est pourtant
CALCULE (`_gain_vs_precedente(_empr)`) juste avant d'etre jete.

CAUSE, lue dans `capturer()` : le chemin ACL (`except OSError`) depose la mesure
dans le dossier d'attente puis fait `return gen` -- ce retour anticipe SAUTE le
bloc `if _gain is not None: _append_oplog(...)` place plus bas. Or ce chemin ACL
n'est pas l'exception : c'est celui qui s'execute A CHAQUE FOIS, `docs/` n'etant
pas inscriptible par le compte de la CI (mesure du 2026-09-07). Le bloc de
reinjection vit donc sur la branche MORTE -- le motif paye toute la journee.

Second defaut du meme chemin : `gen["inscription_differee"] = {...}` est pose
APRES que `_brut = json.dumps(gen)` ait ete calcule. Le fichier depose ne porte
donc AUCUNE trace du differe : l'appelant l'apprend, le disque non. Une capture
differee et une capture ordinaire sont indistinguables sur artefact.

Ce que ce NR garde, et rien de plus : la mesure differee reste REINJECTABLE et
se DECLARE comme differee. Il n'exige aucun emplacement precis pour l'op-log --
l'ACL peut changer, le contrat non.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.71)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

fg = pytest.importorskip("app.forge_generation")


@pytest.fixture()
def acl_refuse(monkeypatch, tmp_path):
    """Reproduit l'ACL REELLE : le dossier cible refuse l'ecriture, l'attente non.

    On ne simule pas par une ABSENCE -- un dossier manquant se cree tout seul et
    le test passerait sans rien prouver (faute commise le 2026-09-20 au matin sur
    un autre NR). C'est l'ECRITURE qui doit lever, comme le fait une ACL.
    """
    cible = tmp_path / "docs_generations"
    attente = tmp_path / "attente"
    cible.mkdir()
    monkeypatch.setattr(fg, "DOSSIER", cible, raising=False)
    monkeypatch.setattr(fg, "DOSSIER_ATTENTE", attente, raising=False)
    monkeypatch.setattr(fg, "DOSSIER_SEQUENCE", attente, raising=False)

    vrai_write = Path.write_text

    def _refuse(self, *a, **k):
        if self.parent == cible and self.suffix == ".json":
            raise PermissionError(13, "Permission denied", str(self))
        return vrai_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", _refuse)
    return cible, attente


def _capturer(**kw):
    return fg.capturer(tests={"suite_temoin": "PASS"}, agent="NR", **kw)


def test_la_mesure_differee_est_bien_deposee(acl_refuse):
    """Garde-fou du garde-fou : sans cela les deux autres ne prouveraient rien."""
    cible, attente = acl_refuse
    gen = _capturer(note="nr differe")
    assert gen["statut"] == "STABLE", gen.get("statut_raison")
    deposes = list(attente.glob("GEN-*.json"))
    assert deposes, "la mesure n'a pas ete deposee dans le dossier d'attente"
    assert not list(cible.glob("GEN-*.json")), "elle n'aurait pas du passer l'ACL"


def test_le_fichier_depose_DIT_qu_il_est_differe(acl_refuse):
    """`inscription_differee` doit etre DANS le fichier, pas seulement rendu.

    Sinon une capture differee et une capture ordinaire sont indistinguables sur
    artefact, et personne ne peut savoir qu'une inscription reste a faire.
    """
    _cible, attente = acl_refuse
    gen = _capturer(note="nr differe")
    assert "inscription_differee" in gen, "l'appelant n'est meme pas informe"
    depose = json.loads(list(attente.glob("GEN-*.json"))[0].read_text(encoding="utf-8"))
    assert "inscription_differee" in depose, (
        "le fichier depose ne porte pas la trace du differe : `gen[...]` est mute "
        "APRES `json.dumps(gen)`, donc le disque ne l'a jamais vu."
    )
    assert depose["inscription_differee"].get("cible"), "la cible manquee n'est pas nommee"


def test_le_gain_calcule_n_est_pas_JETE(acl_refuse):
    """Le gain est calcule juste avant le refus d'ecriture -- il doit SURVIVRE.

    PREMIERE VERSION DE CE TEST, FAUSSE, gardee ici parce qu'elle a servi : elle
    exigeait une entree d'OP-LOG. Un NR anterieur l'a refusee, et il avait raison --
    `test_l_acl_differe_l_inscription_et_ne_perd_pas_la_mesure` arrete que
    « l'oplog ne consigne pas un gain qui n'a pas ete inscrit ». Ce journal ne
    porte que des victoires INSCRITES ; une capture differee n'en est pas une.

    Le contrat juste n'est donc pas « ecrire dans l'op-log » mais « ne pas PERDRE
    la mesure ». Le gain voyage avec elle, dans le fichier depose, pour qu'une
    inscription ulterieure n'ait pas a le recalculer sur un etat qui aura change.
    """
    _cible, attente = acl_refuse
    gen = _capturer(note="nr differe")
    depose = json.loads(list(attente.glob("GEN-*.json"))[0].read_text(encoding="utf-8"))
    differe = depose.get("inscription_differee") or {}
    assert "gain" in differe, (
        "le gain a ete calcule (`_gain_vs_precedente`) puis JETE : le bloc qui le "
        "consigne vit apres le `return` du chemin nominal, hors de portee ici."
    )
    assert "empreinte" in differe, "l'empreinte qui a servi a le calculer manque"
    # et l'op-log reste VIERGE : l'invariant anterieur tient.
    assert not list(attente.rglob("oplog.jsonl")), (
        "l'op-log ne doit PAS consigner une generation non inscrite"
    )
