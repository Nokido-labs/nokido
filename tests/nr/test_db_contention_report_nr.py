# -*- coding: utf-8 -*-
"""NR — le rapport de contention voit un ALIAS, et ne ment pas sur sa portee.

Le cliquet de couverture a exige ce test, et il avait raison : `forge_db_contention_report`
est arrive sans NR verifiant son EFFET. Un test d'import n'aurait rien prouve --
c'est precisement un rapport, son effet EST son contenu.

DEUX DEFAUTS ONT ETE PAYES PAR CET INSTRUMENT LE JOUR DE SA NAISSANCE (2026-09-18),
et chacun a son test ici :

1. il affichait `wal_autocheckpoint` comme une propriete de la BASE, alors que ce
   PRAGMA est PAR CONNEXION : il rapportait le defaut de sa propre sonde, ce qui
   se lit comme une politique du systeme ;
2. il a annonce « CONTENTION : rag, access_switches » parce que le compte qui
   l'executait n'avait pas `LAFORGE_SWITCHES_DB_PATH` -- or `services.toml` la
   pose pour le SERVICE. Il decrivait son propre bac en le prenant pour le systeme.

Sa RAISON D'ETRE est de voir ce qu'une comparaison de chemins ne voit pas : deux
noms differents pour un seul fichier. C'est le premier test ci-dessous, et il
porte sa morsure -- un instrument qui ne verrait plus l'alias rendrait « aucune
contention » avec la meme assurance.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/db : l'instrument de contention voit un alias et borne sa portee"

import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools.forge_db_contention_report import (  # noqa: E402
    _etat_base, _environnement, _generifier, _identite, rapport,
)


def test_l_EFFET_central_deux_chemins_un_fichier_sont_groupes(tmp_path):
    """LA raison d'etre : `samefile` la ou une comparaison de chaines echoue.

    L'alias est fabrique par une TRAVERSEE (`sous/../base.db`), qui survit a
    `str()`. Un premier jet utilisait `tmp / "." / "base.db"` -- et `pathlib`
    COLLAPSE le point : les deux chaines etaient identiques, le temoin ne
    prouvait rien. C'est le test d'auto-verification qui l'a dit, pas moi.
    """
    f = tmp_path / "base.db"
    f.write_bytes(b"x")
    (tmp_path / "sous").mkdir()
    alias = tmp_path / "sous" / ".." / "base.db"
    assert str(f) != str(alias), "les deux chemins doivent differer EN TEXTE"
    assert os.path.normcase(str(f)) != os.path.normcase(str(alias)), (
        "meme une comparaison normalisee doit les croire differents -- c'est tout "
        "l'interet de la mesure par inode"
    )
    r = _identite({"a": str(f), "b": str(alias)})
    partages = r["PARTAGENT_LE_MEME_FICHIER"]
    assert partages, "l'alias n'est pas vu : l'instrument rendrait « aucune contention »"
    assert sorted(next(iter(partages.values()))) == ["a", "b"]
    assert "PARTAGE" in r["verdict"]


def test_l_alias_par_la_CASSE_est_vu_aussi(tmp_path):
    """Sur un systeme de fichiers insensible a la casse, `BASE.db` et `base.db`
    sont UN fichier. Piege deja paye ici le 2026-09-06 (`app/Nokido.py` lu a la
    place de `tools/nokido.py`)."""
    f = tmp_path / "base.db"
    f.write_bytes(b"x")
    autre = tmp_path / "BASE.db"
    if not os.path.exists(autre):
        import pytest

        pytest.skip("systeme de fichiers SENSIBLE a la casse : pas d'alias ici")
    r = _identite({"minuscule": str(f), "majuscule": str(autre)})
    assert r["PARTAGENT_LE_MEME_FICHIER"], "l'alias de casse n'est pas vu"


def test_morsure_deux_fichiers_DISTINCTS_ne_sont_pas_groupes(tmp_path):
    """CONTROLE NEGATIF — sans lui, un instrument qui groupe TOUT passerait le
    test precedent en ne prouvant rien."""
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    r = _identite({"a": str(a), "b": str(b)})
    assert not r["PARTAGENT_LE_MEME_FICHIER"], "deux fichiers distincts ont ete groupes"
    assert "aucune" in r["verdict"]


def test_un_chemin_illisible_est_NOMME_pas_ignore(tmp_path):
    """Un chemin qu'on n'a pas pu lire ne doit pas disparaitre du rapport :
    il se lirait comme « rien a signaler »."""
    r = _identite({"fantome": str(tmp_path / "jamais_creee.db")})
    assert r["non_mesurables"], "un chemin absent a ete avale en silence"
    assert r["non_mesurables"][0]["nom"] == "fantome"
    assert r["non_mesurables"][0]["raison"]


def test_les_pragmas_de_la_sonde_ne_sont_PAS_presentes_comme_ceux_de_la_base(tmp_path):
    """Defaut n°1, celui qui a menti sur `wal_autocheckpoint`."""
    import sqlite3

    f = tmp_path / "p.db"
    sqlite3.connect(str(f)).close()
    d = _etat_base(str(f))
    assert "pragmas_persistants" in d and "pragmas_de_ma_sonde" in d, (
        "les deux familles de PRAGMA sont confondues"
    )
    assert "journal_mode" in d["pragmas_persistants"]
    assert "wal_autocheckpoint" in d["pragmas_de_ma_sonde"], (
        "un reglage PAR CONNEXION est range du cote des proprietes de la base"
    )
    assert "wal_autocheckpoint" not in d["pragmas_persistants"]
    assert "connexion" in d["_avertissement_pragmas"].lower()


def test_une_base_absente_est_ABSENTE_et_le_DIT_au_lieu_de_valoir_zero(tmp_path):
    d = _etat_base(str(tmp_path / "pas_la.db"))
    assert d["existe"] is False
    assert "note" in d and "pas un zero" in d["note"].lower()
    assert "taille_Mo" not in d, "une taille inventee pour une base absente"


def test_l_environnement_de_la_mesure_est_NOMME(monkeypatch):
    """Defaut n°2 : un verdict tire d'un bac ne vaut pas pour le systeme."""
    monkeypatch.delenv("LAFORGE_SWITCHES_DB_PATH", raising=False)
    e = _environnement()
    assert e["compte"], "l'observateur ne se nomme pas"
    assert e["variables_de_chemin_posees"]["LAFORGE_SWITCHES_DB_PATH"] is False
    assert "services.toml" in e["AVERTISSEMENT"], (
        "le rapport ne renvoie pas a la configuration des SERVICES : un verdict "
        "local se lirait comme un verdict systeme"
    )


def test_morsure_quand_TOUT_est_pose_l_avertissement_change(monkeypatch, tmp_path):
    """CONTROLE NEGATIF — l'avertissement ne doit pas etre un texte constant."""
    for v in ("LAFORGE_DB", "LAFORGE_M2M_DB_PATH", "LAFORGE_TASKS_DB_PATH",
              "LAFORGE_SWITCHES_DB_PATH"):
        monkeypatch.setenv(v, str(tmp_path / (v + ".db")))
    e = _environnement()
    assert "services.toml" not in e["AVERTISSEMENT"], (
        "l'avertissement est constant : il crierait meme quand tout est pose"
    )
    assert all(e["variables_de_chemin_posees"].values())


def test_aucun_chemin_de_profil_utilisateur_dans_le_rapport_complet():
    """Un rapport est fait pour etre PARTAGE : il ne publie pas le profil owner."""
    texte = json.dumps(rapport(), default=str)
    maison = str(Path.home())
    for forme in (maison, maison.replace("\\", "/"), maison.replace("\\", "\\\\")):
        assert forme not in texte, f"chemin de profil publie : {forme}"
    assert "<NOKIDO>" in texte or "<HOME>" in texte, (
        "aucun jeton de generification : la substitution ne s'applique pas"
    )


def test_morsure_la_generification_agit_vraiment():
    """CONTROLE NEGATIF du precedent — si `_generifier` rendait son entree telle
    quelle, le test ci-dessus pourrait passer par hasard."""
    brut = str(RACINE / "sandbox" / "x.db")
    assert _generifier(brut).startswith("<NOKIDO>")
    assert str(RACINE) not in _generifier(brut)


def test_le_rapport_complet_porte_ses_non_mesures():
    r = rapport()
    assert r["non_mesure"], "aucune limite declaree : un observateur en a toujours"
    assert any("INCONNU" in n or "pas zero" in n for n in r["non_mesure"])
    assert "environnement" in r and "identite_physique" in r and "bases" in r


def test_le_rapport_est_serialisable_sans_perte():
    """Il part vers un tiers : s'il ne se serialise pas, il n'existe pas."""
    json.loads(json.dumps(rapport(), default=str))
