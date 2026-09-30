"""Non-regression : la memoire de travail du corps, et ses trois regles.

Defaut d'origine, mesure le 2026-08-25 : la memoire injectee aux clients etait
choisie UNE FOIS a la minute zero par `ORDER BY rowid DESC LIMIT 4` - la recence
d'INSERTION -, le canal par tour n'injectait aucune memoire, et la zone `active_bugs`
(29 faits, le registre des dettes) n'etait lue par personne. Une dette non tenue
depuis 72 jours y valait une confiance de 0.001 : elle s'eteignait au lieu de crier.

Consequence payee le jour meme : un defaut diagnostique a 10 h a ete oublie jusqu'a
22 h DANS LA MEME SESSION, contexte intact. Une obligation sans porteur.

Ces tests portent sur l'EFFET. Hermetiques : le registre est double, rien n'est lu
ni ecrit dans le blackboard reel.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_memoire_active as mem  # noqa: E402


def _fait(cle, valeur, age_jours, trust=0.9):
    return {"key": cle, "value": valeur, "age_days": age_jours, "trust": trust,
            "worker_id": "TEST"}


@pytest.fixture()
def registre(monkeypatch):
    """Double le registre de dettes : aucun acces au blackboard reel."""
    boite = {"faits": []}

    def _faux_read_zone(zone, **kw):
        return {"zone": zone, "facts": boite["faits"]}

    import forge_swarm_blackboard as bb

    monkeypatch.setattr(bb, "read_zone", _faux_read_zone)
    return boite


# ------------------------------------------------------- salience inversee

def test_une_dette_ancienne_domine_une_dette_recente(registre):
    """Le coeur du correctif. Le blackboard fait DECROITRE la confiance avec l'age -
    juste pour une observation, faux pour une obligation : une dette non tenue
    s'aggrave. Sans cette inversion, la dette de 72 jours reste invisible."""
    registre["faits"] = [_fait("recente", "bug d hier", 1.0),
                         _fait("ancienne", "bug de deux mois", 72.0)]
    entrees, _ = mem.dettes_ouvertes()
    assert entrees[0]["texte"].startswith("ancienne"), [e["texte"] for e in entrees]
    assert entrees[0]["salience"] > entrees[1]["salience"]


def test_la_salience_croit_avec_lage_apres_le_creux():
    a, b, c = (mem.salience_dette(x) for x in (1.0, 10.0, 70.0))
    assert a < b < c


def test_une_dette_du_jour_crie_aussi_fort_quune_dette_de_dix_jours():
    """Defaut trouve A LA MISE EN SERVICE : avec une salience purement croissante,
    les cinq dettes inscrites le jour meme se rangeaient DERNIERES, donc invisibles -
    le registre ne servait plus a ce pour quoi il venait d'etre construit. Le corps
    connait deux douleurs : l'AIGUE, forte a l'inscription, et la CHRONIQUE, qui croit
    avec le temps non tenu. Le creux tombe au milieu, la ou une obligation se perd."""
    fraiche = mem.salience_dette(0.0)
    creux = mem.salience_dette(1.0)
    ancienne = mem.salience_dette(70.0)
    assert fraiche > creux, "une dette du jour est plus faible que le creux"
    assert ancienne > fraiche, "la chronicite doit finir par dominer"
    assert fraiche > mem.salience_dette(6.0)


def test_une_dette_fraiche_garde_sa_place_derriere_les_anciennes(registre):
    """Une douleur aigue doit etre entendue meme quand une chronique hurle plus fort."""
    registre["faits"] = [_fait("vieille%d" % i, "x", 60.0 + i) for i in range(5)]
    registre["faits"].append(_fait("de_ce_soir", "inscrite a l instant", 0.0))
    entrees, _ = mem.dettes_ouvertes(limit=3)
    textes = " ".join(e["texte"] for e in entrees)
    assert "de_ce_soir" in textes, textes


def test_rafraichir_une_dette_nefface_pas_sa_chronicite():
    """Defaut trouve a la mise en service : reactualiser une dette de 52 jours avec
    la mesure du jour remettait son `age_days` a 0, effacant la CHRONICITE - c'est-a
    dire exactement le signal que cet organe existe pour preserver."""
    recent = {"key": "x", "value": "[OUVERT 2026-08-25T22:45:22 depuis=2026-07-04] ...",
              "age_days": 0.0}
    assert mem._age_reel(recent) > 40.0
    sans_marque = {"key": "x", "value": "constat brut", "age_days": 12.0}
    assert mem._age_reel(sans_marque) == 12.0


def test_une_date_dorigine_illisible_retombe_sur_le_registre():
    """Trois etats : on ne fabrique pas un age a partir d'une date qu'on ne sait pas
    lire, on retombe sur la mesure du registre."""
    bancal = {"key": "x", "value": "[OUVERT ... depuis=pas-une-date] ...",
              "age_days": 7.0}
    assert mem._age_reel(bancal) == 7.0


# ------------------------------------------------------------ cloture

def test_une_dette_close_disparait_du_rappel(registre):
    registre["faits"] = [_fait("faite", "[CLOS 2026-08-25T22:00:00] preuve=commit abc",
                               50.0),
                         _fait("ouverte", "encore a faire", 2.0)]
    entrees, _ = mem.dettes_ouvertes()
    assert len(entrees) == 1
    assert entrees[0]["texte"].startswith("ouverte")


def test_la_prose_heritee_est_reconnue_comme_close(registre):
    """Les dettes anterieures a cet organe n'ont pas d'etat structure : elles disent
    RESOLU ou RETRACTE en prose. On les lit au mieux plutot que de les compter
    ouvertes a tort - 29 faits existaient deja quand l'organe a ete ecrit."""
    registre["faits"] = [_fait("vieille", "RESOLU ET VERIFIE EN PRODUCTION", 11.0)]
    entrees, _ = mem.dettes_ouvertes()
    assert entrees == []


def test_clore_exige_et_conserve_une_preuve(monkeypatch, registre):
    """Une commande acceptee n'est pas un effet obtenu - meme exigence que la
    post-condition posee sur le watchdog le meme jour."""
    ecrits = {}

    def _faux_write(zone, cle, val, cat, **kw):
        ecrits.update({"zone": zone, "cle": cle, "val": val})
        registre["faits"] = [{"key": cle, "value": val, "age_days": 0.0}]
        return None  # comme le vrai : il ne rend RIEN

    import forge_swarm_blackboard as bb

    monkeypatch.setattr(bb, "_write_fact", _faux_write)
    r = mem.clore_dette("x", "suite pure rc=0 sur 97 fichiers")
    assert ecrits["val"].startswith(mem.MARQUEUR_CLOS)
    assert "preuve=suite pure rc=0" in ecrits["val"]
    assert r["ok"] is True, r


def test_une_cloture_sans_preuve_est_refusee():
    """Clore sur declaration seule reproduirait le defaut qu'on vient de corriger
    partout ailleurs dans le corps."""
    r = mem.clore_dette("x", "   ")
    assert r["ok"] is False and "preuve" in r["raison"]


def test_une_inscription_qui_ne_prouve_rien_le_DIT(monkeypatch, registre):
    """`_write_fact` rend `None` : sans relecture, `ouvrir_dette` rendait `None` et
    l'appelant ne pouvait pas distinguer l'ecriture reussie du silence. C'est le
    defaut meme que cet organe combat, dans le code qui le combat."""
    import forge_swarm_blackboard as bb

    monkeypatch.setattr(bb, "_write_fact", lambda *a, **k: None)
    registre["faits"] = []  # l'ecriture n'a rien produit
    r = mem.ouvrir_dette("fantome", "quelque chose")
    assert r["ok"] is False
    assert "absente" in r["raison"]


# --------------------------------------------- les trois regles de l'organe

def test_une_strate_qui_na_pas_pu_regarder_le_DIT(registre, monkeypatch):
    """Regle 1. « Je n'ai rien vu » n'est pas « il n'y a rien » - le defaut le plus
    cher du corps, mesure sur 268 aveux d'erreur."""
    import forge_swarm_blackboard as bb

    def _refuse(zone, **kw):
        raise PermissionError("acces refuse")

    monkeypatch.setattr(bb, "read_zone", _refuse)
    entrees, note = mem.dettes_ouvertes()
    assert entrees == []
    assert note and "refusee" in note


def test_une_strate_vide_ne_disparait_pas_du_rendu():
    """Regle 1 appliquee au RENDU : ma premiere version faisait disparaitre la strate
    `longue` quand elle ne trouvait rien, rendant son silence indiscernable d'une
    panne. Mesure et corrige dans le meme tour."""
    proj = {"strates": {n: [] for n in mem.STRATES}, "non_vu": {}, "ecarte": 0}
    proj["non_vu"]["longue"] = "aucun rappel sur ces termes (corpus, pas panne)"
    rendu = mem.rendre(proj)
    assert "longue" in rendu and "corpus, pas panne" in rendu


def test_ce_qui_est_ecarte_par_le_budget_est_compte(registre):
    """Regle 2. Un filtre muet fait passer une projection tronquee pour complete."""
    registre["faits"] = [_fait("d%d" % i, "x" * 60, float(i)) for i in range(1, 12)]
    _entrees, note = mem.dettes_ouvertes(limit=3)
    assert note and "NON affichee" in note and "8" in note


def test_chaque_entree_porte_sa_provenance(registre):
    """Regle 3. Une memoire sans provenance ne peut pas etre refutee."""
    registre["faits"] = [_fait("a", "quelque chose", 3.0)]
    entrees, _ = mem.dettes_ouvertes()
    assert entrees[0]["source"] == "blackboard/active_bugs"
    assert entrees[0]["age_s"] is not None


# ------------------------------------------------------------- projection

def test_le_budget_sacrifie_le_rappel_avant_les_dettes(registre, monkeypatch):
    """Une dette RECLAME, un rappel PROPOSE. Sous contrainte, c'est le rappel qui
    saute - sinon le budget ferait taire exactement ce qu'on vient de rendre audible."""
    registre["faits"] = [_fait("dette", "y" * 150, 40.0)]
    monkeypatch.setattr(mem, "_longue",
                        lambda i, limit=3: ([mem._entree("z" * 150, "keeper/find")], None))
    monkeypatch.setattr(mem, "_courte", lambda i, limit=3: ([], None))
    monkeypatch.setattr(mem, "_introspective", lambda i, limit=4: ([], None))
    monkeypatch.setattr(mem, "_proprioceptive", lambda limit=4: ([], None))
    proj = mem.projeter("peu importe", budget_chars=200)
    assert proj["strates"]["immediate"], "la dette a ete sacrifiee avant le rappel"
    assert proj["strates"]["longue"] == []
    assert proj["ecarte"] >= 1


def test_la_projection_annonce_son_cout(registre):
    """Cet organe tourne a chaque tour : son cout doit etre mesurable par celui qui
    le paie, pas suppose."""
    registre["faits"] = []
    proj = mem.projeter("watchdog")
    assert isinstance(proj["cout_ms"], float)
    assert set(proj["strates"]) | set(proj["non_vu"]) >= set(mem.STRATES)
