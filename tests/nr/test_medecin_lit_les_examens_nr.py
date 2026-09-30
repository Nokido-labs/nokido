"""NR -- le diagnostic consolide LIT les examens que d'autres organes produisent, et le medecin les entend.

MESURE 2026-09-25 (epreuve owner « comme un vrai medecin qui fait toutes les analyses ») : la soif
interoceptive ne lisait qu'UN examen, `health_diagnostic.json`. A cote, sans lecteur :
  - capability_freshness.json (circadien NREM1) disait `ratchet_check=REGRESSION` et
    `execution_trace=ERREUR_OUTIL` -- une regression de capacite et un instrument casse ;
  - reachability.json : 1191 LOST, 933 ORPHELIN ; body_regulation.json : 2 NON_CABLE ;
  - organ_map_full.json (recensement) a 46 h et provider_reachability.json a 28 JOURS, sans
    aucun ordonnanceur ;
  - forge_organ_agents.gaps() : 2 cablages essentiels declares manquants.
Le diagnostic ne refait AUCUN de ces examens : il les lit, dit leur age, et ne conclut jamais d'un
examen absent ou illisible. NON BLOQUANT : aucune ligne ne retire de point (observer avant d'enforcer).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_health_diagnostic as hd  # noqa: E402

MAINTENANT = 1_790_000_000.0


def _ecrire(base: Path, rel: str, data, age_h: float):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    t = MAINTENANT - age_h * 3600
    os.utime(p, (t, t))


def _sandbox(tmp_path):
    _ecrire(tmp_path, "capability_freshness.json", {"resume": {
        "crosswalk": "PASS", "execution_trace": "ERREUR_OUTIL", "ratchet_check": "REGRESSION"}}, 23)
    _ecrire(tmp_path, "workspace/body_regulation.json", {
        "a.py": {"statut": "REGULE"}, "b.py": {"statut": "NON_CABLE"}, "c.py": {"statut": "INDETERMINE"}}, 60)
    _ecrire(tmp_path, "reachability.json", "{pas du json", 1)
    _ecrire(tmp_path, "workspace/organ_map_full.json", {"module_organ": {}}, 46.5)
    # provider_reachability.json : ABSENT
    return tmp_path


def test_chaque_examen_a_un_etat_honnete(tmp_path, monkeypatch):
    monkeypatch.setattr(hd, "_cablages_declares_manquants", lambda: [
        {"family": "Reproductif / regeneration", "missing_wiring": "BOUCLE regeneration non close"}])
    ex = hd.audit_examens(sandbox=_sandbox(tmp_path), maintenant=MAINTENANT)
    assert ex["capacites"]["etat"] == "FRAIS"
    assert ex["capacites"]["constats"] == ["execution_trace=ERREUR_OUTIL", "ratchet_check=REGRESSION"]
    assert ex["innervation"]["etat"] == "PERIME" and ex["innervation"]["age_h"] == 60.0
    assert ex["atteignabilite"]["etat"] == "ILLISIBLE"          # jamais « sain » ni « vide »
    assert ex["anatomie"]["etat"] == "SANS_ORDONNANCEUR"        # un age, pas un verdict invente
    assert ex["fournisseurs"]["etat"] == "ABSENT"
    assert ex["cablages_manquants"]["constats"][0].startswith("Reproductif / regeneration")


def test_les_lignes_qui_demandent_un_soin_portent_un_marqueur_que_le_medecin_entend(tmp_path, monkeypatch):
    """Contrat entre les DEUX organes : une ligne qui n'a aucun marqueur de soin n'arrive jamais au
    medecin -- elle reste dans un rapport que personne ne lit."""
    monkeypatch.setattr(hd, "_cablages_declares_manquants", lambda: [])
    lignes = hd._lignes_examens(hd.audit_examens(sandbox=_sandbox(tmp_path), maintenant=MAINTENANT))
    spec = importlib.util.spec_from_file_location("demon_examens", RACINE / "tools" / "forge_epistemic_daemon.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)

    def entendue(ligne):
        return any(m in ligne for m in d._CARE_MARKERS)

    regression = [l for l in lignes if "REGRESSION" in l]
    perime = [l for l in lignes if "innervation" in l and "PÉRIMÉ" in l]
    absent = [l for l in lignes if "fournisseurs" in l]
    assert regression and all(entendue(l) for l in regression), lignes
    assert perime and all(entendue(l) for l in perime), lignes
    assert absent and all(entendue(l) for l in absent), lignes
    assert any("atteignabilite" in l and "ILLISIBLE" in l for l in lignes), lignes


def test_une_ligne_de_soin_est_stable_d_un_cycle_a_l_autre(tmp_path, monkeypatch):
    """MESURE 2026-09-25 (tableau noir, 5 cycles) : « Capacites examen de 1.9 h / 2.2 h / 2.5 h... :
    ratchet_check REGRESSION » -- l'AGE dans le texte changeait la signature de la lesion a chaque
    cycle (la soif la hache sur le texte) : jamais chronique, un fait neuf par cycle. Une ligne de
    soin ne porte RIEN qui varie sans que la lesion change."""
    monkeypatch.setattr(hd, "_cablages_declares_manquants", lambda: [])
    sb = _sandbox(tmp_path)
    avant = hd._lignes_examens(hd.audit_examens(sandbox=sb, maintenant=MAINTENANT))
    apres = hd._lignes_examens(hd.audit_examens(sandbox=sb, maintenant=MAINTENANT + 3 * 3600))
    spec = importlib.util.spec_from_file_location("demon_stable", RACINE / "tools" / "forge_epistemic_daemon.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    soins_avant = [l for l in avant if any(m in l for m in d._CARE_MARKERS)]
    soins_apres = [l for l in apres if any(m in l for m in d._CARE_MARKERS)]
    assert soins_avant and soins_avant == soins_apres, (soins_avant, soins_apres)


def test_non_bloquant_et_branche_dans_le_cycle():
    src = (RACINE / "app" / "forge_health_diagnostic.py").read_text(encoding="utf-8")
    cycle = src.split("def run_cycle", 1)[1]
    assert '"examens": audit_examens()' in cycle
    score = src.split("def compute_score_and_gaps", 1)[1].split("\ndef ", 1)[0]
    assert "gaps.extend(_lignes_examens(" in score
    fn = src.split("def _lignes_examens", 1)[1].split("\ndef ", 1)[0]
    assert "score" not in fn, "une ligne d'examen ne retire AUCUN point tant que son bruit n'est pas mesure"
