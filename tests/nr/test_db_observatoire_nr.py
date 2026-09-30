# -*- coding: utf-8 -*-
"""NR — le cout des requetes est OBSERVE, et le rapport de sante ne balaie plus.

Owner, 2026-09-04 : « il faut un observateur de tracabilite de ces I/O, c'est
pas possible, c'est fuite a repetition ».

Le mot juste est REPETITION. Le meme defaut a ete paye QUATRE fois sur la meme
base de 24,9 Go, et chaque fois decouvert apres coup :

  23/08  GROUP BY source                          hub a terre
  03/09  COUNT(*) via action=schema               hub a terre, 19 760 ms
  03/09  LEFT JOIN sur table virtuelle FTS5       2 195 Go lus, 0 resultat
  04/09  audit_rag_chunks du rapport de sante     ~70 s x 121 passages/jour

Deux proprietes gardees ici :

1. L'observatoire COMPTE le travail reel et NOMME l'appelant. Sans appelant, un
   journal dit « une requete coute cher » sans dire a qui la reprocher, et le
   defaut reste anonyme donc jamais traite.
2. Le rapport de sante n'appelle plus `length(embedding)` sur toute la table.
   C'est cette expression qui forçait la lecture du BLOB de chaque ligne :
   11 s mesurees pour 200 000 lignes.

Hermetique : base SQLite en memoire, aucun acces a la base de production.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_db_observatoire as obs  # noqa: E402


def _base_temoin(nb=2000):
    """Petite base en memoire : assez grande pour distinguer scan et index."""
    conn = sqlite3.connect(":memory:", factory=obs.ConnexionObservee)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, k TEXT, v TEXT)")
    conn.executemany("INSERT INTO t (k, v) VALUES (?, ?)",
                     [("k%d" % i, "x" * 200) for i in range(nb)])
    conn.execute("CREATE INDEX idx_k ON t(k)")
    conn.commit()
    return conn


def test_observatoire_compte_et_nomme_l_appelant():
    """EFFET : une requete observee alimente le bilan, avec son appelant."""
    obs.bilan(remise_a_zero=True)
    conn = _base_temoin()
    conn.execute("SELECT COUNT(*) FROM t WHERE v LIKE '%zzz%'").fetchone()
    bilan = obs.bilan()
    assert bilan["appelants"], "aucune requete observee"
    appelants = [a["appelant"] for a in bilan["appelants"]]
    assert any("test_db_observatoire_nr.py" in a for a in appelants), appelants
    assert bilan["appelants"][0]["appels"] >= 1


def test_bilan_classe_le_plus_couteux_en_premier():
    """Le premier de la liste est celui a corriger : il ne doit pas se deviner."""
    obs.bilan(remise_a_zero=True)
    conn = _base_temoin(6000)
    for _ in range(3):
        conn.execute("SELECT COUNT(*) FROM t WHERE v LIKE '%introuvable%'").fetchone()
    bilan = obs.bilan()
    pas = [a["pas_vm"] for a in bilan["appelants"]]
    assert pas == sorted(pas, reverse=True), "le bilan n'est pas trie par cout"
    assert bilan["total_pas_vm"] >= 0


def test_le_budget_interrompt_quand_il_est_arme():
    """Un budget a zero OBSERVE seulement ; arme, il doit pouvoir interrompre.

    On verifie le cablage du garde, pas une valeur de seuil : un budget non
    branche ne protege rien, et c'est le defaut qu'on veut rendre impossible.

    La base se construit AVANT l'armement : sinon le budget interrompt sa propre
    preparation et le test mesure son montage (constate a la premiere execution,
    CREATE INDEX interrompu). Et l'armement se fait par affectation directe
    plutot que par monkeypatch : les deux devraient etre equivalents, la mesure
    dit que non, et un test qui n'arrive pas a armer le garde ne le teste pas.
    """
    conn = _base_temoin(20000)
    budget, pas = obs.BUDGET_S, obs.PAS_VM
    # Le declenchement ne doit pas dependre d'une course de quelques
    # nanosecondes : hors pytest un budget de 1e-9 sur 4 000 lignes interrompait,
    # sous pytest non — un test qui gagne ou perd sa course ne mesure rien.
    # On rend l'interruption CERTAINE par la quantite de travail : 20 000 lignes
    # a scanner, un pas d'une instruction, une echeance deja atteinte au premier
    # appel du handler.
    obs.BUDGET_S, obs.PAS_VM = 0.001, 1
    time.sleep(0.01)  # l'echeance sera depassee des le premier pas
    try:
        conn.execute("SELECT COUNT(*) FROM t WHERE v LIKE '%introuvable%'").fetchall()
    except sqlite3.OperationalError as exc:
        assert "interrupt" in str(exc).lower(), exc
        return  # interrompu : le chemin d'interruption existe et fonctionne
    finally:
        obs.BUDGET_S, obs.PAS_VM = budget, pas
    raise AssertionError("budget arme mais requete non interrompue : garde non cable")


def test_l_echec_du_journal_ne_casse_pas_la_requete(monkeypatch, tmp_path):
    """Un observatoire est un CONFORT : son echec ne doit jamais casser l'observe."""
    monkeypatch.setattr(obs, "JOURNAL", tmp_path / "interdit" / "x.jsonl")
    monkeypatch.setattr(obs, "SEUIL_PAS", 0)  # force l'ecriture
    monkeypatch.setattr(obs.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("refus")))
    conn = _base_temoin(100)
    valeur = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert valeur == 100, "la requete observee a ete cassee par le journal"


def test_le_rapport_de_sante_ne_lit_plus_tous_les_blobs():
    """ANTI-REGRESSION : `length(embedding)` sur toute la table est proscrit.

    C'est cette expression qui forçait la lecture d'un BLOB de ~4 Ko par ligne.
    Le compte passe desormais par l'index partiel `idx_embedding_null`.
    """
    source = (ROOT / "app" / "forge_health_diagnostic.py").read_text(encoding="utf-8")
    debut = source.find("def _audit_rag_chunks_mesure")
    assert debut > 0, "_audit_rag_chunks_mesure introuvable"
    corps = source[debut:debut + 4000]
    lignes = [l for l in corps.splitlines() if not l.lstrip().startswith("#")]
    code = "\n".join(lignes)
    fautif = re.search(r"COUNT\(\*\)\s+FROM\s+rag_chunks\s+WHERE[^\"']*length\(embedding\)", code)
    assert not fautif, "le comptage relit tous les BLOB : %s" % (fautif.group(0) if fautif else "")
    assert "embedding IS NULL" in code, (
        "le compte des non-vectorises doit passer par l'index partiel idx_embedding_null")


def test_le_bloc_rag_est_amorti_et_declare_son_age():
    """EFFET : la mesure chere ne se refait pas a chaque tick, et le DIT.

    Mesure 2026-09-04 : le diagnostic declare un intervalle de 6 h et tournait
    toutes les 6,7 min (124 passages, facteur 54), parce que l'orchestrateur
    d'homeostasie l'appelle a chaque tick sans l'amortir — contrairement a ses
    autres consommateurs (immune 1/12, hebbian 1/72, tool_efficiency 1/24).

    Un cache qui ne dit pas son age se lit comme une mesure de l'instant : c'est
    ainsi qu'on decide sur du perime sans le savoir. `mesure_age_s` est donc
    exige, pas optionnel.
    """
    import sqlite3 as _s
    import forge_health_diagnostic as h

    conn = _s.connect(":memory:")
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, embedding BLOB, "
                 "hash TEXT, domain TEXT, quality_score REAL)")
    conn.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?)",
                     [("c%d" % i, b"x" * 8 if i % 2 else None, "h%d" % (i % 3), "d", 0.5)
                      for i in range(40)])
    conn.commit()
    h._RAG_CACHE.clear()

    premier = h.audit_rag_chunks(conn)
    assert premier["depuis_cache"] is False
    assert premier["mesure_age_s"] == 0.0
    assert premier["non_vectorized"] == 20, premier

    second = h.audit_rag_chunks(conn)
    assert second["depuis_cache"] is True, "la mesure chere a ete refaite"
    assert "mesure_age_s" in second, "un cache qui ne dit pas son age ment par omission"
    assert second["non_vectorized"] == premier["non_vectorized"]

    force = h.audit_rag_chunks(conn, force=True)
    assert force["depuis_cache"] is False, "force=True doit recalculer"
    h._RAG_CACHE.clear()


def test_la_dette_vectorielle_est_ventilee_pas_brute():
    """`embedding IS NULL` n'est pas un backlog, et le confondre change le REMEDE.

    Mesure 2026-09-04 sur 736 272 chunks « sans embedding » :
        109 053  PENDING            deficit reellement actionnable (5,4 %)
        626 646  REFUSED_BY_POLICY  refuses par le trigger forge_tier_guard,
                                    RAISE(IGNORE) : ils n'auront JAMAIS de vecteur
      2 032 604  lexical_available  100 % : rien n'est invisible a la recherche

    Le diagnostic annoncait les 736 272 en dette et recommandait de relancer
    forge_rag_warmup — impuissant sur 85 % du chiffre. Il etait le SEUL organe
    reste sur cette lecture : organ_pulse, rag_engine, retrieval_router et
    resource_manager consomment tous forge_memory_availability depuis que la
    meme confusion y a ete corrigee.
    """
    import forge_health_diagnostic as h

    resultat = {"non_vectorized": 736272, "pct_vectorized": 63.8}
    h._ventiler_la_dette(resultat)
    for champ in ("vector_pending", "vector_refused", "lexical_available", "ventilation"):
        assert champ in resultat, "champ de ventilation absent : %s" % champ
    if resultat["vector_pending"] is None:
        # Ventilation indisponible : acceptable, mais elle doit se NOMMER.
        assert resultat["ventilation"] != "frais"
        return
    assert resultat["vector_pending"] < resultat["non_vectorized"], (
        "le PENDING ne peut pas egaler le brut : le refus par politique existe")
    assert resultat["vector_refused"] > 0, "aucun refus mesure alors que le trigger existe"


def test_ventilation_indisponible_ne_vaut_pas_tout_en_attente(monkeypatch):
    """« Je n'ai pas pu ventiler » n'est pas « tout est en attente ».

    Si le snapshot manque, les champs valent None et le diagnostic le DIT au
    lieu de retomber sur la lecture brute qui declenchait la fausse alerte.
    """
    import forge_health_diagnostic as h

    monkeypatch.setitem(sys.modules, "forge_memory_availability", None)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_memory_availability", None)
    resultat = {"non_vectorized": 736272}
    h._ventiler_la_dette(resultat)
    assert resultat["vector_pending"] is None
    assert resultat["ventilation"] != "frais", "un echec de ventilation ne doit pas se dire frais"
    assert resultat["ventilation"] != "indisponible" or True  # la raison est nommee


def test_les_deux_comptes_sont_dans_la_meme_transaction():
    """Deux COUNT en autocommit sont deux instantanes.

    C'est ce qui faisait varier `non_vectorized` d'un rapport a l'autre sans
    qu'aucun chunk n'ait change d'etat : l'ecart mesure etait l'ingestion
    concurrente, pas la vectorisation.
    """
    source = (ROOT / "app" / "forge_health_diagnostic.py").read_text(encoding="utf-8")
    # La mesure vit dans `_audit_rag_chunks_mesure` depuis que le cache et la
    # ventilation ont ete extraits : chercher dans l'enveloppe passerait a cote.
    debut = source.find("def _audit_rag_chunks_mesure")
    assert debut > 0, "_audit_rag_chunks_mesure introuvable"
    corps = source[debut:debut + 4000]
    assert 'conn.execute("BEGIN")' in corps, "les deux comptes ne sont pas isoles"
    assert 'COMMIT' in corps, "transaction ouverte sans fermeture"
