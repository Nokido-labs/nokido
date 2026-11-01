"""NR -- les regles de la memoire de session sont MESUREES contre le corps DISTRIBUE (owner 21/10).

Owner, 21/10 : « toutes les decisions qui font appel a la memoire de nos echanges doivent etre notifiees en base, sinon
les versions distribuables ne vont jamais trouver le fonctionnement » ; puis « oulala ca veut dire que plein de regles
de fonctionnement vont echapper a un CLI agnostique ? il faut combler absolument ce manque ». Mesure du 21/10 : la
memoire de Claude (feedback, decisions, gotchas, references) n'est NI suivie dans alpha NI livree dans le dist ; elle est
versee au RAG LOCAL seulement (783 sources `memory:<fiche>`, domaine episodic_memory). Exemple paye : la route du tray
(commande-faite) n'etait connue que d'elle (corrige 0d72726c1).

Extension de tools/forge_intent_verifier.py (son moteur ANCRE/PRESENT/PARTIEL/ABSENT, pas un second outil) :
  1. regles_de_la_memoire(lignes) : [(source, texte)] -> une regle par fiche `memory:<nom>` (textes concatenes) ;
     ecartees : MEMORY (l'index), index_*, reprise_* (journaux, pas des regles) -- et le nombre d'ecartees est DIT ;
  2. index_de(fichiers) : {chemin: texte} -> (idx, nfic), le meme index que _index() mais sur une liste DONNEE ;
  3. ancrage_memoire(regles, fichiers_distribues) -> {"verdicts": [...], "compte": {...}, "ecartees": n} : une regle
     n'est jugee que contre les fichiers DISTRIBUES ; une fiche memoire n'est jamais sa propre preuve.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_intent_verifier as V  # noqa: E402

LIGNES = [
    ("memory:feedback_tray_route", "Retirer une commande du tray : demander_ordre ordre=commande_faite_xyz "
                                   "cible=cmd_abc ; forme mesuree commande_faite_xyz."),
    ("memory:feedback_tray_route", "Suite de la fiche : commande_faite_xyz rend FAITE."),
    ("memory:gotcha_inconnu", "Le piege zorglub_qwerty_frobnique ne figure nulle part ailleurs ; zorglub_qwerty_frobnique."),
    ("memory:MEMORY", "index"),
    ("memory:index_deporte_2026-10-21", "liste"),
    ("memory:reprise_2026-10-20_matin", "journal"),
]


def test_regles_de_la_memoire_une_par_fiche_et_ecartees_dites():
    regles, ecartees = V.regles_de_la_memoire(LIGNES)
    assert sorted(r["source"] for r in regles) == ["memory:feedback_tray_route", "memory:gotcha_inconnu"]
    tray = [r for r in regles if r["source"] == "memory:feedback_tray_route"][0]
    assert "rend FAITE" in tray["texte"]
    assert ecartees == 3


def test_ancrage_contre_le_seul_corps_distribue():
    regles, _ = V.regles_de_la_memoire(LIGNES)
    distribues = {
        "docs/skills/forge-hub/SKILL.md": "Cycle du tray : ordre=commande_faite_xyz cible=cmd_abc, rend FAITE.",
        "app/forge_ordres_bureau.py": "if ordre == 'commande_faite_xyz': return marquer(cible)  # cmd_abc",
    }
    for i in range(12):
        distribues["docs/autre_%d.md" % i] = "texte neutre numero %d sans rapport" % i
    r = V.ancrage_memoire(regles, distribues)
    par = {v["source"]: v["verdict"] for v in r["verdicts"]}
    assert par["memory:feedback_tray_route"] in ("ANCRE", "PRESENT")
    assert par["memory:gotcha_inconnu"] == "ABSENT"
    assert r["compte"]["ABSENT"] == 1


def test_deux_termes_dans_un_gros_fichier_n_ancrent_pas_une_longue_regle():
    # 30/10 : 750/750 ANCRE sur 6 452 fichiers -- CHANGELOG.md ou app/Nokido.py portaient deux termes rares de
    # n'importe quelle fiche. Une regle longue n'est ancree que si un fichier porte une PART de ses termes rares.
    lignes = [("memory:feedback_longue", "regle alpha_un beta_deux gamma_trois delta_quatre epsilon_cinq zeta_six "
                                         "eta_sept theta_huit iota_neuf kappa_dix lambda_onze mu_douze")]
    regles, _ = V.regles_de_la_memoire(lignes)
    distribues = {"CHANGELOG.md": "alpha_un et beta_deux au passage, rien d'autre"}
    for i in range(12):
        distribues["docs/autre_%d.md" % i] = "texte neutre %d" % i
    r = V.ancrage_memoire(regles, distribues)
    assert r["verdicts"][0]["verdict"] == "PARTIEL"
    distribues["docs/vraie_regle.md"] = "alpha_un beta_deux gamma_trois delta_quatre epsilon_cinq"
    r = V.ancrage_memoire(regles, distribues)
    assert r["verdicts"][0]["verdict"] == "ANCRE"


def test_une_fiche_memoire_n_est_jamais_sa_propre_preuve():
    regles, _ = V.regles_de_la_memoire(LIGNES)
    distribues = {"memory/gotcha_inconnu.md": "zorglub_qwerty_frobnique zorglub_qwerty_frobnique"}
    for i in range(12):
        distribues["docs/autre_%d.md" % i] = "texte neutre %d" % i
    r = V.ancrage_memoire(regles, distribues)
    par = {v["source"]: v["verdict"] for v in r["verdicts"]}
    assert par["memory:gotcha_inconnu"] == "ABSENT"
