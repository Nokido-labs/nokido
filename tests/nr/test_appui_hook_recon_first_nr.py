# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `tools/hook_recon_first.py`. Il verifie que le module se CHARGE, rien de plus.

Ce qu'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain`
ne peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs
de chargement (NameError, ImportError) sur un chemin que personne n'execute.

Ce qu'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la
metrique `couverture prouvee` — le marqueur en tete sert exactement a l'en
exclure. Le remplacer par un vrai test de comportement est un progres ; le
supprimer sans le remplacer rend le module non mesurable.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    assert importlib.import_module("hook_recon_first") is not None


# --------------------------------------------------------------------------
# PRECISION du garde (2026-09-14). Un garde qui crie a faux se fait desarmer —
# c'est la raison pour laquelle le faux positif se corrige tout de suite, au
# meme titre qu'un faux negatif (celui sur `laforge_py314` l'a ete en dix
# minutes le 30/07).
#
# Cas MESURE : un `git commit -m "...GATE-KO /rag..."` a ete refuse au motif
# « domaine rag instrumente sans consultation ». Le commit n'instrumentait
# aucun domaine : le mot vivait dans la PROSE du message. Le garde lisait la
# ligne entiere, message compris.
# --------------------------------------------------------------------------

def _domaines(texte):
    return importlib.import_module("hook_recon_first")._domaines(texte)


def test_un_message_de_commit_n_instrumente_aucun_domaine():
    """ROUGE ATTENDU avant correctif — le cas exact paye le 2026-09-14."""
    cmd = (
        'git -c safe.directory=* -C "/depot" commit '
        '-m "fix(ui): le gate juge au lieu de sortir UNKNOWN" '
        '-m "verdict ROUGE avec une cause nommee (GATE-KO /rag, chunks)"'
    )
    assert _domaines(cmd) == set(), (
        "le garde lit la prose du message de commit comme une instrumentation : %r"
        % (_domaines(cmd),)
    )


def test_le_domaine_reste_detecte_hors_message():
    """Controle NEGATIF : on ne troque pas un faux positif contre un trou.

    Une vraie instrumentation doit continuer de mordre, y compris dans une
    commande qui porte AUSSI un message de commit.
    """
    assert "rag" in _domaines('python tools/bench_rag.py --rebuild')
    assert "rag" in _domaines(
        'python tools/embed_probe.py && git commit -m "mesure"'
    )


def test_un_message_en_apostrophes_est_traite_pareil():
    """Les deux quotages existent ; n'en couvrir qu'un laisse la moitie du trou."""
    assert _domaines("git commit -m 'refonte du chunk store'") == set()


# --------------------------------------------------------------------------
# COMPORTEMENT du garde (2026-09-13). Le test d'appui ci-dessus ne prouve rien
# d'autre que l'import ; sa propre docstring invite a le remplacer par du
# comportement. Ce qui suit verrouille les deux defauts MESURES ce jour-la.
# --------------------------------------------------------------------------
import io      # noqa: E402
import json    # noqa: E402
import time    # noqa: E402

import pytest  # noqa: E402


def _verdict(monkeypatch, tmp_path, etat: dict, chemin: str) -> int:
    """Joue le hook sur un etat ISOLE et rend son code de sortie (2 = deny)."""
    mod = importlib.import_module("hook_recon_first")
    fichier = tmp_path / "recon_state.json"
    fichier.write_text(json.dumps(etat), encoding="utf-8")
    monkeypatch.setattr(mod, "ETAT", fichier, raising=False)
    charge = {"tool_name": "Write",
              "tool_input": {"file_path": chemin, "content": "print(1)"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(charge)))
    return mod.main()


def test_creer_un_script_sans_rien_consulter_est_refuse(monkeypatch, tmp_path):
    """Le garde ne mordait QUE sur un `forge_*.py` du depot.

    Or la reinvention passe par des scripts d'INSTRUMENT hors depot : le
    2026-09-13, dix ont ete crees dans C:/tmp en une session, dont trois
    refaisaient un outil existant (`forge_ci_profil`, `forge_service_rss_watch`,
    le profilage scalene). Aucun n'a declenche le garde.
    """
    rc = _verdict(monkeypatch, tmp_path, {},
                  str(tmp_path / "instrument_invente.py").replace("\\", "/"))
    assert rc == 2, (
        "creation d'un script neuf sans consultation : le garde doit refuser UNE "
        "fois, sinon la reinvention passe par les scripts hors depot"
    )


def test_une_consultation_de_la_veille_ne_vaut_pas_autorisation(monkeypatch, tmp_path):
    """LE defaut du 2026-09-13 : `__memoire__` etait un drapeau GLOBAL a TTL 24 h.

    Mesure : drapeau pose il y a 13,1 h sur un tout autre sujet, garde muet toute
    la journee. Un garde dont le signal est trop grossier ne garde rien.
    """
    vieux = {"__memoire__": time.time() - 13.1 * 3600}
    rc = _verdict(monkeypatch, tmp_path, vieux,
                  str(tmp_path / "autre_instrument.py").replace("\\", "/"))
    assert rc == 2, (
        "consultation vieille de 13 h : elle ne prouve rien sur le sujet courant, "
        "le garde doit refuser"
    )


def test_une_consultation_fraiche_laisse_passer(monkeypatch, tmp_path):
    """Contre-epreuve : un garde qui refuse TOUJOURS se fait desarmer.

    Sans ce cas, les deux precedents seraient satisfaits par un `return 2` en dur.
    """
    frais = {"__memoire__": time.time() - 60}
    rc = _verdict(monkeypatch, tmp_path, frais,
                  str(tmp_path / "apres_consultation.py").replace("\\", "/"))
    assert rc == 0, "apres une consultation recente, le garde doit se taire"


def test_le_garde_ne_bloque_qu_une_fois(monkeypatch, tmp_path):
    """Un peage permanent se contourne ; un rappel unique s'accepte.

    Le garde marque la cle AVANT de refuser, donc la relance passe.
    """
    mod = importlib.import_module("hook_recon_first")
    fichier = tmp_path / "recon_state.json"
    fichier.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ETAT", fichier, raising=False)
    chemin = str(tmp_path / "deux_fois.py").replace("\\", "/")
    charge = json.dumps({"tool_name": "Write",
                         "tool_input": {"file_path": chemin, "content": "x"}})

    monkeypatch.setattr("sys.stdin", io.StringIO(charge))
    assert mod.main() == 2, "premier passage : le garde doit refuser"

    monkeypatch.setattr("sys.stdin", io.StringIO(charge))
    assert mod.main() == 0, (
        "second passage : le garde a deja dit son mot, il ne doit plus bloquer"
    )


def test_le_seuil_de_fraicheur_est_declare(monkeypatch, tmp_path):
    """Le seuil doit avoir UN defaut nomme, pas une valeur enfouie.

    Mesure 2026-09-05 : deux defauts pour un meme garde (hub 15 s / module 60 s)
    ont produit un piege de relecture -- on lisait l'un, l'autre s'appliquait.
    """
    mod = importlib.import_module("hook_recon_first")
    seuil = getattr(mod, "TTL_CONSULTATION_CREATION_S", None)
    assert isinstance(seuil, (int, float)) and seuil > 0, (
        "le seuil de fraicheur doit etre une constante declaree du module"
    )
    assert seuil < mod.TTL_S, (
        "le seuil de creation doit etre PLUS COURT que le TTL de domaine, sinon "
        "il n'ajoute aucune exigence"
    )
