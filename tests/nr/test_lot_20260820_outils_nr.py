"""NR -- lot d'outils du 2026-08-20 (veille CLI, coffre, ingestion, index memoire).

POURQUOI. Le cliquet `test_nr_coverage_ratchet_nr` a mordu au run GHA 32390147813 :
quatre modules ajoutes par le commit af6e4ad3, aucun test. Le gate a raison --
ces outils portent des VERDICTS (« cette version a change », « ce secret est
duplique », « cette page est deja vue », « cette ligne tient dans le budget »)
sur lesquels des decisions se prennent ensuite.

Chaque test verifie un EFFET, jamais un import : un test qui se contente de
charger le module atteste que le code est ECRIT, jamais qu'il MARCHE, et ne tue
aucun mutant (mesure du 2026-08-18).

Aucun test ici ne sort sur le reseau ni ne lit le working tree : les entrees sont
construites dans `tmp_path` ou passees en memoire.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _charger(nom: str, zone: str = "tools"):
    """Charge un module par son chemin. Un ImportError ECHOUE le test : un outil
    qu'on ne peut plus importer est casse, pas 'a sauter'."""
    chemin = ROOT / zone / (nom + ".py")
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# forge_ingest_llms_txt -- l'index des pages a ingerer
# --------------------------------------------------------------------------

def test_extraire_pages_dedoublonne_en_gardant_le_premier_ordre():
    """Une URL vue deux fois ne doit etre ingeree qu'une fois, et l'ordre de
    l'index doit etre conserve : c'est lui qui porte la structure de la doc."""
    m = _charger("forge_ingest_llms_txt")
    index = (
        "- [Intro](https://ex.test/a.md)\n"
        "- [Suite](https://ex.test/b.md)\n"
        "- [Intro bis](https://ex.test/a.md)\n"
    )
    assert m.extraire_pages(index, None) == [
        ("Intro", "https://ex.test/a.md"),
        ("Suite", "https://ex.test/b.md"),
    ]


def test_extraire_pages_filtre_sur_le_prefixe_et_nettoie_la_ponctuation():
    """Le prefixe borne l'ingestion a une section. Et une URL collee a une
    ponctuation de fin de phrase ne doit pas partir en 404."""
    m = _charger("forge_ingest_llms_txt")
    index = (
        "voir [Guide](https://ex.test/docs/g.md), et [Autre](https://autre.test/z.md)\n"
    )
    pages = m.extraire_pages(index, "https://ex.test/docs/")
    assert pages == [("Guide", "https://ex.test/docs/g.md")]


# --------------------------------------------------------------------------
# forge_env_to_vault -- migration des secrets vers le coffre
# --------------------------------------------------------------------------

def test_lire_env_ignore_commentaires_et_valeurs_vides(tmp_path):
    m = _charger("forge_env_to_vault")
    f = tmp_path / ".env"
    f.write_text(
        "# un commentaire\n"
        "\n"
        "VIDE=\n"
        "SANS_EGAL\n"
        'CITE="valeur"\n'
        "SIMPLE='autre'\n",
        encoding="utf-8",
    )
    assert m.lire_env(f) == {"CITE": "valeur", "SIMPLE": "autre"}


def test_lire_env_signale_un_doublon_divergent_et_garde_la_derniere(capsys, tmp_path):
    """Mesure du 2026-08-20 : CLOUDFLARE_ACCOUNT_ID figurait deux fois avec des
    valeurs differentes. Ecraser en SILENCE fait perdre un secret -- le conflit
    doit etre DIT, et la derniere ligne l'emporte de facon deterministe."""
    m = _charger("forge_env_to_vault")
    f = tmp_path / ".env"
    f.write_text("CLE=premiere\nCLE=seconde\n", encoding="utf-8")
    assert m.lire_env(f) == {"CLE": "seconde"}
    sortie = capsys.readouterr().out
    assert "CLE" in sortie and "DUPLIQUE" in sortie
    assert "premiere" not in sortie and "seconde" not in sortie


def test_emp_compare_sans_jamais_exposer_la_valeur():
    """L'empreinte sert a COMPARER deux secrets. Elle ne doit ni contenir le
    secret, ni varier d'un appel a l'autre."""
    m = _charger("forge_env_to_vault")
    e = m._emp("secret-tres-sensible")
    assert e == m._emp("secret-tres-sensible")
    assert e != m._emp("autre-secret")
    assert len(e) == 12
    assert "secret" not in e


# --------------------------------------------------------------------------
# forge_memory_index_compact -- compacter l'index sans perdre d'entree
# --------------------------------------------------------------------------

def test_compacter_ne_supprime_jamais_une_ligne():
    """L'invariant central : une troncature de fin mangerait les entrees les
    plus anciennes (donc la doctrine). Ici on rabote, on ne coupe pas."""
    m = _charger("forge_memory_index_compact")
    lignes = ["- [%s](f%d.md) %s" % ("titre " * 40, i, "queue " * 30) for i in range(12)]
    txt = "\n".join(lignes)
    out, _budget = m.compacter(txt, 2000)
    assert len(out.strip().splitlines()) == len(lignes)


def test_compacter_atteint_la_cible_en_octets():
    m = _charger("forge_memory_index_compact")
    txt = "\n".join("- [%s](f%d.md)" % ("mot " * 80, i) for i in range(20))
    cible = 3000
    out, _budget = m.compacter(txt, cible)
    assert len(out.encode("utf-8")) <= cible


def test_compacter_ligne_rabote_le_libelle_mais_preserve_la_cible():
    """On peut raccourcir ce qu'un lien AFFICHE ; jamais ou il POINTE."""
    m = _charger("forge_memory_index_compact")
    ligne = "- [%s](destination_exacte.md)" % ("libelle tres long " * 20)
    court = m._compacter_ligne(ligne, 120)
    assert "destination_exacte.md" in court
    assert len(court) < len(ligne)


def test_compacter_ligne_laisse_une_ligne_deja_courte_intacte():
    m = _charger("forge_memory_index_compact")
    ligne = "- [ok](x.md)"
    assert m._compacter_ligne(ligne, 500) == ligne


# --------------------------------------------------------------------------
# forge_cli_version_watch -- surveiller les versions des CLI
# --------------------------------------------------------------------------

def test_version_binaire_dit_la_non_mesure_au_lieu_de_la_maquiller():
    """Un binaire absent ne doit JAMAIS ressortir en 'inchange' : ce serait un
    faux-vert, et la veille conclurait que la doc est a jour sans l'avoir vu."""
    m = _charger("forge_cli_version_watch")
    v = m.version_binaire("nokido_binaire_qui_n_existe_pas_xyz")
    assert v.startswith("non mesure")
    assert "PATH" in v


def test_le_daemon_reprend_la_contention_mais_meurt_sur_un_defaut():
    """CONTRAT STRUCTUREL, assume comme plus faible qu'un test d'effet : la boucle
    de `main()` est infinie et ne se prete pas a un appel direct.

    Ce qu'il protege : reprendre sur `Exception` transformait un NameError ou un
    KeyError en « on reessaie dans 2 s ». Le daemon restait vivant et
    cognitivement casse, heartbeat battant -- plus trompeur qu'un daemon mort.
    Seule la contention SQLite se reprend ; tout le reste remonte.
    """
    src = (ROOT / "tools" / "forge_embed_auto_trigger.py").read_text(
        encoding="utf-8", errors="replace")
    principal = next((n for n in ast.walk(ast.parse(src))
                      if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert principal is not None, "main() introuvable"
    gestionnaires = [h for n in ast.walk(principal) if isinstance(n, ast.Try)
                     for h in n.handlers]

    contention = [h for h in gestionnaires
                  if h.type and "OperationalError" in ast.unparse(h.type)]
    assert contention, "la contention SQLite doit avoir son propre gestionnaire"
    assert any(isinstance(x, ast.Continue) for h in contention for x in ast.walk(h)), \
        "la contention doit REPRENDRE la boucle"

    larges_qui_bouclent = [
        h for h in gestionnaires
        if h.type and ast.unparse(h.type) == "Exception"
        and any(isinstance(x, ast.Continue) for x in ast.walk(h))
    ]
    assert not larges_qui_bouclent, (
        "un `except Exception` qui reprend la boucle avale les defauts logiques : "
        "le daemon survit en etant casse, et son heartbeat ment")


def test_empreinte_doc_rend_l_erreur_au_lieu_de_lever():
    """La veille passe sur plusieurs docs : une seule injoignable ne doit pas
    tuer la passe. L'echec est une DONNEE, nommee, pas une exception."""
    m = _charger("forge_cli_version_watch")
    r = m.empreinte_doc("schemebidon://hote/inexistant")
    assert isinstance(r, dict)
    assert "erreur" in r
    assert "sha256" not in r
