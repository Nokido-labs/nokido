"""NR -- aucune demande owner ne se perd (owner 17/10 : « a l'avenir aucune demande ne doit se perdre, ancre le ! »).

Mesure du 17/10 (point total) : des demandes owner sans AUCUNE trace dans le code ni suivi au SSoT -- dont la passe
d'efficacite vers le natif, decidee le 16/10 et jamais profilee. Le verificateur existant (tools/forge_intent_verifier.py)
confrontait les demandes au CODE seulement, n'inscrivait rien et n'avait aucun declencheur. Et une zone ordinaire du
tableau noir est ELAGUEE (TTL + plafond, forge_swarm_blackboard._prune) : un registre range dans une zone ordinaire
perdrait les demandes par construction. Forme executable : zone perenne `demandes_owner`, reconciliation code x SSoT,
inscription idempotente par empreinte de la phrase, passe nocturne NREM1.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_swarm_blackboard as B  # noqa: E402
from nokido_agent.tools import forge_intent_verifier as V  # noqa: E402

SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"
# Phrase ABSURDE, a dessein : tests/ est indexe par le verificateur ; une vraie demande ecrite ici passerait pour
# tracee dans le code (auto-contamination deja payee le 12/08, cf. _SKIP du verificateur).
ARBRE = "il faut que le zorglub repeigne les quokkas en mauve chaque mardi"


def _d(texte=ARBRE, verdict="ABSENT", **kw):
    return {"texte": texte, "occurrences": 1, "verdict": verdict, **kw}


def test_la_zone_des_demandes_n_est_jamais_elaguee():
    assert "demandes_owner" in B._ZONES_PERENNES


def test_une_demande_sans_trace_ni_suivi_est_orpheline():
    assert [o["texte"] for o in V.demandes_sans_suivi([_d()], suivis=[])] == [ARBRE]


def test_une_trace_faible_sans_suivi_reste_orpheline():
    assert len(V.demandes_sans_suivi([_d(verdict="PARTIEL")], suivis=[])) == 1


def test_une_demande_ancree_dans_le_code_n_est_pas_orpheline():
    assert V.demandes_sans_suivi([_d(verdict="ANCRE"), _d(verdict="PRESENT")], suivis=[]) == []


def test_une_demande_suivie_au_ssot_n_est_pas_orpheline():
    suivis = [{"cle": "roadmap_p1_zorglub_quokkas", "statut": "ouvert",
               "titre": "P1: le zorglub repeint les quokkas en mauve"}]
    assert V.demandes_sans_suivi([_d()], suivis) == []


def test_une_demande_recouverte_par_une_plus_recente_n_est_pas_comptee():
    assert V.demandes_sans_suivi([_d(recouverte_par="refais le point total")], []) == []


def test_une_demande_deja_inscrite_compte_comme_suivie():
    """La zone demandes_owner est elle-meme un suivi : pas de doublon, et un [CLOS] pose sur le fait la ferme."""
    suivis = [{"cle": V.cle_demande(ARBRE), "statut": "ouvert", "titre": "[A TRIER 2026-10-17] autre libelle",
               "registre": True}]
    assert V.demandes_sans_suivi([_d()], suivis) == []


def test_un_fait_du_registre_ne_vaut_suivi_que_par_sa_cle():
    """Apparier par les MOTS le texte d'une demande inscrite ferait passer pour suivie toute demande voisine."""
    voisin = [{"cle": V.cle_demande("autre phrase"), "statut": "ouvert", "registre": True,
               "titre": "[A TRIER 2026-10-17] « il faut que le zorglub repeigne les quokkas en mauve »"}]
    assert len(V.demandes_sans_suivi([_d()], voisin)) == 1


def test_un_registre_illisible_arrete_la_passe(monkeypatch, tmp_path):
    """Inscrire sans avoir lu le registre ecraserait les marqueurs de tri ([CLOS] -> [A TRIER])."""
    monkeypatch.setattr(V, "_enonces", lambda: [{"texte": ARBRE, "occurrences": 1, "vu_le": None, "revu_le": None}])
    monkeypatch.setattr(V, "_enonces_captures", lambda: [])
    monkeypatch.setattr(V, "_index", lambda: ({}, 100))

    def illisible():
        raise OSError("base verrouillee")

    monkeypatch.setattr(V, "_suivis_ssot", illisible)
    ecrits = []
    monkeypatch.setattr(V, "_ecrire_fait", lambda zone, fact, **kw: ecrits.append(zone) or {"ok": True})
    monkeypatch.setattr(V, "REGISTRE", tmp_path / "registre.json")
    monkeypatch.setattr(sys, "argv", ["forge_intent_verifier.py", "--registre"])
    assert V.main() == 2 and ecrits == []


def test_inscription_idempotente_par_empreinte_de_la_phrase():
    ecrits = []

    def ecrire(zone, fact, **kw):
        ecrits.append((zone, kw.get("key"), fact))
        return {"ok": True}

    d = [_d(vu_le="2026-10-17T10:00:00", revu_le="2026-10-17T11:00:00")]
    V.inscrire_demandes(d, ecrire=ecrire)
    V.inscrire_demandes(d, ecrire=ecrire)
    assert len(ecrits) == 2 and len({k for _, k, _ in ecrits}) == 1
    zone, cle, fait = ecrits[0]
    assert zone == "demandes_owner" and cle == V.cle_demande(ARBRE) and cle.startswith("demande_")
    assert fait.startswith("[A TRIER") and ARBRE in fait


def test_une_demande_recue_par_une_autre_surface_entre_au_registre(monkeypatch, tmp_path):
    """Owner 17/10 : « ces outils doivent pouvoir en entree fonctionner sur d'autres cli aussi, tu n'es qu'un client
    parmi d'autres ». Un tour owner capture en direct par N'IMPORTE QUEL client (cli_capture_lib -> agent_messages,
    from_agent cli_<surface>) compte, sans attendre son ingestion au RAG ; un tour assistant ne compte jamais."""
    import json
    import sqlite3
    db = tmp_path / "m2m.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE agent_messages (id TEXT, from_agent TEXT, to_agent TEXT, correlation_id TEXT, "
                "method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    for i, (surface, role) in enumerate((("cli_gemini", "user"), ("cli_opencode", "user"), ("cli_claude", "assistant"))):
        con.execute("INSERT INTO agent_messages VALUES (?,?,?,?,?,?,?,?)",
                    (str(i), surface, "cli_capture", "s", "conversation.turn",
                     json.dumps({"role": role, "content": ARBRE + "."}), "unread", "2026-10-17T11:%02d:00" % i))
    con.commit()
    con.close()
    monkeypatch.setattr(V, "_capture_db", lambda: db)
    [e] = V._enonces_captures()
    assert e["texte"] == ARBRE and e["occurrences"] == 2, e
    assert set(e["surfaces"]) == {"cli_gemini", "cli_opencode"}


def test_une_demande_datee_en_epoch_et_en_iso_se_fusionne_sans_planter():
    """Le RAG date ses tours en epoch (entier), la capture en ISO : mesure du 17/10, le premier passage a plante
    (TypeError) en formatant une date entiere ; comparer les deux formats planterait la fusion."""
    rag = [{"texte": ARBRE, "occurrences": 2, "vu_le": 1792000000, "revu_le": 1792100000}]
    direct = [{"texte": ARBRE, "occurrences": 1, "vu_le": "2026-10-17T11:00:00", "revu_le": "2026-10-17T11:00:00",
               "surfaces": ["cli_gemini"]}]
    [e] = V._fusionner(rag, direct)
    assert e["occurrences"] == 3 and e["surfaces"] == ["cli_gemini"]
    assert e["vu_le"] == 1792000000 and e["revu_le"] > 1792100000
    ecrits = []
    V.inscrire_demandes([dict(e, verdict="ABSENT")], ecrire=lambda z, f, **kw: ecrits.append(f) or {"ok": True})
    assert "2026-10" in ecrits[0], ecrits[0]


def test_le_point_d_entree_registre_traverse(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "_enonces", lambda: [{"texte": ARBRE, "occurrences": 2, "vu_le": None, "revu_le": None}])
    monkeypatch.setattr(V, "_enonces_captures", lambda: [{"texte": ARBRE, "occurrences": 1, "vu_le": None,
                                                         "revu_le": None, "surfaces": ["cli_gemini"]}])
    monkeypatch.setattr(V, "_index", lambda: ({}, 100))
    monkeypatch.setattr(V, "_suivis_ssot", lambda: [])
    ecrits = []
    monkeypatch.setattr(V, "_ecrire_fait", lambda zone, fact, **kw: ecrits.append((zone, kw.get("key"))) or {"ok": True})
    monkeypatch.setattr(V, "REGISTRE", tmp_path / "registre.json")
    monkeypatch.setattr(sys, "argv", ["forge_intent_verifier.py", "--registre"])
    assert V.main() == 0
    assert ("demandes_owner", V.cle_demande(ARBRE)) in ecrits
    assert ("demandes_owner", "resume_registre") in ecrits, "le resume du registre est le signal lu par les surfaces"
    assert (tmp_path / "registre.json").exists()


def test_la_phase_nrem1_declenche_le_registre():
    src = SUP.read_text(encoding="utf-8")
    i = src.index('if (phase === "NREM1") {')
    bloc = src[i:i + 14000]
    assert '"forge_intent_verifier.py"' in bloc, "aucun declencheur du registre des demandes owner"
    j = bloc.index('"forge_intent_verifier.py"')
    assert '"--registre"' in bloc[j:j + 900]
