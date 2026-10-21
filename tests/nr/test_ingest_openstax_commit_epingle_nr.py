"""NR -- OpenStax s'ingere a un COMMIT EPINGLE, et la citation suit la licence de CE commit (2026-10-20).

Mesure du 20/10 (deux observateurs) : openstax/osbooks-anatomy-physiology est passe en CC BY-NC-SA 4.0 le 19/03/2026
(commit fdfa6e21ac) ; a son parent b0058a743b, le fichier LICENSE dit « Attribution 4.0 International » et la
collection declare http://creativecommons.org/licenses/by/4.0/. Une licence CC est irrevocable pour la copie deja
distribuee : epingle a ce commit, le manuel est en CC BY 4.0, donc redistribuable avec attribution.
L'ingesteur ne savait telecharger qu'une BRANCHE (refs/heads/<ref>), et l'en-tete disait « jamais redistribue » quelle
que soit la licence.

Ce qui est garde : une reference de 40 hexadecimaux se telecharge comme un commit ; une branche reste une branche ;
l'en-tete d'une collection CC BY porte l'attribution et ne dit pas « jamais redistribue » ; celui d'une collection
NC-SA le dit.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
SHA = "b0058a743bdd2cc08196abaaa7d5469970c0d80c"
MODULE = ('<document xmlns="http://cnx.rice.edu/cnxml" id="m45983"><title>Homeostasis</title>'
          '<content><para id="p1">Homeostasis is the maintenance of a stable internal environment.</para></content></document>')


def _collection(url, libelle):
    return ('<col:collection xmlns:md="http://cnx.rice.edu/mdml" xmlns:col="http://cnx.rice.edu/collxml">'
            '<metadata><md:license url="%s">%s</md:license></metadata><col:content>'
            '<col:subcollection><md:title>Levels of Organization</md:title><col:content>'
            '<col:module document="m45983"/></col:content></col:subcollection></col:content></col:collection>'
            % (url, libelle))


def _module():
    spec = importlib.util.spec_from_file_location("ingest_openstax_epingle_nr", RACINE / "tools" / "forge_ingest_github_repo.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_un_sha_se_telecharge_comme_un_commit_une_branche_comme_une_branche():
    m = _module()
    assert m.url_tarball("openstax", "osbooks-anatomy-physiology", SHA) == (
        "https://codeload.github.com/openstax/osbooks-anatomy-physiology/tar.gz/" + SHA)
    assert m.url_tarball("openstax", "osbooks-anatomy-physiology", "main") == (
        "https://codeload.github.com/openstax/osbooks-anatomy-physiology/tar.gz/refs/heads/main")


def test_l_entete_suit_la_licence_de_la_collection():
    m = _module()
    by = m.preparer_openstax([("collections/a.collection.xml",
                               _collection("http://creativecommons.org/licenses/by/4.0/",
                                           "Creative Commons Attribution License")),
                              ("modules/m45983/index.cnxml", MODULE)])[0][2]
    assert "CC BY 4.0" in by and "Rice University" in by and "jamais redistribue" not in by
    nc = m.preparer_openstax([("collections/a.collection.xml",
                               _collection("http://creativecommons.org/licenses/by-nc-sa/4.0/",
                                           "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International")),
                              ("modules/m45983/index.cnxml", MODULE)])[0][2]
    assert "CC BY-NC-SA 4.0" in nc and "jamais redistribue" in nc
