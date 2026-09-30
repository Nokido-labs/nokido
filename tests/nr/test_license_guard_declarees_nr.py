"""NR — le garde de licences juge les dependances DECLAREES, et ne se trompe plus de metadonnee.

Mesure du 2026-09-29 (question owner : « tu es sur d'avoir couvert toutes les licences ? ») :
- le mode par defaut juge l'environnement INSTALLE : 0 incompatible sur l'env de CI, 13 sur
  l'interpreteur runtime ; une dependance optionnelle GPL-2.0-only (scapy) etait importee sans
  que la CI l'ait jamais vue ;
- un classifieur « Other/Proprietary » FABRIQUE par Poetry ecrasait la licence ecrite par
  l'auteur : androguard, archspec, fastembed (Apache/MIT) refuses a tort ;
- GPLv3 et GPLv2-ou-ulterieure sortaient « inconnu » alors que compatibles AGPLv3 ;
- une premiere mesure a compte `# scapy>=2.5.0` (ligne COMMENTEE) comme declaree.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_license_guard as G  # noqa: E402


class _Meta:
    def __init__(self, champs):
        self._c = champs

    def get(self, cle, defaut=None):
        v = self._c.get(cle, defaut)
        return v[0] if isinstance(v, list) and v else v

    def get_all(self, cle, defaut=None):
        v = self._c.get(cle)
        return v if isinstance(v, list) else ([v] if v else defaut)


class _Dist:
    def __init__(self, nom, version="1.0", **champs):
        champs.setdefault("Name", nom)
        self.metadata = _Meta(champs)
        self.version = version


def test_une_ligne_commentee_n_est_pas_une_declaration(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n# scapy>=2.5.0\n  # autre\n-r base.txt\n",
                                               encoding="utf-8")
    decl = G.dependances_declarees(tmp_path)
    assert "requests" in decl and "scapy" not in decl


def test_pyproject_dependances_et_extras_sont_lus(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["httpx>=0.27", "Foo_Bar[extra]>=1"]\n'
        '[project.optional-dependencies]\nml = ["torch>=2"]\n', encoding="utf-8")
    decl = G.dependances_declarees(tmp_path)
    assert decl["httpx"] == ["pyproject.toml"]
    assert "foo-bar" in decl, "nom non normalise (PEP 503)"
    assert decl["torch"] == ["pyproject.toml[ml]"]


def test_un_classifieur_proprietaire_fabrique_cede_a_la_licence_ecrite():
    d = _Dist("androguard", License="Apache Licence, Version 2.0",
              Classifier=["License :: Other/Proprietary License"])
    assert G.classify("androguard", G._license_text(d)) == "ok"


def test_un_classifieur_generique_cede_a_la_licence_ecrite():
    """asyncssh : « EPL-2.0 OR GPL-2.0-or-later » derriere un simple « OSI Approved »."""
    d = _Dist("asyncssh", License="EPL-2.0 OR GPL-2.0-or-later", Classifier=["License :: OSI Approved"])
    assert G.classify("asyncssh", G._license_text(d)) == "ok"


def test_metadonnees_vides_le_fichier_de_licence_livre_nomme_la_licence(tmp_path):
    """mistralai 2.3.2 : ni champ ni classifieur, un LICENSE Apache-2.0 dans son dist-info."""
    lic = tmp_path / "LICENSE"
    lic.write_text("\n                 Apache License\n           Version 2.0, January 2004\n", encoding="utf-8")

    class _F:
        def __str__(self):
            return "mistralai-2.3.2.dist-info/licenses/LICENSE"

        def locate(self):
            return lic

    d = _Dist("mistralai")
    d.files = [_F()]
    assert G.classify("mistralai", G._license_text(d)) == "ok"


def _dist_avec_fichier(tmp_path, nom, texte):
    lic = tmp_path / ("LICENSE_" + nom)
    lic.write_text(texte, encoding="utf-8")

    class _F:
        def __str__(self):
            return "%s-1.0.dist-info/licenses/LICENSE" % nom

        def locate(self):
            return lic

    d = _Dist(nom)
    d.files = [_F()]
    return d


def test_un_texte_bsd_all_rights_reserved_n_est_pas_un_refus(tmp_path):
    """Regression payee le 2026-09-29 : conda-package-handling et matplotlib-inline (BSD-3)
    refuses a cause de « All rights reserved » recopie depuis leur texte."""
    d = _dist_avec_fichier(tmp_path, "mpl-inline", "BSD 3-Clause License\n\nCopyright (c) 2019, X\n"
                           "All rights reserved.\n\nRedistribution and use in source and binary forms, ...\n")
    assert G.classify("mpl-inline", G._license_text(d)) == "ok"


def test_un_texte_gplv2_sans_metadonnee_reste_inconnu(tmp_path):
    """La GPLv2 porte toujours son annexe « any later version » : la version reelle n'est pas
    tranchable depuis le texte. Ni refuse ni accepte : INCONNU."""
    d = _dist_avec_fichier(tmp_path, "g2", "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n...\n"
                           "either version 2 of the License, or (at your option) any later version.\n")
    assert G.classify("g2", G._license_text(d)) == "unknown"


def test_un_texte_lgpl_qui_cite_la_gpl_reste_lgpl(tmp_path):
    d = _dist_avec_fichier(tmp_path, "l21", "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999\n"
                           "... the GNU General Public License ...\n")
    assert G.classify("l21", G._license_text(d)) == "ok"


def test_un_texte_non_reconnu_reste_inconnu(tmp_path):
    d = _dist_avec_fichier(tmp_path, "naist", "Copyright 2000 Nara Institute\nAll rights reserved.\nUse ...\n")
    assert G.classify("naist", G._license_text(d)) == "unknown"


def test_un_vrai_proprietaire_reste_refuse():
    d = _Dist("x", License="Proprietary", Classifier=["License :: Other/Proprietary License"])
    assert G.classify("x", G._license_text(d)) == "deny"
    d2 = _Dist("y", Classifier=["License :: Other/Proprietary License"])
    assert G.classify("y", G._license_text(d2)) == "deny"


def test_gplv3_et_gplv2_ou_ulterieure_sont_compatibles_gplv2_seule_non():
    assert G.classify("a", "gpl-3.0-or-later") == "ok"
    assert G.classify("b", "license :: osi approved :: gnu general public license v3 or later (gplv3+)") == "ok"
    assert G.classify("c", "gpl-2.0-or-later") == "ok"
    assert G.classify("d", "gpl-2.0-only") == "deny"
    assert G.classify("e", "license :: osi approved :: gnu general public license v2 (gplv2)") == "deny"


def test_une_declaree_incompatible_fait_echouer_et_une_absente_est_non_mesuree(tmp_path, monkeypatch, capsys):
    (tmp_path / "requirements.txt").write_text("mauvais-paquet\npaquet-absent-xyz\nbon\n", encoding="utf-8")
    monkeypatch.setattr(G.metadata, "distributions", lambda: [
        _Dist("mauvais-paquet", License="SSPL-1.0"), _Dist("bon", License="MIT")])
    assert G.verifier_declarees(tmp_path) == 1
    sortie = capsys.readouterr().out
    assert "DENY    mauvais-paquet" in sortie
    assert "NON MESURÉ paquet-absent-xyz" in sortie


def test_le_point_d_entree_declarees(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("bon\n", encoding="utf-8")
    monkeypatch.setattr(G, "ROOT", tmp_path)
    monkeypatch.setattr(G.metadata, "distributions", lambda: [_Dist("bon", License="MIT")])
    monkeypatch.setattr(sys, "argv", ["forge_license_guard.py", "--declarees"])
    assert G.main() == 0
