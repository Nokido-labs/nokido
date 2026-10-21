"""NR -- ingestion du manuel OpenStax Anatomy and Physiology 2e, en PRIVE, cite au chapitre et a la section (20/10).

Decision owner du 20/10 (« la veille physiologie toujours pas ingeree ») : ingerer OpenStax en prive (licence MESUREE
CC BY-NC-SA 4.0 sur le LICENSE du depot et sur la collection : jamais dans le pack public) ; la connaissance du corps
doit nourrir celle du code, citee au chapitre ou a la section. On ETEND tools/forge_ingest_github_repo.py (la route
d'ingestion GitHub existante, sans Docker) plutot que d'en ecrire une seconde. Trois limites mesurees de l'outil :
il lit tout le tarball EN MEMOIRE (depot de 509 Mo, RAM a 80 %), il ne garde pas le CNXML (XML de section), et la
citation n'atteint que le premier fragment d'un fichier.

Ce qui est garde : la collection rattache chaque section a son unite et son chapitre ; le CNXML devient un texte propre
(titres, paragraphes, legendes ; ni balise ni media) ; seuls les modules et la collection sont gardes ; chaque fragment
porte la citation et la licence ; le tarball arrive EN FLUX (jamais un read() complet).
"""
from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]

COLLECTION = """<col:collection xmlns="http://cnx.rice.edu/collxml" xmlns:md="http://cnx.rice.edu/mdml" xmlns:col="http://cnx.rice.edu/collxml">
  <metadata xmlns:md="http://cnx.rice.edu/mdml"><md:title>Anatomy and Physiology 2e</md:title>
    <md:license url="http://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International</md:license>
  </metadata>
  <col:content>
    <col:module document="m46844"/>
    <col:subcollection><md:title>Levels of Organization</md:title><col:content>
      <col:subcollection><md:title>An Introduction to the Human Body</md:title><col:content>
        <col:module document="m45981"/><col:module document="m45983"/>
      </col:content></col:subcollection>
    </col:content></col:subcollection>
  </col:content>
</col:collection>"""

MODULE = """<document xmlns="http://cnx.rice.edu/cnxml" xmlns:md="http://cnx.rice.edu/mdml" id="m45983">
  <title>Homeostasis</title>
  <metadata xmlns:md="http://cnx.rice.edu/mdml"><md:title>Homeostasis</md:title></metadata>
  <content>
    <para id="p1">Maintaining <term>homeostasis</term> requires that the body continuously monitors its internal conditions.</para>
    <section id="s1"><title>Negative Feedback</title>
      <para id="p2">A negative feedback system has three basic components: a sensor, a control center and an effector.</para>
    </section>
    <figure id="f1"><media id="md1" alt="boucle"><image mime-type="image/jpeg" src="../../media/fig_1_5.jpg"/></media>
      <caption>Negative feedback loop of body temperature.</caption></figure>
  </content>
</document>"""


def _module():
    spec = importlib.util.spec_from_file_location("ingest_openstax_nr", RACINE / "tools" / "forge_ingest_github_repo.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_collection_rattache_chaque_section_a_son_unite_et_son_chapitre():
    cit, licence = _module().citations_collection(COLLECTION)
    assert cit["m45983"] == "Levels of Organization > An Introduction to the Human Body"
    assert cit["m46844"] == ""
    assert "NonCommercial" in licence


def test_le_cnxml_devient_un_texte_propre():
    titre, texte = _module().cnxml_vers_texte(MODULE)
    assert titre == "Homeostasis"
    assert "Maintaining homeostasis requires that the body continuously monitors" in texte
    assert "Negative Feedback" in texte and "a sensor, a control center and an effector" in texte
    assert "Negative feedback loop of body temperature." in texte
    assert "<" not in texte and "fig_1_5.jpg" not in texte


@pytest.mark.parametrize("nom, garde", [("modules/m45983/index.cnxml", True),
                                         ("collections/anatomy-and-physiology-2e.collection.xml", True),
                                         ("media/fig_1_5.jpg", False), ("modules/m45983/fig.png", False),
                                         ("README.md", False)])
def test_seuls_les_modules_et_la_collection_sont_gardes(nom, garde):
    assert _module()._garder_openstax(nom) is garde


def test_chaque_fragment_porte_la_citation_et_la_licence():
    m = _module()
    prepares = m.preparer_openstax([("collections/a.collection.xml", COLLECTION),
                                    ("modules/m45983/index.cnxml", MODULE)])
    assert len(prepares) == 1
    interne, texte, entete = prepares[0]
    assert interne == "modules/m45983/index.cnxml"
    assert "An Introduction to the Human Body" in entete and "Homeostasis" in entete and "BY-NC-SA" in entete
    long_texte = texte * 40
    lignes = m.lignes_a_indexer([(interne, long_texte, entete)], "openstax/osbooks-anatomy-physiology")
    assert len(lignes) > 1, "le texte doit produire plusieurs fragments pour que le test ait un sens"
    assert all(chunk.startswith(entete) for _cid, _src, chunk in lignes)


def test_le_tarball_arrive_en_flux_jamais_d_un_bloc(monkeypatch, tmp_path):
    m = _module()
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w:gz") as tar:
        for nom, contenu in (("osbooks-main/collections/a.collection.xml", COLLECTION),
                             ("osbooks-main/modules/m45983/index.cnxml", MODULE),
                             ("osbooks-main/media/fig.jpg", "binaire")):
            data = contenu.encode("utf-8")
            info = tarfile.TarInfo(nom)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    octets = tampon.getvalue()

    class Reponse(io.BytesIO):
        def read(self, n=-1):
            assert n is not None and n > 0, "lecture d'un bloc interdite : le depot fait 509 Mo"
            return super().read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda url, timeout=120: Reponse(octets))
    fichiers, rapport = m.fetch("openstax", "osbooks-anatomy-physiology", "main", openstax=True, tmpdir=tmp_path)
    assert sorted(f[0] for f in fichiers) == ["collections/a.collection.xml", "modules/m45983/index.cnxml"]
    assert rapport["ecartes"]["extension_ou_dossier"] == 1
