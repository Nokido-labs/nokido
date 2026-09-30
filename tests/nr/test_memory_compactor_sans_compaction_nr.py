# -*- coding: utf-8 -*-
"""NR — `--auto` MESURE et SIGNALE le risque de plafond, sans jamais reecrire l'index.

Decision owner du 2026-09-11, en deux temps. D'abord desarmer la compaction (elle
descendait au plancher de 2 jours et emportait 14 entrees, dont trois de trois jours
marquees cinq etoiles). Puis CORRIGER ce desarmement, juge trop agressif : le
compacteur ne servait pas qu'a archiver, il etait aussi le GARDE contre le
depassement du plafond de chargement de l'index -- au-dela, des entrees sont
DROPPEES AU LOAD, en silence. Retirer le garde sans remplacant laissait 2,7 Ko de
marge (21,7 Ko mesures pour un cap de 24,4 Ko).

Le contrat devient donc : `--auto` mesure, signale, et ne deplace RIEN.

    ledger sync -> reingestion RAG -> mesure -> signal gradue -> STOP

Deux raisons de ne pas dependre du drapeau `--sans-compaction` pour cette surete :
la consigne de MEMORY.md du 2026-09-06 (« COMPACTER CET INDEX = A LA MAIN ») est
superieure a toute automatisation, et une surete qui vit dans un fichier de config
EXTERNE disparait des que quelqu'un edite ce fichier. Le defaut du CODE est le seul
endroit ou elle tient. Le drapeau reste accepte, sans effet, pour ne pas casser le
hook deja configure.

Ce que ce NR verrouille, et pourquoi chaque point a ete paye :
  - `--auto` seul (SANS drapeau) ne reecrit pas l'index : c'est le cas qui aurait
    emporte les 14 entrees au prochain SessionStart ;
  - le plancher vaut 5 jours et non 2 : reglage du filet, pas permission d'archiver
    du recent ;
  - le signal est GRADUE et nomme le cap : un index qui grossit ne doit pas se
    confondre avec un compacteur en panne — c'est le silence paye 24 h le 11/09 ;
  - la compaction MANUELLE reste fonctionnelle : desarmer l'automatisme ne doit pas
    supprimer la capacite, sinon on remplace un risque par une impuissance ;
  - `--rattacher --dry-run` n'ecrit rien : les 227 orphelines sont un chantier
    distinct, et sa reconnaissance ne doit produire aucun effet de bord.

Forme : simulation a la forme reelle. On traverse `main()` et les drapeaux CLI — le
chemin qu'un hook emprunte — mais les deux modules a EFFET DE BORD sont patches.
Sans ce patch, `_mi.ingerer(appliquer=True, fichier="MEMORY.md")` ecrirait dans la
VRAIE base RAG pendant la suite de tests, et `--memory-dir` ne l'en empeche pas (il
ne lui est pas passe). La prise suit la forme COMPLETE — les deux clefs de
`sys.modules` ET l'attribut du paquet — car `from nokido_agent.tools import X` lit
d'abord l'attribut du paquet (mesure du 2026-09-10).
"""
# pylint: disable=protected-access
#   Ce NR VERROUILLE des constantes privees (`_PLANCHER_JOURS`, `_SEUIL_DEFAUT_KB`,
#   `_CAP_CHARGEMENT_KB`) : y acceder est son objet meme, pas une indiscretion. Les
#   lire via une API publique inexistante reviendrait a ne plus les garder.
# pylint: disable=redefined-outer-name,unused-argument
#   Motif pytest : une fixture se recoit par argument, et `effets_de_bord_patches`
#   agit par EFFET (neutraliser ledger et ingestion), pas par valeur. La retirer des
#   signatures ferait ecrire ces tests dans la VRAIE base RAG -- exactement la prise
#   perdue mesuree le 2026-09-10.
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_memory_compactor as mc  # noqa: E402


def _index_qui_deborde(dossier: Path, cible_ko: float = 20.0) -> Path:
    """Index au-dessus du seuil, aux entrees DATEES et anciennes — donc compactables.

    Les deux proprietes sont necessaires : sous le seuil `--auto` sort tout de suite,
    et une entree sans date est epargnee par `_classify` de toute facon. Sans elles le
    test passerait pour la mauvaise raison.
    """
    lignes = ["# MEMORY (fixture)", ""]
    i = 0
    while sum(len(x) + 1 for x in lignes) / 1024 < cible_ko:
        lignes.append(f"- [lecon numero {i:03d}, texte de remplissage pour peser]"
                      f"(topic_{i:03d}_2026-01-15.md)")
        i += 1
    p = dossier / "MEMORY.md"
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    assert len(p.read_bytes()) / 1024 > mc._SEUIL_DEFAUT_KB, "fixture sous le seuil : rien mesure"
    return p


@pytest.fixture
def effets_de_bord_patches(monkeypatch):
    """Neutralise ledger et reingestion, et COMPTE leurs appels.

    Les compter, et pas seulement les taire : le garde ne doit toucher QUE la
    compaction. Un `--auto` qui court-circuiterait aussi le ledger ou la reingestion
    recreerait la panne silencieuse reparee le 11/09.
    """
    vus = {"ledger": 0, "ingest": 0}
    faux_ledger = types.ModuleType("forge_memory_ledger")
    faux_ledger.sync = lambda *a, **k: vus.__setitem__("ledger", vus["ledger"] + 1) or {"appended": 0}
    faux_ledger.prune = lambda *a, **k: None
    faux_ingest = types.ModuleType("forge_memory_ingest")
    faux_ingest.ingerer = lambda *a, **k: vus.__setitem__("ingest", vus["ingest"] + 1)

    paquet = sys.modules.get("nokido_agent.tools")
    for nom, faux in (("forge_memory_ledger", faux_ledger), ("forge_memory_ingest", faux_ingest)):
        monkeypatch.setitem(sys.modules, nom, faux)
        monkeypatch.setitem(sys.modules, f"nokido_agent.tools.{nom}", faux)
        if paquet is not None:
            monkeypatch.setattr(paquet, nom, faux, raising=False)
    return vus


def test_le_plancher_protege_cinq_jours():
    """Reglage du filet, pas permission d'archiver du recent (owner, 2026-09-11)."""
    assert mc._PLANCHER_JOURS == 5, mc._PLANCHER_JOURS


def test_le_cap_de_chargement_est_declare_et_au_dessus_du_seuil():
    """Le seuil de repli et le cap de LOAD sont deux grandeurs distinctes.

    Les confondre, c'est soit crier trop tot, soit ne pas crier du tout quand des
    entrees vont reellement etre perdues au chargement.
    """
    assert mc._CAP_CHARGEMENT_KB > mc._SEUIL_DEFAUT_KB, (mc._CAP_CHARGEMENT_KB, mc._SEUIL_DEFAUT_KB)


def test_auto_nu_sans_drapeau_ne_reecrit_pas_l_index(tmp_path, monkeypatch, capsys,
                                                     effets_de_bord_patches):
    """LE cas paye : c'est `--auto` NU qui aurait emporte 14 entrees au SessionStart.

    La surete doit tenir dans le defaut du CODE, pas dans un drapeau du hook — un
    fichier de config s'edite, et la protection disparaitrait avec lui.
    """
    p = _index_qui_deborde(tmp_path)
    avant = p.read_bytes()
    monkeypatch.setattr(sys, "argv", ["forge_memory_compactor.py", "--auto",
                                      "--memory-dir", str(tmp_path)])
    mc.main()

    assert p.read_bytes() == avant, "--auto NU a reecrit l'index"
    assert not (tmp_path / "MEMORY_ARCHIVE.md").exists(), "une archive froide a ete creee"
    sortie = capsys.readouterr().out
    assert f"{len(avant) / 1024:.1f}" in sortie, "la taille mesuree n'est pas dite : " + sortie
    assert effets_de_bord_patches["ledger"] == 1, "le ledger n'a pas ete synchronise"
    assert effets_de_bord_patches["ingest"] >= 1, "l'index n'a pas ete reingere"


def test_le_signal_est_gradue_et_nomme_le_cap(tmp_path, monkeypatch, capsys,
                                              effets_de_bord_patches):
    """Au-dela du CAP, le message doit changer de nature : ce n'est plus « l'index
    grossit », c'est « des entrees vont etre perdues au chargement »."""
    _index_qui_deborde(tmp_path, cible_ko=mc._CAP_CHARGEMENT_KB + 2)
    monkeypatch.setattr(sys, "argv", ["forge_memory_compactor.py", "--auto",
                                      "--memory-dir", str(tmp_path)])
    mc.main()
    sortie = capsys.readouterr().out
    assert "CAP" in sortie.upper(), sortie
    assert f"{mc._CAP_CHARGEMENT_KB:.1f}" in sortie, "le cap n'est pas chiffre : " + sortie


def test_le_drapeau_historique_reste_accepte(tmp_path, monkeypatch, effets_de_bord_patches):
    """`--sans-compaction` vit encore dans le hook global : le retirer du code
    ferait mourir le SessionStart en `unrecognized arguments`. Il est conserve, sans
    effet, et ce test empeche qu'on le supprime par inadvertance."""
    p = _index_qui_deborde(tmp_path)
    avant = p.read_bytes()
    monkeypatch.setattr(sys, "argv", ["forge_memory_compactor.py", "--auto",
                                      "--sans-compaction", "--memory-dir", str(tmp_path)])
    mc.main()
    assert p.read_bytes() == avant


def test_la_compaction_manuelle_reste_possible(tmp_path):
    """Garde du garde : desarmer l'automatisme ne doit pas supprimer la CAPACITE.

    Sans ce test, on pourrait « securiser » le module en le rendant incapable de
    compacter — remplacer un risque par une impuissance, et l'index deborderait
    quand meme, sans plus aucun remede.
    """
    p = _index_qui_deborde(tmp_path)
    avant = p.read_bytes()
    res = mc.compact(tmp_path, cutoff="2026-06-01", dry_run=False)
    assert res["archived"] > 0, res
    assert p.read_bytes() != avant, "la compaction manuelle ne fait plus rien"
    assert (tmp_path / "MEMORY_ARCHIVE.md").exists(), "le froid n'a pas recu les entrees"


def test_rattacher_en_dry_run_n_ecrit_rien(tmp_path):
    """Les 227 orphelines sont un chantier distinct : leur RECONNAISSANCE ne doit
    produire aucun effet de bord."""
    p = _index_qui_deborde(tmp_path)
    (tmp_path / "orpheline_2026-09-01.md").write_text(
        "---\ndescription: fiche de test orpheline\n---\n\ncorps\n", encoding="utf-8")
    avant = p.read_bytes()
    res = mc.rattacher(tmp_path, dry_run=True)
    assert res["orphelins"] >= 1, res
    assert p.read_bytes() == avant, "le dry-run a ecrit dans l'index chaud"
    assert not (tmp_path / "MEMORY_ARCHIVE.md").exists(), "le dry-run a cree l'archive froide"
