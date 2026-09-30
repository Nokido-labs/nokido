"""Non-regression : un keeper qui BAT n'atteste pas que son ORGANE repond.

Defaut mesure le 2026-08-25. `docker_keeper` battait depuis 11 s avec
`health: "idle"` et, dans son propre payload, `stats.daemon_up: false` accompagne de
`failed to connect to the docker API`. `llama_keeper` battait depuis 31 s avec
`gemma_up: false`. `audit_workers_heartbeat` ne calculait `alive` que sur l'AGE du
fichier : la cellule vivante valait certificat de sante pour l'organe, et le corps
voyait vert sur une dependance morte.

Le piege symetrique, evite de justesse : un organe eteint n'est une PANNE que si
quelqu'un le RECLAME. `docker.wanted` avait 159 731 s pour un TTL declare de 900 s --
perime depuis 44 heures. Accuser Docker aurait fabrique un faux positif de plus, et
un garde qui crie a faux finit desarme.

Ces tests portent sur l'EFFET : le corps accuse-t-il quand il le doit, et se tait-il
quand il le doit ? Un test qui verifierait seulement « le champ fonctionnel existe »
laisserait passer les deux erreurs.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_health_diagnostic as hd  # noqa: E402


def _audit(workers: dict) -> dict:
    """Un corps sain ou seuls les workers varient."""
    return {
        "rag_chunks": {"pct_vectorized": 99.0, "non_vectorized": 0,
                       "duplicate_hashes": 0},
        "biblio": {"topics_total": 1, "raw_by_status": {}},
        "messages": {"agent_messages_pct_unread": 0.0, "agent_messages_total": 10},
        "lessons": {"solutions_total": 1, "errors_total": 0, "lessons_last_24h": 0},
        "db_size": {"size_mb_main": 100.0},
        "tables_empty": {"empty_tables": []},
        "workers_heartbeat": workers,
        "services_http": {},
        "supervised_fleet": {"dead": [], "drift": [], "orphans": []},
        "constants": {"LAFORGE_PYTHON_path_exists": True,
                      "LAFORGE_ADMIN_TOKEN_set": True, "FORGE_MCP_TOKEN_set": True},
        "provider_keys": {"broken": []},
        "imports": {"broken": []},
        "journal_timestamps": {"scanned": 1, "undated": []},
        "host_vitals": {"ok": True, "ram_pct": 50.0, "disk_pct": 50.0,
                        "tdr_recent": 0,
                        "ram_pct_1h": {"min": 40.0, "max": 60.0, "avg": 50.0}},
        "identification": {"lisible": True, "part_pct": 0.0, "total_1h": 10,
                           "anonymes_1h": 0, "agents": {}, "emetteurs": []},
    }


def _keeper(fonctionnel, intention, motif="daemon_up=false"):
    return {"gardien": {"present": True, "alive": True, "age_s": 11,
                        "fonctionnel": fonctionnel, "fonctionnel_motif": motif,
                        "intention_fraiche": intention}}


# ------------------------------------------------- cellule vivante / organe mort

def test_organe_mort_et_reclame_est_accuse():
    """Le defaut d'origine : un keeper frais servait de certificat de sante."""
    score, gaps = hd.compute_score_and_gaps(_audit(_keeper(False, True)))
    assert any("CELLULE VIVANTE, ORGANE MORT" in g for g in gaps), gaps
    assert score < hd.compute_score_and_gaps(_audit({}))[0]


def test_organe_mort_mais_NON_reclame_nest_pas_accuse():
    """Le faux positif evite. `docker.wanted` etait perime depuis 44 h : un organe
    que personne ne demande n'est pas en panne, il obeit."""
    temoin, _ = hd.compute_score_and_gaps(_audit({}))
    score, gaps = hd.compute_score_and_gaps(_audit(_keeper(False, False)))
    assert score == temoin, "un organe au repos fait perdre des points"
    assert any("conforme à l'intention" in g for g in gaps), gaps
    assert not any("ORGANE MORT" in g for g in gaps)


def test_intention_illisible_ne_tranche_ni_dans_un_sens_ni_dans_lautre():
    """Trois etats, jamais deux : ne pas savoir si l'organe est reclame n'autorise
    ni a l'accuser, ni a le declarer conforme."""
    temoin, _ = hd.compute_score_and_gaps(_audit({}))
    score, gaps = hd.compute_score_and_gaps(_audit(_keeper(False, None)))
    assert score == temoin
    assert any("INTENTION ILLISIBLE" in g for g in gaps), gaps


def test_un_organe_qui_repond_ne_produit_aucune_alerte():
    """Temoin : le garde doit se taire quand tout va bien, sinon on l'ignore."""
    _score, gaps = hd.compute_score_and_gaps(_audit(_keeper(True, True, "gemma_up=true")))
    assert not any(("ORGANE MORT" in g or "conforme à l'intention" in g) for g in gaps)


# ----------------------------------------------------- lecture du payload keeper

def test_letat_de_lorgane_est_lu_dans_un_niveau_imbrique():
    """`docker_keeper` publie `stats.daemon_up`, pas `daemon_up` a la racine."""
    fonc, motif = hd._verdict_fonctionnel(
        {"health": "idle", "stats": {"daemon_up": False, "error": "npipe refuse"}})
    assert fonc is False
    assert "daemon_up=false" in motif and "npipe refuse" in motif


def test_un_payload_sans_etat_dorgane_rend_none_jamais_false():
    """« Je n'ai pas pu voir » n'est pas « l'organe est mort » — c'est la difference
    entre un capteur et une accusation."""
    fonc, motif = hd._verdict_fonctionnel({"health": "idle", "iter": 190})
    assert fonc is None
    assert "aucun etat" in motif


def test_un_payload_illisible_rend_none():
    assert hd._verdict_fonctionnel("2026-08-25T19:18:02+00:00")[0] is None
    assert hd._verdict_fonctionnel(None)[0] is None


def test_un_heartbeat_illisible_nest_pas_declare_mort():
    """Six heartbeats du bac a sable ne sont pas du JSON : deux portent une date ISO
    nue, un n'est que des octets NUL. Les declarer morts fabriquerait des pannes a
    partir d'un defaut de FORMAT."""
    temoin, _ = hd.compute_score_and_gaps(_audit({}))
    illisible = {"x": {"present": True, "alive": None, "err": "JSONDecodeError"}}
    score, gaps = hd.compute_score_and_gaps(_audit(illisible))
    assert score == temoin, "un heartbeat illisible fait perdre des points"
    assert any("ILLISIBLE" in g and "FORMAT" in g for g in gaps), gaps


# ------------------------------------------------------------ drapeau d'intention

def test_lintention_se_juge_sur_le_mtime_pas_sur_le_contenu(monkeypatch, tmp_path):
    """Les quatre drapeaux mesures portent QUATRE formats — float nu, JSON, fichier
    VIDE, prose. Un parseur de contenu casserait sur trois d'entre eux."""
    monkeypatch.setattr(hd, "SANDBOX", tmp_path)
    for nom, contenu in (("a", "1787525813.72"), ("b", json.dumps({"ts": 1.0})),
                         ("c", ""), ("d", "Arme le capteur SNN, pose le 2026-08-04")):
        (tmp_path / f"{nom}.wanted").write_text(contenu, encoding="utf-8")
        assert hd._intention_fraiche(nom) is True, nom


def test_un_drapeau_perime_ne_vaut_pas_intention(monkeypatch, tmp_path):
    monkeypatch.setattr(hd, "SANDBOX", tmp_path)
    p = tmp_path / "vieux.wanted"
    p.write_text("x", encoding="utf-8")
    vieux = time.time() - (hd._INTENTION_TTL_S + 60)
    import os

    os.utime(p, (vieux, vieux))
    assert hd._intention_fraiche("vieux") is False


def test_un_drapeau_absent_vaut_absence_dintention(monkeypatch, tmp_path):
    monkeypatch.setattr(hd, "SANDBOX", tmp_path)
    assert hd._intention_fraiche("jamais_pose") is False


# ------------------------------------- import garde vs reference morte

def test_un_import_garde_nest_pas_compte_comme_une_regression(monkeypatch, tmp_path):
    """Mesure 2026-08-25 : un `forge_*` importé sous `try` avec un repli (capacité
    optionnelle/déportée) ne doit PAS être compté comme une référence morte — un
    garde qui accuse un choix d'architecture finit désarmé.

    Testé sur un faux ROOT hermétique : l'exemple historique était l'import
    `forge_exegol_supervisor` de `forge_mcp_registry`, retiré du cœur lors de la
    purge offensive du 2026-09-01. On garde le MÉCANISME (classer, ne pas
    supprimer), indépendamment de tout import réel qui va et vient."""
    app = tmp_path / "app"
    app.mkdir()
    (tmp_path / "tools").mkdir()
    # capacité optionnelle : import sous try + handler
    (app / "mod_optionnel.py").write_text(
        "try:\n"
        "    import forge_capacite_deportee_xyz  # noqa: F401\n"
        "except Exception:\n"
        "    forge_capacite_deportee_xyz = None\n",
        encoding="utf-8")
    # référence morte : import top-level d'un forge_* inexistant
    (app / "mod_mort.py").write_text(
        "import forge_reference_morte_xyz  # noqa: F401\n", encoding="utf-8")

    monkeypatch.setattr(hd, "ROOT", tmp_path)
    r = hd.audit_import_resolvability()
    noms_morts = {b["missing"] for b in r["broken"]}
    noms_opt = {b["missing"] for b in r["optionnels"]}

    assert "forge_capacite_deportee_xyz" in noms_opt, (
        "un import garde sous try a ete compte comme une regression")
    assert "forge_capacite_deportee_xyz" not in noms_morts
    assert "forge_reference_morte_xyz" in noms_morts, (
        "une vraie reference morte doit rester detectee")


def test_une_capacite_optionnelle_ne_coute_aucun_point():
    temoin, _ = hd.compute_score_and_gaps(_audit({}))
    a = _audit({})
    a["imports"] = {"broken": [],
                    "optionnels": [{"file": "x.py", "missing": "forge_absent"}]}
    score, gaps = hd.compute_score_and_gaps(a)
    assert score == temoin
    assert any("OPTIONNELLE" in g for g in gaps), gaps


def test_un_import_NU_qui_ne_resout_pas_reste_une_regression():
    """Temoin indispensable : classer n'est pas absoudre. Sans ce test, on aurait pu
    faire taire le scanner entier au lieu de lui apprendre a distinguer."""
    temoin, _ = hd.compute_score_and_gaps(_audit({}))
    a = _audit({})
    a["imports"] = {"broken": [{"file": "x.py", "missing": "forge_absent"}],
                    "optionnels": []}
    score, gaps = hd.compute_score_and_gaps(a)
    assert score < temoin
    assert any("import(s) Nokido mort" in g for g in gaps), gaps
