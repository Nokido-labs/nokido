"""NR — deporter une section de regles ne perd RIEN, et refuse plutot que de deviner.

Le 2026-09-02, une edition de `RULES_SHARED.md` a DETRUIT 31 775 octets en emportant
deux sections voisines ; il a fallu ecrire `tools/forge_rules_restore.py` pour
reparer. Le 2026-09-19, le meme geste se represente -- deporter la section
"Capacites d'execution" (52 % du fichier) hors du noyau resident, qui est re-envoye
a chaque tour. Ces tests sont le garde qui manquait la premiere fois.

Invariant central : `avant + section + apres == original`, verifie AVANT toute
ecriture. Et une comptabilite explicite `perdu == 0`, car un deplacement qui ne
compte pas ce qu'il deplace ne se distingue pas d'une suppression.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
frd = importlib.import_module("forge_rules_deport_section")

CORPUS = """# Regles

## Premiere section (2026-01-01)

Du texte A.

## Capacités d'exécution — formes qui MARCHENT (mesuré 2026-07-22)

| Piege | Forme correcte |
|---|---|
| un piege | une forme |

Corollaire : un outil qui refuse n'est presque jamais une capacite absente.

## Derniere section (2026-02-02)

Du texte B.
"""


# Une section assez GROSSE pour que le deport la fasse maigrir : sur une petite,
# le pointeur coute plus cher que ce qu'il remplace (mesure 2026-09-19 : pointeur
# 834 car. pour une section de 208) et l'outil doit REFUSER.
GROS = CORPUS.replace("| un piege | une forme |",
                      "\n".join("| piege %03d | forme %03d |" % (i, i) for i in range(120)))


def _source(tmp_path, texte=CORPUS):
    p = tmp_path / "RULES_SHARED.md"
    p.write_text(texte, encoding="utf-8")
    return p


def test_le_dry_run_compte_zero_perdu_et_n_ecrit_RIEN(tmp_path, capsys):
    src, dst = _source(tmp_path, GROS), tmp_path / "docs" / "DEPORTE.md"
    avant = src.read_text(encoding="utf-8")

    assert frd.deporter(src, "Capacites d'execution", dst, appliquer=False) == 0

    sortie = capsys.readouterr().out
    assert "perdu         0 car." in sortie, "la comptabilite doit etre AFFICHEE, pas supposee"
    assert not dst.exists(), "un dry-run qui ecrit n'est pas un dry-run"
    assert src.read_text(encoding="utf-8") == avant, "la source doit etre INTACTE"


def test_appliquer_deplace_le_texte_SANS_en_perdre_un_caractere(tmp_path):
    src, dst = _source(tmp_path, GROS), tmp_path / "docs" / "DEPORTE.md"
    original = src.read_text(encoding="utf-8")

    frd.deporter(src, "Capacites d'execution", dst, appliquer=True)

    cible = dst.read_text(encoding="utf-8")
    reste = src.read_text(encoding="utf-8")

    assert "| piege 042 | forme 042 |" in cible, "le corps doit avoir SUIVI"
    assert "un outil qui refuse n'est presque jamais" in cible
    assert "| piege 042 | forme 042 |" not in reste, "et avoir quitte la source"
    assert "Du texte A." in reste and "Du texte B." in reste, \
        "les sections VOISINES sont ce qui a ete detruit le 2026-09-02"
    assert "DEPORTEE" in reste, "sans pointeur, la section est perdue pour le lecteur"
    assert dst.name in reste, "le pointeur doit NOMMER le nouveau lieu"
    assert len(reste) < len(original), "le noyau resident doit avoir MAIGRI"

    # Comptabilite bout a bout : tout caractere de la section est dans la cible.
    _t, corps, _d, _f = frd.trouver(original, "Capacites d'execution")
    assert corps.strip() in cible


def test_un_deport_qui_FERAIT_GROSSIR_le_noyau_est_REFUSE(tmp_path):
    """Le but du deport est le budget : un pointeur plus cher que sa section
    retourne le geste contre lui-meme, en silence. Mesure 2026-09-19.
    """
    src, dst = _source(tmp_path, CORPUS), tmp_path / "docs" / "petit.md"
    with pytest.raises(SystemExit) as e:
        frd.deporter(src, "Capacites d'execution", dst, appliquer=True)
    motif = str(e.value)
    assert "FERAIT GROSSIR" in motif
    assert "plus gros que la section" in motif
    assert not dst.exists() and src.read_text(encoding="utf-8") == CORPUS

    # L'echappatoire existe, et elle est EXPLICITE (le budget n'est pas le seul but).
    assert frd.deporter(src, "Capacites d'execution", dst, appliquer=True,
                        meme_si_plus_gros=True) == 0
    assert dst.exists()


def test_le_pointeur_n_INVENTE_pas_ce_qui_reste_vrai(tmp_path):
    """Defaut mesure le 2026-09-19, en production sur `CLAUDE.md`.

    Les trois puces « ce qui reste vrai » etaient CODEES EN DUR — le resume de
    la section « Capacites d'execution » de RULES_SHARED. Deportee la section
    « Cartographie anatomique », le pointeur a donc affirme que la suite parlait
    de `hook_capability_gate` et de `forge_retrieval_sweep`. Rien de tout cela
    ne s'y trouve.

    Le controle `perdu == 0` etait VRAI pendant ce temps : il mesure la
    reconstitution de ce qui EST PARTI, jamais l'exactitude de ce qui RESTE. Un
    pointeur faux se lit comme un resume autorise — pire qu'un pointeur absent.
    """
    src = _source(tmp_path)
    dst = tmp_path / "deporte.md"
    # Corpus miniature : le garde « pointeur plus gros que la section » mord
    # ici a juste titre. Ce test porte sur le CONTENU du pointeur, pas sur le
    # budget — on neutralise le garde de budget, jamais celui de la perte.
    frd.deporter(src, "Capacites d'execution", dst, appliquer=True,
                 meme_si_plus_gros=True)
    noyau = src.read_text(encoding="utf-8")
    for mot in ("hook_capability_gate", "forge_retrieval_sweep",
                "capacite absente", "Ce qui reste vrai"):
        assert mot not in noyau, \
            "sans --resume, le pointeur ne doit RIEN affirmer : %r invente" % mot
    assert "DEPORTEE" in noyau and "deporte.md" in noyau, \
        "un pointeur sans resume reste un pointeur : le lien doit y etre"


def test_le_resume_FOURNI_est_celui_qui_est_ecrit(tmp_path):
    """Contre-epreuve du test precedent : fourni, le resume doit apparaitre TEL
    QUEL. Sans elle, un pointeur qui n'ecrirait jamais rien passerait aussi."""
    src = _source(tmp_path)
    dst = tmp_path / "deporte.md"
    frd.deporter(src, "Capacites d'execution", dst, appliquer=True,
                 resume=["la carte organe vit dans organ_map_full.json",
                         "le diagnostic passe par le skill forge-anatomy"],
                 meme_si_plus_gros=True)
    noyau = src.read_text(encoding="utf-8")
    assert "Ce qui reste vrai" in noyau
    assert "- la carte organe vit dans organ_map_full.json" in noyau
    assert "- le diagnostic passe par le skill forge-anatomy" in noyau
    assert "hook_capability_gate" not in noyau, \
        "aucun residu de l'ancien bloc code en dur"


def test_la_ligne_de_commande_EXIGE_un_resume(tmp_path):
    """Le chemin humain ne doit pas pouvoir deporter sans dire ce qui reste."""
    src = _source(tmp_path)
    with pytest.raises(SystemExit):
        frd.main(["--source", str(src), "--section", "Capacites d'execution",
                  "--vers", str(tmp_path / "d.md")])


def test_le_pointeur_annonce_le_VRAI_pourcentage(tmp_path):
    """Le premier jet ecrivait '52 %' en dur -- vrai pour une section, faux pour
    toutes les autres. Un chiffre en dur dans un gabarit est un mensonge differe.
    """
    src, dst = _source(tmp_path, GROS), tmp_path / "docs" / "DEPORTE.md"
    original = src.read_text(encoding="utf-8")
    _t, _c, debut, fin = frd.trouver(original, "Capacites d'execution")
    attendu = round(100.0 * (fin - debut) / len(original))

    frd.deporter(src, "Capacites d'execution", dst, appliquer=True)

    assert "%d%% de ce fichier" % attendu in src.read_text(encoding="utf-8")


def test_un_motif_ambigu_est_REFUSE_jamais_devine(tmp_path):
    src = _source(tmp_path, CORPUS.replace("Derniere section (2026-02-02)",
                                           "Capacités d'exécution bis (2026-02-02)"))
    with pytest.raises(SystemExit) as e:
        frd.deporter(src, "Capacites d'execution", tmp_path / "d.md", appliquer=True)
    assert "2 sections" in str(e.value)
    assert "Capacités d'exécution" in str(e.value), "nommer les candidates, sinon rien a corriger"


def test_un_motif_absent_est_REFUSE_en_listant_ce_qui_EXISTE(tmp_path):
    src = _source(tmp_path)
    with pytest.raises(SystemExit) as e:
        frd.deporter(src, "section qui n'existe pas", tmp_path / "d.md", appliquer=True)
    assert "aucune section" in str(e.value)
    assert "Premiere section" in str(e.value), "dire ce qui EST la, pas seulement ce qui manque"
    assert src.read_text(encoding="utf-8") == CORPUS


def test_une_cible_existante_n_est_JAMAIS_ecrasee(tmp_path):
    src, dst = _source(tmp_path), tmp_path / "deja.md"
    dst.write_text("un deport anterieur\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        frd.deporter(src, "Capacites d'execution", dst, appliquer=True)
    assert "existe deja" in str(e.value)
    assert dst.read_text(encoding="utf-8") == "un deport anterieur\n"
    assert src.read_text(encoding="utf-8") == CORPUS, "source intacte sur refus"


def test_un_fichier_hors_perimetre_est_REFUSE(tmp_path):
    p = tmp_path / "un_fichier_quelconque.md"
    p.write_text(CORPUS, encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        frd.deporter(p, "Capacites d'execution", tmp_path / "d.md", appliquer=True)
    assert "hors du perimetre" in str(e.value)


def test_le_titre_se_trouve_SANS_les_accents(tmp_path):
    """Un agent qui tape la commande ne reproduit pas toujours les diacritiques ;
    tolerer la SAISIE n'est pas tolerer l'ambiguite (cf. le test du motif ambigu).
    """
    src = _source(tmp_path)
    titre, _corps, _d, _f = frd.trouver(src.read_text(encoding="utf-8"),
                                        "capacites d execution".replace(" d ", " d'"))
    assert titre.startswith("## Capacités d'exécution")


def test_la_reconstitution_est_verifiee_AVANT_d_ecrire(tmp_path):
    """Le garde central, teste sur ses bornes : premiere et derniere section."""
    texte = _source(tmp_path).read_text(encoding="utf-8")
    for motif in ("Premiere section", "Capacites d'execution", "Derniere section"):
        titre, _c, debut, fin = frd.trouver(texte, motif)
        assert texte[:debut] + texte[debut:fin] + texte[fin:] == texte, titre
