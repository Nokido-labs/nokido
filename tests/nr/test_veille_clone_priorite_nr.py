"""Tests NR : sous cap, ce qui est retenu doit etre CHOISI, pas rencontre.

`forge_veille_clone_ingest` plafonne le volume ingere par depot. Avant le
correctif du 2026-08-30, la selection suivait l'ordre de `os.walk` et
s'interrompait au premier depassement : sur un gros depot, on gardait les
premiers repertoires rencontres et on jetait le reste EN SILENCE. L'ordre du
systeme de fichiers n'est pas un critere de pertinence.

Tests PURS : `priorite()` ne touche ni disque ni reseau.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.forge_veille_clone_ingest import (  # noqa: E402
    CAP_PAR_REPO,
    MAX_TOTAL,
    SKIP_EXT,
    est_binaire,
    priorite,
)


def trie(chemins):
    return sorted(chemins, key=priorite)


# --- le contrat d'agent passe avant tout ------------------------------------
def test_agents_md_passe_avant_le_code():
    """AGENTS.md dit ce que le depot attend d'un agent : rang 0, toujours."""
    assert trie(["codex-rs/core/src/lib.rs", "AGENTS.md"])[0] == "AGENTS.md"


def test_readme_passe_avant_la_doc_secondaire():
    assert trie(["docs/advanced/tuning.md", "README.md"])[0] == "README.md"


def test_doc_passe_avant_configuration_et_code():
    ordre = trie(["Cargo.toml", "src/main.rs", "docs/design.md"])
    assert ordre == ["docs/design.md", "Cargo.toml", "src/main.rs"]


def test_configuration_passe_avant_le_code():
    assert trie(["src/main.rs", "Cargo.toml"])[0] == "Cargo.toml"


# --- a rang egal, le coeur avant la peripherie ------------------------------
def test_a_rang_egal_le_chemin_le_moins_profond_gagne():
    ordre = trie(["codex-rs/core/src/deep/nested/thing.rs", "codex-rs/lib.rs"])
    assert ordre[0] == "codex-rs/lib.rs"


def test_profondeur_prime_sur_la_longueur_du_nom():
    """Un nom long peu profond bat un nom court tres profond."""
    ordre = trie(["a/b/c/x.rs", "un_nom_de_fichier_tres_long.rs"])
    assert ordre[0] == "un_nom_de_fichier_tres_long.rs"


def test_agents_md_profond_reste_prioritaire_sur_du_code_racine():
    """Le rang domine la profondeur : un contrat enfoui bat du code racine."""
    ordre = trie(["main.rs", "sub/project/AGENTS.md"])
    assert ordre[0] == "sub/project/AGENTS.md"


# --- insensibilite a la casse ----------------------------------------------
def test_la_casse_du_nom_ne_change_pas_le_rang():
    assert priorite("Agents.md")[0] == priorite("agents.md")[0] == 0
    assert priorite("ReadMe.md")[0] == 0


# --- l'ordre est TOTAL et deterministe -------------------------------------
def test_tri_deterministe_sur_entree_permutee():
    """Deux ordres d'entree differents doivent rendre la MEME sortie."""
    a = ["src/main.rs", "AGENTS.md", "Cargo.toml", "docs/x.md"]
    assert trie(a) == trie(list(reversed(a)))


# --- AUCUNE limite de volume (decision owner 2026-08-30) -------------------
def test_aucun_cap_par_defaut():
    """« Pas de limite a l'ingestion d'un depot » : le raffinage trie en aval.

    Un cap a l'ingestion est une perte IRREVERSIBLE decidee par l'ordre du
    systeme de fichiers -- ce qui n'entre pas ne pourra jamais etre raffine.
    """
    assert MAX_TOTAL is None


def test_aucun_depot_ne_porte_de_cap():
    assert CAP_PAR_REPO == {}


# --- la selection par type est une LISTE NOIRE, pas une allowlist ----------
def test_les_langages_de_code_ne_sont_plus_filtres_par_allowlist():
    """Une allowlist echoue en SILENCE sur tout langage non prevu.

    `.rs` manquait, et ingerer un depot Rust n'aurait rendu que la vitrine
    `.md` -- avec un rapport de succes. Aucune extension de code ne doit
    figurer dans la liste noire.
    """
    for ext in (".rs", ".go", ".java", ".kt", ".swift", ".cpp", ".rb", ".php",
                ".lua", ".sql", ".proto", ".zig", ".ex", ".scala", ".dart"):
        assert ext not in SKIP_EXT, f"{ext} ne doit pas etre exclu"


def test_les_binaires_et_assets_restent_exclus():
    for ext in (".png", ".zip", ".exe", ".woff2", ".safetensors", ".pdf"):
        assert ext in SKIP_EXT


def test_un_fichier_texte_nest_pas_pris_pour_un_binaire(tmp_path):
    f = tmp_path / "a.rs"
    f.write_bytes(b"fn main() { println!(\"ok\"); }\n")
    assert est_binaire(str(f)) is False


def test_un_octet_nul_trahit_un_binaire_quelle_que_soit_l_extension(tmp_path):
    """Un binaire peut porter n'importe quel suffixe ; `read_text` ne leve pas
    dessus, il rend une bouillie qui polluerait le lexical."""
    f = tmp_path / "piege.rs"
    f.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00" * 8)
    assert est_binaire(str(f)) is True


def test_fichier_absent_est_traite_comme_non_ingerable(tmp_path):
    """Illisible n'est pas « texte » : on ne l'ingere pas, et on le compte."""
    assert est_binaire(str(tmp_path / "nexiste_pas.rs")) is True
