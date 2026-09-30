"""NR -- CAPSULE COGNITIVE (RecursiveMAS, direction owner du 2026-09-28).

Direction : RecursiveMAS pense AUTOUR des boites noires (Claude Code, agy), jamais dedans ;
elles ne recoivent qu'une capsule courte et tracable, CRISTALLISEE par le corps. Premier
increment choisi par l'owner. Mesure du jour : le mode latent n'a servi qu'une fois (validation
du 03/07) ; le debat produit deja un etat STRUCTURE et rejouable (axes, positions, tensions,
acquis, intentions, verdict sous quorum). La capsule en est une projection DETERMINISTE --
aucun appel de modele de plus, rien d'invente.

Doctrine « preuve != parole » : tout ce qu'un debat produit est DECLARED ; OBSERVED ou PROVEN
exigerait une reference de preuve, qu'un debat n'apporte pas. Le RAG est un CONTEXTE, jamais
une cause.

Contrats :
  1. faits = axes admis + acquis ; ecartes = axes rejetes ; incertitudes = axes candidats ;
     contradictions = tensions + axes admis par l'un et rejetes par l'autre ; prochaines
     actions = intentions capturees -- chacun porte son auteur ; tout est DECLARED ;
  2. sous quorum (NEEDS_MEASUREMENT) : pas d'etat, pas de fait invente, verdict dit ;
  3. bornee (texte et listes) et DETERMINISTE (meme entree -> meme capsule) ;
  4. le rendu texte pour une boite noire porte les sections et reste borne ;
  5. ecrite a cote du resultat du debat, la capsule pointe vers lui (provenance).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _debat():
    spec = importlib.util.spec_from_file_location("nr_capsule_debat", ROOT / "tools/forge_debate_job.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pos(axe, statut, par, why, seq):
    return {"id": f"P_{axe}_{seq}", "axe": axe, "statut": statut, "par": par, "why": why,
            "mesure": "non mesure", "supersedes": None}


def _resultat(**surcharge):
    positions = [
        _pos("seuil", "admis", "A", "seuil a 0.8 mesure", 1),
        _pos("seuil", "rejete", "B", "seuil trop haut", 2),
        _pos("cache", "admis", "A", "cache LRU", 1),
        _pos("gpu", "candidat", "B", "a mesurer", 1),
        _pos("cloud", "rejete", "A", "cout", 1),
    ]
    axes = {}
    for p in positions:
        axes[p["axe"]] = dict(p)
    r = {
        "objective": "finaliser le pont M2M", "rounds": 2, "verdict": "ADOPTE", "verdict_motif": None,
        "n_repondus": 4, "n_structures": 4, "mode": "text-cloud",
        "transcript": [{"name": "A", "provider": "groq", "ok": True, "text": "x"},
                       {"name": "B", "provider": "cerebras", "ok": True, "text": "y"}],
        "deliberation": {"tour": 2, "axes": axes, "positions": positions,
                         "tensions": ["[B] le rejeu n'est pas prouve"],
                         "acquis": ["[A] le transport marche"], "journal": [{"seq": 1}]},
        "synthesis": "CONSENSUS : seuil 0.8. " * 200,
        "captured_intents": ["ACTION: mesurer le rejeu inter-process"],
        "rag_context": "contexte",
    }
    r.update(surcharge)
    return r


def test_la_capsule_projette_l_etat_du_debat_et_tout_y_est_declare():
    d = _debat()
    c = d.cristalliser(_resultat(), ref="C:/tmp/debat.json", cristallise_a="2026-09-28T09:00:00")
    faits = {(f["axe"], f["par"]) for f in c["faits"] if f.get("axe")}
    ok = (c["schema"], c["confiance"], ("cache", "A") in faits,
          any("transport" in f["texte"] for f in c["faits"]),
          {e["axe"] for e in c["ecartes"]}, {i["axe"] for i in c["incertitudes"]},
          any("rejeu" in x for x in c["contradictions"]),
          any("seuil" in x for x in c["contradictions"]),
          c["prochaines_actions"], c["provenance"]["resultat_ref"],
          {f["preuve"] for f in c["faits"]} | {e["preuve"] for e in c["ecartes"]})
    assert ok == ("nokido.capsule/1", "DECLARED", True, True, {"cloud", "seuil"}, {"gpu"},
                  True, True, ["ACTION: mesurer le rejeu inter-process"], "C:/tmp/debat.json",
                  {"DECLARED"})


def test_sous_quorum_la_capsule_n_invente_rien():
    d = _debat()
    c = d.cristalliser(_resultat(verdict="NEEDS_MEASUREMENT", verdict_motif="quorum",
                                 synthesis=None, deliberation={"tour": 0, "axes": {}, "tensions": [],
                                                               "acquis": []}, captured_intents=[]),
                       ref="r", cristallise_a="t")
    ok = (c["etat"], c["faits"], c["verdict"], c["verdict_motif"])
    assert ok == (None, [], "NEEDS_MEASUREMENT", "quorum")


def test_la_capsule_est_bornee_et_deterministe():
    d = _debat()
    a = d.cristalliser(_resultat(), ref="r", cristallise_a="t")
    b = d.cristalliser(_resultat(), ref="r", cristallise_a="t")
    ok = (a == b, len(a["etat"]) <= d.CAPSULE_ETAT_MAX, "journal" not in json.dumps(a))
    assert ok == (True, True, True)


def test_le_rendu_pour_une_boite_noire_est_court_et_structure():
    d = _debat()
    t = d.capsule_en_texte(d.cristalliser(_resultat(), ref="r", cristallise_a="t"))
    ok = (all(s in t for s in ("OBJECTIF", "FAITS DECLARES", "CONTRADICTIONS", "INCERTITUDES",
                               "PROCHAINES ACTIONS", "PROVENANCE")), len(t) <= d.CAPSULE_TEXTE_MAX)
    assert ok == (True, True)


def test_la_capsule_s_ecrit_a_cote_du_resultat_et_le_pointe(tmp_path):
    d = _debat()
    sortie = tmp_path / "debat.json"
    sortie.write_text(json.dumps(_resultat()), encoding="utf-8")
    chemin = d.ecrire_capsule(_resultat(), sortie)
    c = json.loads(Path(chemin).read_text(encoding="utf-8"))
    ok = (Path(chemin).name, c["provenance"]["resultat_ref"] == str(sortie))
    assert ok == ("debat.capsule.json", True)
