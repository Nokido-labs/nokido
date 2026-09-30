"""NR — une selection de tests dit ce qu'elle ECARTE, et ne certifie jamais.

La « suite pure » est un bloc de ~10 800 tests rejoue en entier a chaque
iteration. Le selecteur reduit ce cout, et c'est precisement pour cela qu'il est
dangereux : une selection silencieuse se lit comme une suite verte.

Ces tests gardent les trois abstentions, toutes du cote de la PRUDENCE :
diff illisible -> TOUT · aucun changement -> TOUT · fichier global -> TOUT.
Et l'invariant qui protege la publication : une partielle rend `SUITE_PARTIELLE`,
jamais `SUITE_COMPLETE` (directive owner du 2026-09-19 : ne pas sauter la CI
avant un push dist).
"""
import importlib
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.164)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
fcs = importlib.import_module("forge_ci_selection")

PRESENT = ["tests/nr/test_a_nr.py", "tests/nr/test_b_nr.py", "tests/nr/test_c_nr.py"]
SOURCES = {
    "tests/nr/test_a_nr.py": "import forge_token_monitor\n",
    "tests/nr/test_b_nr.py": "rien a voir\n",
    "tests/nr/test_c_nr.py": "on parle de forge_inspector ici\n",
}


def _lire(chemin):
    return SOURCES[chemin.replace("\\", "/")]


def test_seuls_les_tests_ATTEIGNABLES_par_le_diff_sont_retenus():
    r = fcs.selectionner(PRESENT, ["app/forge_token_monitor.py"], lire=_lire)
    assert r["mode"] == "PARTIELLE"
    assert r["retenus"] == ["tests/nr/test_a_nr.py"]
    assert r["ecartes"] == 2
    assert "1 test(s) sur 3" in r["raison"], "une borne doit dire COMBIEN"
    assert "forge_token_monitor" in r["pourquoi"]["tests/nr/test_a_nr.py"]


def test_un_diff_ILLISIBLE_fait_TOUT_jouer():
    """UNKNOWN != NO : ne rien savoir des changements n'est pas 'rien n'a change'."""
    r = fcs.selectionner(PRESENT, [], etat_diff="ILLISIBLE(git rc=128)", lire=_lire)
    assert r["mode"] == fcs.TOUT and r["retenus"] == PRESENT
    assert "ILLISIBLE" in r["raison"]


def test_aucun_changement_fait_TOUT_jouer():
    """Une selection VIDE declaree verte serait le faux vert parfait."""
    r = fcs.selectionner(PRESENT, [], lire=_lire)
    assert r["mode"] == fcs.TOUT and r["retenus"] == PRESENT


def test_un_fichier_GLOBAL_fait_TOUT_jouer():
    for global_ in ("conftest.py", "pyproject.toml", "tools/ci_local.py",
                    "requirements.txt", "tests/conftest.py"):
        r = fcs.selectionner(PRESENT, [global_, "app/forge_token_monitor.py"], lire=_lire)
        assert r["mode"] == fcs.TOUT, global_
        assert "global" in r["raison"]


def test_le_selecteur_LUI_MEME_est_un_fichier_global():
    """Sinon une modification du selecteur se validerait avec l'ancien selecteur."""
    r = fcs.selectionner(PRESENT, ["tools/forge_ci_selection.py"], lire=_lire)
    assert r["mode"] == fcs.TOUT


def test_un_test_MODIFIE_est_toujours_retenu():
    r = fcs.selectionner(PRESENT, ["tests/nr/test_b_nr.py"], lire=_lire)
    assert "tests/nr/test_b_nr.py" in r["retenus"]
    assert r["pourquoi"]["tests/nr/test_b_nr.py"] == "test modifie"


def test_une_source_ILLISIBLE_est_RETENUE_par_prudence():
    """Un test qu'on ne sait pas classer se joue : le classer 'hors perimetre'
    sur une lecture ratee fabriquerait un trou invisible.
    """
    def _lire_ko(chemin):
        if chemin.replace("\\", "/") == "tests/nr/test_b_nr.py":
            raise OSError("acces refuse")
        return _lire(chemin)

    r = fcs.selectionner(PRESENT, ["app/forge_token_monitor.py"], lire=_lire_ko)
    assert "tests/nr/test_b_nr.py" in r["retenus"]
    assert r["illisibles"] == ["tests/nr/test_b_nr.py"], "et l'illisible est COMPTE"


def test_une_PARTIELLE_ne_rend_JAMAIS_suite_complete():
    """L'invariant qui protege la publication (directive owner 2026-09-19)."""
    partielle = fcs.selectionner(PRESENT, ["app/forge_token_monitor.py"], lire=_lire)
    complete = fcs.selectionner(PRESENT, [], lire=_lire)

    assert fcs.etat_suite(partielle) == "SUITE_PARTIELLE"
    assert fcs.etat_suite(complete) == "SUITE_COMPLETE"

    texte = fcs.resume(partielle)
    assert "NE CERTIFIE PAS" in texte
    assert "pas de capture de sha" in texte
    assert "dist reste COMPLETE" in texte


def test_un_module_de_TEST_modifie_ne_compte_pas_comme_module_touche():
    """Sinon le mot 'test_b_nr' irait matcher des sources au hasard."""
    r = fcs.selectionner(PRESENT, ["tests/nr/test_b_nr.py"], lire=_lire)
    assert r["modules_touches"] == []


def test_un_dossier_qui_n_est_PAS_la_racine_git_est_refuse(tmp_path):
    """`git -C <dossier>` REMONTE au depot englobant s'il n'en est pas la racine.

    Mesure 2026-09-19 : le basetemp de pytest vit sous `sandbox/`, donc DANS
    Nokido — git y a rendu les 20 fichiers modifies du depot au lieu de refuser.
    Une selection batie sur le diff d'un AUTRE depot est fausse en silence, et
    rien ne la distingue d'une selection juste.
    """
    vus, etat = fcs.fichiers_modifies(tmp_path)
    assert vus == [], "le diff d'un autre depot ne doit jamais servir de base"
    assert etat.startswith("ILLISIBLE"), \
        "et ce refus doit etre DIT, pas rendu comme 'rien n'a change'"
    assert "hors depot" in etat or "pas un depot" in etat

    # Et l'appelant doit en tirer la bonne conclusion : TOUT jouer.
    assert fcs.selectionner(PRESENT, vus, etat_diff=etat, lire=_lire)["mode"] == fcs.TOUT


def test_la_racine_REELLE_du_depot_est_lisible():
    vus_reels, etat_reel = fcs.fichiers_modifies(ROOT)
    assert etat_reel == "PRESENT", "le depot Nokido doit etre lisible ici"
    assert isinstance(vus_reels, list)


def test_une_liste_FOURNIE_remplace_un_git_inaccessible(tmp_path):
    """Sous le compte du hub, git est REFUSE : l'auto-detection rend ILLISIBLE et
    joue TOUT. Correct, mais le mode serait inoperant la ou la CI tourne. La
    liste fournie par un appelant qui a le canal git retablit le gain.
    """
    f = tmp_path / "diff.txt"
    f.write_text("# commentaire ignore\napp/forge_token_monitor.py\n\n", encoding="utf-8")
    vus, etat = fcs.liste_depuis_fichier(f)
    assert vus == ["app/forge_token_monitor.py"] and etat == "PRESENT"

    r = fcs.selectionner(PRESENT, vus, etat_diff=etat, lire=_lire)
    assert r["mode"] == "PARTIELLE" and r["retenus"] == ["tests/nr/test_a_nr.py"]


def test_une_liste_VIDE_ou_ABSENTE_fait_TOUT_jouer(tmp_path):
    """Un fichier tronque, d'un run precedent, ou jamais ecrit produirait sinon
    une selection vide declaree verte -- le faux vert parfait.
    """
    vide = tmp_path / "vide.txt"
    vide.write_text("# que des commentaires\n", encoding="utf-8")
    for chemin in (vide, tmp_path / "jamais_ecrit.txt"):
        vus, etat = fcs.liste_depuis_fichier(chemin)
        assert vus == [] and etat.startswith("ILLISIBLE"), chemin
        assert fcs.selectionner(PRESENT, vus, etat_diff=etat, lire=_lire)["mode"] == fcs.TOUT


def test_le_drapeau_CLI_existe_et_ANNONCE_qu_il_ne_certifie_pas():
    """Chemin reel : `check()` passait ses tests pendant que `--check` mourait
    en NameError (mesure du depot). Un drapeau se traverse par son CLI.
    """
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "ci_local.py"), "--help"],
                       capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr[:400]
    aide = (r.stdout or "") + (r.stderr or "")
    assert "--impacte" in aide
    assert "--impacte-fichiers" in aide or "impacte-fichiers" in aide
    assert "NON CERTIFIANT" in aide, "un mode reducteur doit dire qu'il ne certifie pas"
    assert "dist reste COMPLETE" in aide, \
        "directive owner 2026-09-19 : ne pas sauter la CI avant un push dist"


def test_le_gate_FORCE_suite_partielle_quand_la_selection_reduit():
    """Garde STRUCTUREL : executer la CI complete dans un test est exclu, mais
    l'oubli qu'on veut empecher est precisement l'absence de cette ligne --
    sans elle, un run reduit publierait SUITE_COMPLETE.
    """
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '_bp["etat"] = "SUITE_PARTIELLE"' in src
    i = src.index('_bp["etat"] = "SUITE_PARTIELLE"')
    avant = src[max(0, i - 400):i]
    assert '_selection is not None' in avant and '!= "TOUT"' in avant, \
        "la bascule doit etre conditionnee a une selection REDUITE, pas posee sec"
    assert 'from forge_ci_selection import' in src, "le selecteur doit etre CABLE"
    assert '_selection["retenus"]' in src, "et son resultat REELLEMENT applique"
    assert 'liste_depuis_fichier' in src, \
        "sans la liste fournie, le mode est inoperant sous le compte du hub"
