"""Non-régression AH1 : la RÉCIDIVE se mesure par motif, pas en agrégat.

Item de veille AH1 : « mesurer la récidive avec les données déjà captées par
`forge_recurrence_audit` ». L'outil captait bien les données — il n'en tirait
pas la mesure qui porte son nom.

CE QU'IL FAISAIT, et pourquoi ça ne répond pas à la question :

    `tendance()` agrège **tous** les recadrages par mois, puis compare le
    PREMIER mois au DERNIER pour rendre EMPIRE / AMELIORE / STABLE.

Trois défauts, et ils se cumulent :

  1. **L'agrégat annule les mouvements opposés.** Un motif éteint et un motif
     qui explose se compensent exactement dans le total. Le verdict global peut
     rester « STABLE » pendant qu'un défaut précis empire tous les mois.

  2. **Deux points ne font pas une tendance.** Le dépôt a déjà payé la version
     douce de ce défaut : « la moyenne all-time MENT sur les rafales » — un
     débit médian sous budget masquant 14 intervalles en rafale. Ici c'est plus
     brutal : sur N mois de données, N-2 sont ignorés par le verdict.

  3. **Le dernier mois est presque toujours PARTIEL.** Comparer un mois de
     douze jours à des mois pleins, sans le dire, c'est comparer deux choses
     qui ne se comparent pas. Le nombre de sessions doit accompagner le taux,
     sinon un mois maigre pèse autant qu'un mois chargé.

CE QUE « RÉCIDIVE » VEUT DIRE, et qui n'était mesuré nulle part : un motif qui
revient **après une période de silence** n'est pas un motif toujours présent.
Le premier dit qu'on l'a cru mort ; le second est une dette ouverte jamais
traitée. Les confondre, c'est traiter les deux de la même façon — donc mal.

⚠️ Et l'état qu'on n'invente pas : un motif absent des données n'est pas
« résolu ». Il est **JAMAIS_VU**, ce qui peut tout aussi bien vouloir dire que
son détecteur ne mord pas. Classer par liste BLANCHE : n'est éteint que ce qui
a été VU puis ne l'est plus, jamais ce qu'on n'a pas su voir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_recurrence_audit  # type: ignore

    return forge_recurrence_audit


def _transcript(dossier: Path, nom: str, date: str, messages: list[str]) -> None:
    """Écrit un vrai transcript au format lu par `scan_sessions`.

    Volontairement un FICHIER, pas un dictionnaire : une fixture bâtie sur ma
    lecture du schéma valide ma lecture, pas l'émetteur. Ici on emprunte le
    chemin réel — le parseur de transcripts — et c'est lui qui doit rendre les
    motifs attribués.
    """
    lignes = []
    for i, m in enumerate(messages):
        lignes.append(json.dumps({
            "type": "user",
            "timestamp": f"{date}T1{i}:00:00.000Z",
            "message": {"content": m},
        }, ensure_ascii=False))
    (dossier / f"{nom}.jsonl").write_text("\n".join(lignes) + "\n", encoding="utf-8")


# Chacun de ces messages porte le vocabulaire d'un motif du catalogue.
_MOTIF_A = "tu as lu un acces refuse comme une absence, c'est illisible pas vide"
_MOTIF_B = "ton pid est mort mais already_running dit l'inverse, le registre ment"
_NEUTRE = "continue sur ce point et donne moi le detail technique complet stp"


def _sessions(tmp_path: Path, plan: dict[str, list[str]]) -> list[dict]:
    """{date: [motifs...]} -> sessions telles que `scan_sessions` les rend."""
    m = _mod()
    d = tmp_path / "projet"
    d.mkdir(exist_ok=True)
    for i, (date, motifs) in enumerate(sorted(plan.items())):
        msgs = list(motifs) + [_NEUTRE] * max(0, 6 - len(motifs))
        _transcript(d, f"sess{i:02d}aaaa", date, msgs)
    res = m.scan_sessions(d)
    assert res.get("etat") == "ok", res
    return res["sessions"]


# ── 1. Le chemin réel attribue les motifs ─────────────────────────────────────

def test_les_motifs_sont_attribues_a_la_session_qui_les_porte(tmp_path):
    """Sans attribution datée, aucune récidive n'est calculable : c'est la
    donnée manquante, pas l'algorithme."""
    sessions = _sessions(tmp_path, {"2026-05-03": [_MOTIF_A, _MOTIF_A]})
    assert sessions, "aucune session lue sur un transcript pourtant valide"
    s = sessions[0]
    assert "motifs" in s, (
        "scan_sessions ne rattache aucun motif a la session : les recadrages "
        "sont comptes en bloc, donc rien ne dit LEQUEL revient"
    )
    assert "invisible_lu_comme_absent" in s["motifs"], (
        "le motif present dans le texte owner n'est pas attribue : %s" % s["motifs"]
    )


# ── 2. Récidive ≠ chronique ≠ éteint ≠ jamais vu ──────────────────────────────

def test_un_motif_qui_revient_apres_un_silence_est_une_RECIDIVE(tmp_path):
    sessions = _sessions(tmp_path, {
        "2026-05-03": [_MOTIF_A],
        "2026-06-04": [_NEUTRE],
        "2026-07-05": [_NEUTRE],
        "2026-08-06": [_MOTIF_A],
    })
    r = _mod().recidive(sessions)
    par_cle = {x["cle"]: x for x in r["motifs"]}
    a = par_cle["invisible_lu_comme_absent"]
    assert a["etat"] == "RECIDIVE", (
        "un motif revenu apres deux mois de silence doit etre une RECIDIVE, "
        "pas une occurrence de plus : %s" % a
    )
    assert a["mois_de_silence"] >= 2, a


def test_un_motif_toujours_la_est_CHRONIQUE_pas_une_recidive(tmp_path):
    sessions = _sessions(tmp_path, {
        "2026-05-03": [_MOTIF_B],
        "2026-06-04": [_MOTIF_B],
        "2026-07-05": [_MOTIF_B],
        "2026-08-06": [_MOTIF_B],
    })
    r = _mod().recidive(sessions)
    par_cle = {x["cle"]: x for x in r["motifs"]}
    b = par_cle["statut_declare_vs_reel"]
    assert b["etat"] == "CHRONIQUE", (
        "un defaut jamais interrompu est une dette ouverte, pas une rechute — "
        "les confondre fait appliquer le mauvais remede : %s" % b
    )


def test_un_motif_jamais_vu_n_est_PAS_declare_resolu(tmp_path):
    """Liste BLANCHE : n'est éteint que ce qui a été VU puis ne l'est plus."""
    sessions = _sessions(tmp_path, {"2026-05-03": [_MOTIF_A]})
    r = _mod().recidive(sessions)
    par_cle = {x["cle"]: x for x in r["motifs"]}
    autres = [x for k, x in par_cle.items() if k != "invisible_lu_comme_absent"]
    assert autres, "catalogue de motifs vide : la mesure ne couvre rien"
    for x in autres:
        assert x["etat"] == "JAMAIS_VU", (
            "un motif absent des donnees est rendu « %s » : un detecteur muet "
            "se lirait comme un defaut corrige" % x["etat"]
        )


def test_sans_assez_de_mois_le_verdict_est_INDETERMINE(tmp_path):
    sessions = _sessions(tmp_path, {"2026-05-03": [_MOTIF_A]})
    r = _mod().recidive(sessions)
    par_cle = {x["cle"]: x for x in r["motifs"]}
    a = par_cle["invisible_lu_comme_absent"]
    assert a["etat"] in ("INDETERMINE", "VU_UNE_FOIS"), (
        "un seul mois de donnees ne permet aucun verdict de tendance : %s" % a
    )


# ── 3. La tendance globale ne repose plus sur deux points ─────────────────────

def test_la_tendance_declare_le_mois_partiel_et_son_volume(tmp_path):
    sessions = _sessions(tmp_path, {
        "2026-05-03": [_MOTIF_A], "2026-06-04": [_MOTIF_A],
        "2026-07-05": [_MOTIF_B], "2026-08-06": [_NEUTRE],
    })
    t = _mod().tendance(sessions)
    for l in t["par_mois"]:
        assert "sessions" in l and l["sessions"] >= 1
        assert "mois_complet" in l, (
            "un mois PARTIEL compare a des mois pleins sans le dire : le "
            "dernier mois est presque toujours incomplet"
        )
    v = t.get("verdict") or {}
    assert "mois_retenus" in v, (
        "le verdict compare toujours deux points (premier vs dernier mois) : "
        "sur 4 mois de donnees, 2 sont ignores"
    )
    assert v["mois_retenus"] >= 3, v


def test_un_mois_sans_session_n_est_pas_un_mois_sans_defaut(tmp_path):
    """Mesuré le 2026-09-12 sur les données réelles : 45 sessions réparties sur
    juin, août et septembre — **juillet est vide**. Si le silence se comptait en
    mois calendaires, un mois sans travail se lirait comme un mois sans défaut.
    `UNKNOWN ≠ NO`, appliqué à l'axe du temps."""
    sessions = _sessions(tmp_path, {
        "2026-05-03": [_MOTIF_A],
        "2026-08-06": [_MOTIF_A],
    })
    r = _mod().recidive(sessions)
    assert r["mois_sans_donnees"] == ["2026-06", "2026-07"], (
        "les mois sans aucune session ne sont pas nommes : le lecteur croira "
        "l'axe continu : %s" % r["mois_sans_donnees"]
    )
    a = {x["cle"]: x for x in r["motifs"]}["invisible_lu_comme_absent"]
    assert a["mois_de_silence"] == 0, (
        "le silence a ete compte sur des mois ou PERSONNE n'a travaille : "
        "deux mois vides fabriquent une fausse RECIDIVE (%s)" % a
    )


# ── 4. Le CHEMIN RÉEL, pas seulement les fonctions ────────────────────────────

def test_le_point_d_entree_affiche_la_recidive_sans_casser(tmp_path, capsys,
                                                           monkeypatch):
    """Déjà payé dans ce dépôt : `check()` passait ses tests pendant que
    `--check` mourait en `NameError`. Ici le risque est jumeau — `main()`
    formatait `verdict['ecart_points']`, une clé que la nouvelle tendance ne
    produit plus. Une fonction verte n'a jamais prouvé qu'un programme tourne."""
    m = _mod()
    d = tmp_path / "projet"
    d.mkdir(exist_ok=True)
    for i, (date, msgs) in enumerate(sorted({
        "2026-05-03": [_MOTIF_A], "2026-06-04": [_NEUTRE],
        "2026-07-05": [_NEUTRE], "2026-08-06": [_MOTIF_A],
    }.items())):
        _transcript(d, f"ent{i:02d}aaaa", date,
                    list(msgs) + [_NEUTRE] * max(0, 6 - len(msgs)))

    monkeypatch.setattr(sys, "argv", ["forge_recurrence_audit.py",
                                      "--sessions", str(d)])
    rc = m.main()
    sortie = capsys.readouterr().out
    assert rc == 0, "le point d'entree sort en erreur"
    assert "RECIDIVE PAR MOTIF" in sortie, (
        "la mesure existe mais n'est branchee sur aucune sortie : une capacite "
        "non cablee est une dette, jamais une mesure"
    )
    assert "invisible_lu_comme_absent" in sortie
    assert "JAMAIS_VU" in sortie, (
        "les motifs absents doivent rester VISIBLES et nommes : les taire "
        "ferait lire un detecteur muet comme un defaut corrige"
    )
