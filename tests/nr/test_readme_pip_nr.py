"""NR -- le bloc `pip install` du README annonce ce que PyPI SERT, ni plus ni moins.

Decision owner 2026-10-01 : sur la version distribuee, l'installation par pip doit
figurer dans le README des qu'une version est servie par PyPI, et un gate doit la
faire correspondre a chaque nouvelle distribution. PyPI SEUL fait foi : une version
n'y arrive qu'apres la preuve d'installation trois OS de release.yml.

Trois etats pour l'index, jamais deux : une version servie, AUCUNE (le projet
n'existe pas), ILLISIBLE (reseau, reponse invalide). ILLISIBLE ne s'ecrit jamais.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    chemin = ROOT / "tools" / "forge_readme_pip.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_readme_pip", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_readme_pip"] = mod
    spec.loader.exec_module(mod)
    return mod


def _index(statut=200, version="1.2.3"):
    """Doublure de urlopen : jamais le vrai reseau dans un NR."""
    def ouvrir(url, timeout=None):
        assert url == "https://pypi.org/pypi/nokido-agent/json", url
        if statut != 200:
            raise urllib.error.HTTPError(url, statut, "x", {}, None)
        return io.BytesIO(json.dumps({"info": {"version": version}}).encode())
    return ouvrir


def _readme(m, version):
    return "# X\n\n" + m.bloc("nokido-agent", version) + "\n\nsuite\n"


# --- l'index : trois etats -----------------------------------------------------

def test_une_version_servie_est_lue():
    m = _mod()
    assert m.version_servie("nokido-agent", ouvrir=_index(version="0.21.0")) == "0.21.0"


def test_un_projet_absent_de_PyPI_rend_AUCUNE():
    m = _mod()
    assert m.version_servie("nokido-agent", ouvrir=_index(statut=404)) == m.AUCUNE


def test_un_index_injoignable_rend_ILLISIBLE_et_jamais_AUCUNE():
    m = _mod()

    def panne(url, timeout=None):
        raise OSError("reseau coupe")
    assert m.version_servie("nokido-agent", ouvrir=panne) == m.ILLISIBLE
    assert m.version_servie("nokido-agent", ouvrir=_index(statut=503)) == m.ILLISIBLE


# --- le rendu ------------------------------------------------------------------

def test_sans_version_publiee_le_bloc_ne_propose_AUCUNE_commande_pip():
    m = _mod()
    b = m.bloc("nokido-agent", m.AUCUNE)
    assert "```" not in b, "pas de bloc de code copiable tant que PyPI ne sert rien"
    assert "not on PyPI yet" in b


def test_une_version_publiee_donne_la_commande_ET_le_lien_PyPI():
    m = _mod()
    b = m.bloc("nokido-agent", "0.21.0")
    assert "pip install nokido-agent==0.21.0" in b
    assert "https://pypi.org/project/nokido-agent/0.21.0/" in b


# --- hors ligne : le README est-il coherent avec sa propre declaration ? -------

def test_un_bloc_regenere_est_coherent():
    m = _mod()
    statut, note = m.coherence(_readme(m, "0.21.0"), "nokido-agent")
    assert statut == m.ALIGNE, note


def test_un_bloc_retouche_a_la_main_est_une_divergence():
    m = _mod()
    texte = _readme(m, "0.21.0").replace("nokido-agent==0.21.0", "nokido-agent==0.22.0")
    statut, _ = m.coherence(texte, "nokido-agent")
    assert statut == m.DIVERGE


def test_une_commande_pip_HORS_du_bloc_est_une_divergence():
    m = _mod()
    texte = _readme(m, m.AUCUNE) + "\n```bash\npip install nokido-agent\n```\n"
    statut, note = m.coherence(texte, "nokido-agent")
    assert statut == m.DIVERGE and "hors du bloc" in note


# --- une phrase qui nie pip, alors que PyPI sert (owner 2026-10-06) ------------------------------
_NEGATION = "\n> **Alpha: run from a cloned repository. `pip install` is not supported yet.**\n"


def test_une_negation_de_pip_contredit_une_version_servie():
    """Le README publie de 0.20.8 : « From PyPI » en tete, « not supported yet » plus bas."""
    m = _mod()
    statut, note = m.coherence(_readme(m, "0.20.8") + _NEGATION, "nokido-agent")
    assert statut == m.DIVERGE and "nie encore pip" in note and "not supported" in note
    fr = _readme(m, "0.20.8") + "\n`pip install` n'est pas encore pris en charge.\n"
    assert m.coherence(fr, "nokido-agent")[0] == m.DIVERGE


def test_sans_version_servie_la_negation_reste_permise():
    """Tant que PyPI ne sert rien, dire « pas encore » est JUSTE : le gate ne crie pas a faux."""
    m = _mod()
    assert m.coherence(_readme(m, m.AUCUNE) + _NEGATION, "nokido-agent")[0] == m.ALIGNE


def test_le_bloc_lui_meme_n_est_pas_une_negation():
    """Le bloc genere dit « not on PyPI yet » quand aucune version n'est servie : hors champ."""
    m = _mod()
    assert m._negations_hors_bloc(_readme(m, m.AUCUNE)) == []


def test_le_promoteur_refuse_une_negation_AVANT_toute_mutation(monkeypatch):
    """Le bloc de la source reste a `none` : la contradiction n'apparait qu'apres alignement. Le
    promoteur la juge avant d'ecrire quoi que ce soit, sur le README lu au sha promu."""
    import pytest
    import subprocess as sp
    spec = importlib.util.spec_from_file_location("promoteur_pip_nr", ROOT / "tools" / "forge_dist_publish.py")
    p = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p)
    m = _mod()
    fichiers = {"README.md": _readme(m, m.AUCUNE) + _NEGATION}

    def faux_run(cmd, capture=True, check=False):
        if "ls-tree" in cmd:
            return sp.CompletedProcess(cmd, 0, "\n".join(fichiers), "")
        chemin = cmd[-1].split(":", 1)[1]
        return sp.CompletedProcess(cmd, 0, fichiers[chemin], "")
    monkeypatch.setattr(p, "run", faux_run)
    with pytest.raises(SystemExit) as e:
        p._verifier_negations_pip("a" * 40, "nokido-agent", "0.20.8")
    assert "README.md" in str(e.value) and "0.20.8" in str(e.value)
    p._verifier_negations_pip("a" * 40, "nokido-agent", None)          # rien de servi : rien a juger
    fichiers["README.md"] = _readme(m, m.AUCUNE)
    p._verifier_negations_pip("a" * 40, "nokido-agent", "0.20.8")       # aucune negation : passe
    src = (ROOT / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    corps = src[src.index("def main()"):]
    assert corps.index("_verifier_negations_pip(") < corps.index("ensure_dist_repo(")


def test_le_README_du_depot_ne_nie_pas_pip_une_fois_aligne():
    """Le chemin reel : le README versionne, bloc simule a une version servie, reste coherent."""
    m = _mod()
    texte = (ROOT / "README.md").read_text(encoding="utf-8")
    simule = m._RE_BLOC.sub(lambda _x: m.bloc("nokido-agent", "0.20.8"), texte, count=1)
    statut, note = m.coherence(simule, "nokido-agent")
    assert statut == m.ALIGNE, note


def test_un_autre_nom_de_paquet_est_une_divergence():
    m = _mod()
    statut, _ = m.coherence(_readme(m, "0.21.0").replace("nokido-agent", "laforge-agent"),
                            "nokido-agent")
    assert statut == m.DIVERGE


def test_sans_bloc_le_controle_le_DIT():
    m = _mod()
    statut, _ = m.coherence("# README sans bloc\n", "nokido-agent")
    assert statut == m.INDETERMINE


# --- en ligne : le README suit-il ce que PyPI sert ? ---------------------------

def test_un_README_en_retard_sur_PyPI_est_une_divergence():
    m = _mod()
    statut, note = m.verifier(_readme(m, m.AUCUNE), "nokido-agent", "0.21.0")
    assert statut == m.DIVERGE and "0.21.0" in note


def test_un_README_qui_annonce_une_version_NON_servie_est_une_divergence():
    m = _mod()
    statut, _ = m.verifier(_readme(m, "0.22.0"), "nokido-agent", "0.21.0")
    assert statut == m.DIVERGE


def test_un_index_ILLISIBLE_ne_vaut_pas_alignement():
    m = _mod()
    statut, _ = m.verifier(_readme(m, "0.21.0"), "nokido-agent", m.ILLISIBLE)
    assert statut == m.INDETERMINE


# --- la mise en correspondance -------------------------------------------------

def test_ecrire_aligne_tous_les_fichiers_qui_portent_le_bloc(tmp_path):
    m = _mod()
    (tmp_path / "docs" / "i18n").mkdir(parents=True)
    (tmp_path / "README.md").write_text(_readme(m, m.AUCUNE), encoding="utf-8")
    (tmp_path / "docs" / "i18n" / "README.fr.md").write_text(_readme(m, m.AUCUNE), encoding="utf-8")
    (tmp_path / "docs" / "i18n" / "README.de.md").write_text("# sans bloc\n", encoding="utf-8")
    changes = m.ecrire(tmp_path, "nokido-agent", "0.21.0")
    assert sorted(p.name for p in changes) == ["README.fr.md", "README.md"]
    for p in changes:
        assert m.verifier(p.read_text(encoding="utf-8"), "nokido-agent", "0.21.0")[0] == m.ALIGNE
    assert (tmp_path / "docs" / "i18n" / "README.de.md").read_text(encoding="utf-8") == "# sans bloc\n"


def test_ecrire_refuse_d_ecrire_ILLISIBLE(tmp_path):
    m = _mod()
    (tmp_path / "README.md").write_text(_readme(m, m.AUCUNE), encoding="utf-8")
    try:
        m.ecrire(tmp_path, "nokido-agent", m.ILLISIBLE)
    except ValueError:
        pass
    else:
        raise AssertionError("ILLISIBLE ne doit jamais etre ecrit dans un README")


# --- les deux points de mise en correspondance (chemin reel) -------------------

def test_release_aligne_le_README_APRES_PyPI_et_sans_pouvoir_publier():
    import yaml
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["readme-pypi"]
    besoins = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "create-release" in besoins, "le README ne suit PyPI qu'apres la Release"
    perms = job.get("permissions") or {}
    assert perms.get("contents") == "write" and "id-token" not in perms, perms
    script = "\n".join(s.get("run", "") for s in job["steps"])
    assert "forge_readme_pip.py --ecrire" in script and "--exiger-servie" in script


def test_le_promoteur_lit_PyPI_AVANT_toute_mutation_et_ecrit_AVANT_le_commit():
    src = (ROOT / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    corps = src[src.index("def main()"):]
    assert corps.index("_version_pypi_servie(") < corps.index("ensure_dist_repo(")
    assert corps.index("sync_snapshot(") < corps.index("_aligner_bloc_pip(") \
        < corps.index("commit_version(")


def test_les_huit_README_portent_le_bloc_et_il_est_coherent():
    """Une traduction qui perd le bloc ne suivrait plus PyPI -- en silence."""
    m = _mod()
    fs = m.fichiers(ROOT)
    assert len(fs) == 8, [p.name for p in fs]
    for p in fs:
        statut, note = m.coherence(p.read_text(encoding="utf-8"), "nokido-agent")
        assert statut == m.ALIGNE, "%s : %s" % (p.name, note)


def test_le_README_du_depot_porte_un_bloc_coherent():
    """Le chemin reel : le README versionne passe le controle hors ligne."""
    m = _mod()
    texte = (ROOT / "README.md").read_text(encoding="utf-8")
    statut, note = m.coherence(texte, "nokido-agent")
    assert statut == m.ALIGNE, note
