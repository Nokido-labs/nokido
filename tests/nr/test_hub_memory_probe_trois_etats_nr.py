"""NR — une sonde memoire qui ne peut pas voir le DIT, elle ne rend jamais zero.

`forge_hub_memory_probe` a ete ecrit le 2026-09-19 pour ventiler le RSS du hub
(2,7-3,1 Go) par ORIGINE. Sa raison d'etre tient a un invariant du depot :
`UNKNOWN != NO`. Sous le compte sandbox, `memory_maps` est refuse ; une sonde qui
rendrait alors des categories a 0,0 Go ferait lire "aucune memoire mappee" la ou
il faut lire "je n'ai pas pu regarder" -- exactement le defaut qui avait fait
declarer 331 process eteints et `deno lint` a 0 erreur.

Ces tests gardent le refus, pas le succes : le succes depend de privileges que la
CI n'a pas, le refus est le chemin que la CI emprunte VRAIMENT.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
psutil = pytest.importorskip("psutil")
fhmp = importlib.import_module("forge_hub_memory_probe")


def test_un_refus_rend_ILLISIBLE_avec_son_motif_jamais_des_zeros(monkeypatch):
    class Refus(PermissionError):
        pass

    def _boum(self, grouped=True):
        raise Refus("AccessDenied")

    monkeypatch.setattr(psutil.Process, "memory_maps", _boum, raising=True)

    out = fhmp.ventiler(__import__("os").getpid())

    assert out["ventilation"] is None, "ne rien voir n'est pas voir zero"
    assert "ventilation_go" not in out, "une ventilation vide se lirait comme une mesure"
    assert "illisible" in out and out["illisible"], "un refus muet est indetectable"


def test_le_motif_NOMME_l_exception_le_compte_et_la_sortie(monkeypatch):
    """Un refus qui ne dit pas COMMENT en sortir est une impasse."""
    def _boum(self, grouped=True):
        raise PermissionError("AccessDenied")

    monkeypatch.setattr(psutil.Process, "memory_maps", _boum, raising=True)
    motif = fhmp.ventiler(__import__("os").getpid())["illisible"]

    assert "PermissionError" in motif, "nommer CE qui a refuse"
    assert "trusted_script" in motif, "nommer la voie qui, elle, passe"
    assert "ABSENCE DE MESURE" in motif, "et interdire de le lire comme une absence de cause"


def test_le_compte_effectif_est_TOUJOURS_rendu(monkeypatch):
    """Sans le compte, un refus n'est pas attribuable : on ne sait pas qui relancer."""
    def _boum(self, grouped=True):
        raise PermissionError("AccessDenied")

    monkeypatch.setattr(psutil.Process, "memory_maps", _boum, raising=True)
    out = fhmp.ventiler(__import__("os").getpid())

    assert out["compte_effectif"], "le compte doit etre nomme meme quand tout echoue"
    assert out["compte_effectif"] in out["illisible"], "et figurer dans le motif"
    assert out["rss_go"] > 0, "le RSS, lui, reste lisible : ne pas tout jeter"


def test_les_categories_distinguent_ce_qui_doit_etre_distingue():
    """Une base mappee, une DLL et le tas anonyme n'ont pas la meme cause."""
    c = fhmp._categorie
    assert c("%NOKIDO_DATA%\embeddings.db") == c("x.db-wal") == c("y.sqlite")
    assert c("python3.dll") == c("_ssl.pyd")
    assert c(None) == c("") == c("[anon]")
    assert len({c("a.db"), c("b.dll"), c("c.exe"), c(None), c("d.txt")}) == 5, \
        "cinq origines distinctes, sinon la ventilation ne ventile rien"


def test_une_ventilation_reelle_ne_se_confond_pas_avec_un_refus():
    """Contre-epreuve : quand la lecture PASSE, la forme doit etre l'autre.

    Si `memory_maps` est refuse ici aussi (compte bride), on le DIT et on saute --
    on ne transforme pas un indetermine en echec (cf. le NR mTLS du 2026-09-19).
    """
    import os
    out = fhmp.ventiler(os.getpid())
    if out.get("illisible"):
        pytest.skip("memory_maps refuse sous ce compte : %s" % out["illisible"][:80])
    assert out["ventilation_go"], "une lecture qui passe doit produire des categories"
    assert sum(out["ventilation_go"].values()) > 0
    assert out["mappings"] > 0
    assert "illisible" not in out, "on ne rend pas les deux formes a la fois"
