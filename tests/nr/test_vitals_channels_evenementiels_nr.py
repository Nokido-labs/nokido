"""Non-regression : les canaux EVENEMENTIELS de la serie vitals.

CE QUE CES TESTS PROTEGENT
==========================
Un capteur qui rend 0 quand il ne SAIT pas fabrique un faux negatif indetectable :
« zero evenement » se lit « tout va bien », et rien dans la serie ne dit que le
capteur etait aveugle. Le module entier est bati sur cette regle -- trois etats,
jamais deux -- et c'est elle que ces tests gardent.

Le second risque est le pic fantome : un flux append-only qui tourne ou se
tronque ferait compter des milliers d'evenements d'un coup si la reference
n'etait pas remise a zero.

Tests PURS : fichiers temporaires uniquement, aucun service, aucun journal
systeme, aucune base.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

vc = pytest.importorskip("forge_vitals_channels")


def _ecrire(p: Path, lignes: list[dict], mode: str = "a") -> None:
    with io.open(p, mode, encoding="utf-8") as fh:
        for d in lignes:
            fh.write(json.dumps(d) + "\n")


def test_premiere_lecture_rend_INCONNU_et_pas_zero(tmp_path):
    """Un debit sans reference est INCONNU. Rendre 0 ferait croire au silence."""
    f = tmp_path / "flux.jsonl"
    _ecrire(f, [{"kind": "msg"}], "w")
    lignes, dt, note = vc._lire_ajouts({}, "t", f)
    assert lignes is None, "la premiere lecture doit rendre None, jamais une liste"
    assert note, "un refus sans raison est indistinguable d'une panne"


def test_les_lignes_ajoutees_sont_lues_et_datees(tmp_path):
    f = tmp_path / "flux.jsonl"
    _ecrire(f, [], "w")
    prev: dict = {}
    vc._lire_ajouts(prev, "t", f)
    time.sleep(0.05)
    _ecrire(f, [{"kind": "error"}, {"kind": "tool_call"}, {"kind": "error"}])
    lignes, dt, _ = vc._lire_ajouts(prev, "t", f)
    assert len(lignes) == 3
    assert dt > 0
    assert sum(1 for d in lignes if d["kind"] == "error") == 2


def test_rien_d_ecrit_rend_une_liste_VIDE_pas_inconnu(tmp_path):
    """Silence mesure et ignorance sont deux faits differents : [] contre None."""
    f = tmp_path / "flux.jsonl"
    _ecrire(f, [{"kind": "msg"}], "w")
    prev: dict = {}
    vc._lire_ajouts(prev, "t", f)
    time.sleep(0.05)
    lignes, dt, _ = vc._lire_ajouts(prev, "t", f)
    assert lignes == [], "rien d'ecrit doit rendre [], pas None"
    assert dt > 0


def test_un_flux_tronque_ne_produit_PAS_de_pic_fantome(tmp_path):
    """Sans cette garde, une rotation ferait compter tout le fichier d'un coup."""
    f = tmp_path / "flux.jsonl"
    _ecrire(f, [{"kind": "msg"} for _ in range(50)], "w")
    prev: dict = {}
    vc._lire_ajouts(prev, "t", f)
    time.sleep(0.05)
    _ecrire(f, [{"kind": "msg"}], "w")          # rotation : le fichier RETRECIT
    lignes, _dt, note = vc._lire_ajouts(prev, "t", f)
    assert lignes is None
    assert "tronque" in note or "tourne" in note


def test_un_flux_absent_est_dit_ILLISIBLE(tmp_path):
    lignes, _dt, note = vc._lire_ajouts({}, "t", tmp_path / "jamais_ecrit.jsonl")
    assert lignes is None
    assert note


def test_le_groupe_bus_ne_rend_aucun_canal_avant_d_avoir_une_reference():
    """Un groupe en echec doit sortir de la serie, pas y injecter des zeros."""
    vals, note = vc.grp_bus({})
    assert vals == {}, "aucun canal tant que le debit est inconnu"
    assert note


def test_le_cycle_de_vie_ne_publie_QUE_le_domaine_gate():
    """Garde ANTI-FUITE. Les actions dominantes du flux (`rss_derive_detected`,
    `evict_detresse`, `snn_spike`) sont des reactions a une RAM basse, or
    l'etiquette de detresse est justement `ram_free_gb` sous un seuil. Les publier
    apprendrait « le regulateur a reagi » au lieu de « la detresse arrive ».
    Si ce test tombe, quelqu'un a elargi le groupe : verifier la fuite AVANT."""
    assert set(k for k in vc.SCHEMA if k.startswith("lc")) == {"lcg"}


def test_l_innervation_se_lit_dans_le_REGISTRE_pas_dans_les_noms():
    """Erreur payee DEUX fois. Le 24-07 : apparier `<service>.heartbeat` par
    convention de nom attribuait a `NokidoWebHub` — qui ne declare AUCUN heartbeat —
    un residu de 20,6 jours, rapporte « capteur gele ». Le 23-08 : la premiere
    version du groupe `organes` a reproduit exactement cela et comptait 22 services
    « denerves » qui ne declarent simplement pas d'afference.

    La source qui fait foi est `services.toml`, champ `heartbeat`."""
    declares = vc._heartbeats_declares()
    assert declares, "registre vide = on ne peut RIEN conclure sur l'innervation"
    for service, chemin in declares.items():
        assert chemin.endswith(".heartbeat"), "%s declare %r" % (service, chemin)
    assert "NokidoWebHub" not in declares, (
        "NokidoWebHub ne declare aucun heartbeat (mesure 24-07) ; s'il apparait ici, "
        "quelqu'un est revenu a l'appariement par nom")


def test_un_organe_sans_afference_declaree_n_est_PAS_une_panne():
    """Distinction physiologique : ne declarer aucune afference, c'est un tissu non
    innerve PAR CONCEPTION — un binaire tiers, une prothese. Declarer une afference
    et se taire, c'est un nerf SECTIONNE. Seul le second est une pathologie, et seul
    le second doit entrer dans `ords`."""
    declares = vc._heartbeats_declares()
    vals, note = vc.grp_organes({})
    if not vals:
        pytest.skip("superviseur injoignable : on ne conclut pas (%s)" % note)
    assert vals["ords"] <= len(declares), (
        "on ne peut pas compter plus d'afferences muettes qu'il n'en est declare — "
        "signe d'un retour a l'appariement par nom")


def test_le_schema_documente_chaque_canal_evenementiel():
    """Une cle courte sans entree de schema est illisible six mois plus tard."""
    for cle in ("hth", "hhd", "hfd", "hrs", "hcp", "ln", "lp95", "lmax",
                "lerr", "lbi", "lbo", "bev", "berr", "bag", "lcg", "wse", "wae"):
        assert cle in vc.SCHEMA, "canal non documente dans SCHEMA : %s" % cle
