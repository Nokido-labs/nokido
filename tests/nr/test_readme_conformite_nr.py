# -*- coding: utf-8 -*-
"""NR -- owner 1/11 : « sur le readme tu parles de la version 14, mets en place un gate de verification absolument pour
respecter la conformite du readme en TOUS points ». Mesure : au tag v0.20.15, README.md ET ses 7 traductions
annoncaient `pip install ...==0.20.14` (page PyPI de 0.20.15 figee ainsi), et le bloc pip des traductions etait
reste en ANGLAIS (forge_readme_pip ne savait rendre qu'une langue).

Points controles par tools/forge_readme_conformite.py, sur README.md + docs/i18n/README.*.md :
  1. une seule version annoncee partout ; en release (--version X), c'est X ;
  2. le bloc pip est celui que SA langue genere (plus de bloc anglais dans une traduction) ;
  3. meme structure de titres que l'anglais ;
  4. tout lien relatif mene a un fichier existant (resolu depuis le fichier) ;
  5. aucune fuite (depot prive, CI auto-hebergee, ancien nom).
Le dernier test juge le DEPOT REEL : en suite pure, il bloque la CI au moindre ecart."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_readme_conformite as C  # noqa: E402
import forge_readme_pip as P  # noqa: E402


def _arbre(tmp_path, version="0.20.15", fr_bloc=None, extra_fr="", extra_en=""):
    (tmp_path / "docs" / "i18n").mkdir(parents=True)
    (tmp_path / "LICENSE").write_text("x", encoding="utf-8")
    en = "# Nokido\n\n## Quick start\n\n%s\n\n## License\n\n[l](LICENSE)\n%s" % (P.bloc(P.PAQUET, version), extra_en)
    fr = ("# Nokido\n\n## Demarrage\n\n%s\n\n## Licence\n\n[l](../../LICENSE)\n%s"
          % (fr_bloc or P.bloc(P.PAQUET, version, "fr"), extra_fr))
    (tmp_path / "README.md").write_text(en, encoding="utf-8")
    (tmp_path / "docs" / "i18n" / "README.fr.md").write_text(fr, encoding="utf-8")
    return tmp_path


def test_le_bloc_pip_se_rend_dans_chaque_langue():
    for langue in C.LANGUES:
        b = P.bloc(P.PAQUET, "0.20.15", langue)
        assert "pip install" in b and "0.20.15" in b
        if langue != "en":
            assert "published after the" not in b, langue
    assert P.bloc(P.PAQUET, "0.20.15", "en") == P.bloc(P.PAQUET, "0.20.15")   # anglais inchange a l'octet


def test_ecrire_pose_dans_chaque_fichier_le_bloc_de_sa_langue(tmp_path):
    _arbre(tmp_path, fr_bloc=P.bloc(P.PAQUET, "0.20.14"))          # bloc ANGLAIS 0.20.14 dans la traduction
    P.ecrire(tmp_path, P.PAQUET, "0.20.15")
    fr = (tmp_path / "docs" / "i18n" / "README.fr.md").read_text(encoding="utf-8")
    assert P.bloc(P.PAQUET, "0.20.15", "fr") in fr
    assert P.coherence(fr, P.PAQUET, "fr")[0] == P.ALIGNE


def test_arbre_conforme(tmp_path):
    assert C.verifier(_arbre(tmp_path)) == []


def test_point1_versions_divergentes_et_release(tmp_path):
    _arbre(tmp_path, fr_bloc=P.bloc(P.PAQUET, "0.20.14", "fr"))
    assert any(e.point == 1 for e in C.verifier(tmp_path))
    assert any(e.point == 1 for e in C.verifier(_arbre(tmp_path / "b"), version="0.20.16"))


def test_point2_bloc_anglais_dans_une_traduction(tmp_path):
    ecarts = C.verifier(_arbre(tmp_path, fr_bloc=P.bloc(P.PAQUET, "0.20.15")))
    assert any(e.point == 2 and e.fichier.endswith("README.fr.md") for e in ecarts)


def test_point3_structure_de_titres(tmp_path):
    assert any(e.point == 3 for e in C.verifier(_arbre(tmp_path, extra_en="\n## Extra\n")))


def test_point4_lien_mort(tmp_path):
    ecarts = C.verifier(_arbre(tmp_path, extra_fr="[x](../absent.md#ancre)\n", extra_en="[y](https://ok)\n"))
    assert [e.point for e in ecarts] == [4]


def test_point5_fuite(tmp_path):
    assert any(e.point == 5 for e in C.verifier(_arbre(tmp_path, extra_en="voir Nokido-labs/nokido-private\n")))


def test_point6_titre_non_traduit(tmp_path):
    """Mesure 1/11 : « # Project status » reste en anglais dans les README es et pt-BR. Un titre identique a l'anglais
    au meme rang est un oubli, sauf s'il ne porte que des mots invariants (Nokido, Architecture, MCP...)."""
    racine = _arbre(tmp_path)
    fr = racine / "docs" / "i18n" / "README.fr.md"
    fr.write_text(fr.read_text(encoding="utf-8").replace("## Demarrage", "## Quick start"), encoding="utf-8")
    assert [e.point for e in C.verifier(racine)] == [6]


def _complet(racine, version="0.20.15", titre_fr="## Installation", lien_fr="[c](../README_complet.md)"):
    d = racine / "docs"
    (d / "README_complet.md").write_text("# Nokido\n\n## Installation\n\n%s\n\n[r](../README.md)\n"
                                         % P.bloc(P.PAQUET, version), encoding="utf-8")
    (d / "i18n" / "README_complet.fr.md").write_text("# Nokido\n\n%s\n\n%s\n\n%s\n"
                                                     % (titre_fr, P.bloc(P.PAQUET, version, "fr"), lien_fr),
                                                     encoding="utf-8")
    return racine


def test_complet_conforme_et_ecrit_par_langue(tmp_path):
    racine = _complet(_arbre(tmp_path))
    assert C.verifier(racine) == []
    assert P.langue_de(racine / "docs" / "i18n" / "README_complet.fr.md") == "fr"
    P.ecrire(racine, P.PAQUET, "0.20.16")
    assert P.bloc(P.PAQUET, "0.20.16", "fr") in (racine / "docs" / "i18n" / "README_complet.fr.md").read_text(
        encoding="utf-8")


def test_complet_version_titres_liens(tmp_path):
    racine = _complet(_arbre(tmp_path), version="none")            # « pas sur PyPI » quand README annonce 0.20.15
    assert any(e.point == 1 and "README_complet" in e.fichier for e in C.verifier(racine))
    racine = _complet(_arbre(tmp_path / "b"), titre_fr="### Installation", lien_fr="[x](../absent.md)")
    points = sorted({e.point for e in C.verifier(racine)})
    assert points == [3, 4]


def test_chemin_reel_cli(tmp_path):
    _arbre(tmp_path, extra_fr="[x](../absent.md)\n")
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_readme_conformite.py"), "--racine", str(tmp_path)],
                       capture_output=True, text=True, errors="replace", timeout=20)
    assert p.returncode == 1 and "absent.md" in p.stdout


def test_le_gate_est_branche_partout():
    """Le gate ne vaut que s'il tourne la ou le README part : release (avant le build : la page PyPI porte la version
    construite), promotion du dist (avant le commit), gate de release, suite pure de la CI."""
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    i_rendu, i_build = wf.find("forge_readme_conformite.py --version"), wf.find("run: uv build")
    assert 0 < i_rendu < i_build and "forge_readme_pip.py --ecrire --version" in wf[:i_build]
    assert "forge_readme_conformite" in (ROOT / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    assert "ctrl_readme_conforme)" in (ROOT / "tools" / "forge_release_gate.py").read_text(encoding="utf-8")
    assert '"tests/nr/test_readme_conformite_nr.py"' in (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")


def test_le_depot_est_conforme():
    ecarts = C.verifier(ROOT)
    assert not ecarts, "\n".join(str(e) for e in ecarts)
