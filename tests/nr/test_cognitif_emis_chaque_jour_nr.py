"""NR : le releve cognitif est EMIS chaque jour par la boucle autonome (mesure 26/10).

Le fichier RAG/cognitive/ etait fige du 14/08 au 26/10 : tools/forge_cognitive_fitness.py n'ecrit qu'avec --emit,
et personne ne le lancait ainsi. eval_fitness lisait donc un 74,07 vieux de 73 jours ; la mesure du jour vaut 54.
"""
import sys
import types

from app import forge_autonomous_loops as fal


def test_le_motif_est_declare_quotidien():
    p = fal.PATTERNS.get("cognitive_emit")
    assert p is not None and p.interval_sec == 86400


def test_le_motif_emet_et_rend_le_releve(monkeypatch):
    appels = []

    def emettre(fenetre_h=24.0):
        appels.append(fenetre_h)
        return {"etat": "MESURE", "pass_rate": 54.0, "_fichier": "cognitive_x.json"}

    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_cognitive_fitness", types.SimpleNamespace(emettre=emettre))
    r = fal.pat_cognitive_emit()
    assert appels == [24.0] and r["pass_rate"] == 54.0 and r["etat"] == "MESURE"


def test_sans_mesure_rien_n_est_pretendu(monkeypatch):
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_cognitive_fitness",
                        types.SimpleNamespace(emettre=lambda fenetre_h=24.0: {"etat": "INSUFFISANT"}))
    r = fal.pat_cognitive_emit()
    assert r["etat"] == "INSUFFISANT" and "pass_rate" not in r
