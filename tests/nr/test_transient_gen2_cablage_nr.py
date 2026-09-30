"""NR — GEN-2 du Transient Spine : le CABLAGE, mesure par le chemin reel.

GEN-1 a prouve qu'une fonction sait normaliser une intention. Ce n'est PAS une
capacite runtime : une fonction juste que personne n'appelle est une dette de
cablage, jamais une securite. Le depot a paye ce motif plusieurs fois (un garde
branche sur une hormone que personne n'emet, un masqueur declare et jamais
importe), et la seule facon de ne pas le repeter est de mesurer quatre choses
DISTINCTES au lieu d'une :

    1. la fonction est correcte      -> GEN-1, deja verrouille ailleurs
    2. la fonction est APPELEE       -> ici, par `main()` sur stdin
    3. un transient est PRODUIT      -> ici
    4. le transient est JOURNALISE   -> ici

C'est la chaine EXISTE -> CABLE -> OBSERVE. `REJOUABLE` et `REINJECTABLE` ne
sont pas de ce cliquet et ne doivent pas y etre supposes.

CE QUE GEN-2 N'A TOUJOURS PAS LE DROIT DE FAIRE, et que ces tests font echouer :
la chaine s'arrete AU JOURNAL. Pas de routeur, pas de worker, pas de swarm, pas
de reinjection. Et la decision du gate reste identique a l'octet pres : on
observe un organe qui fonctionne, on ne le remplace pas pour apprendre a le
regarder.
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "app"), os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate = pytest.importorskip("forge_tool_gate")


def _evenement_task():
    return {
        "cli": "claude",
        "session_id": "sess-gen2",
        "agent": "CLAUDE",
        "tool_name": "Task",
        "tool_input": {"subagent_type": "Explore", "description": "recon"},
    }


def _passer_par_main(evenement, capsys):
    """Le CHEMIN REEL : stdin -> main() -> stdout. Pas un appel de fonction."""
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(evenement))
    try:
        rc = gate.main()
    finally:
        sys.stdin = stdin
    assert rc == 0, "le gate ne doit jamais sortir non nul"
    return capsys.readouterr()


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Redirige le journal : on mesure le CABLAGE, pas les ACL du compte."""
    cible = tmp_path / "transient.jsonl"
    monkeypatch.setenv("LAFORGE_TRANSIENT_JOURNAL", str(cible))
    return cible


# ── 2 et 3 : la fonction est APPELEE, et un transient est PRODUIT ───────────

def test_un_evenement_reel_produit_un_transient_journalise(journal, capsys):
    _passer_par_main(_evenement_task(), capsys)
    assert journal.exists(), (
        "aucun journal : `normaliser_transient` est correcte mais PERSONNE ne "
        "l'appelle sur le chemin reel — c'est une dette de cablage, pas une "
        "capacite")
    lignes = [l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 1, "une observation, une ligne (vu : %d)" % len(lignes)
    t = json.loads(lignes[0])
    assert t.get("schema") == "nokido.transient.v1"
    assert t.get("intent") == "TRANSIENT_OBSERVED"
    assert (t.get("source") or {}).get("method") == "Task"
    assert (t.get("source") or {}).get("transport") == "hook"
    assert t.get("effect") == "UNCHANGED"
    assert (t.get("provenance") or {}).get("depth") == 0


def test_deux_evenements_donnent_deux_lignes(journal, capsys):
    """Le journal AJOUTE ; il n'ecrase pas l'observation precedente."""
    _passer_par_main(_evenement_task(), capsys)
    autre = _evenement_task()
    autre["tool_input"] = {"subagent_type": "Explore", "description": "autre"}
    _passer_par_main(autre, capsys)
    lignes = [l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 2
    ids = {json.loads(l)["id"] for l in lignes}
    assert len(ids) == 2, "deux intentions distinctes doivent porter deux ids"


# ── LE COMPORTEMENT NE BOUGE PAS ───────────────────────────────────────────

def test_la_decision_du_gate_est_inchangee(journal, capsys):
    cap = _passer_par_main(_evenement_task(), capsys)
    texte = (cap.out or "").strip()
    assert texte, "le gate doit toujours emettre sa decision"
    d = json.loads(texte.splitlines()[-1])
    brut = json.dumps(d, ensure_ascii=False).lower()
    assert "deny" in brut or "refus" in brut or "block" in brut, (
        "le refus des sous-agents a disparu : l'observation a modifie le "
        "comportement, ce qui lui est interdit. Sortie : %s" % brut[:300])


def test_un_journal_impossible_ne_casse_pas_le_gate(monkeypatch, capsys):
    """Un journal qui leve tuerait l'appel qu'il observe (paye le 2026-09-06).

    Le garde RSS du wrapper de job est mort en ecrivant son propre journal,
    APRES avoir tue son enfant mais AVANT d'ecrire le code de retour : le job
    est reste « running » a vie. Une observation journalise APRES coup, et son
    journal ne leve JAMAIS.
    """
    monkeypatch.setenv("LAFORGE_TRANSIENT_JOURNAL",
                       os.path.join(os.sep, "chemin", "impossible", "x.jsonl"))
    cap = _passer_par_main(_evenement_task(), capsys)
    assert (cap.out or "").strip(), (
        "le gate a cesse d'emettre sa decision parce que son JOURNAL a echoue")


# ── LA CHAINE S'ARRETE AU JOURNAL ──────────────────────────────────────────

def test_le_cablage_ne_declenche_aucune_execution(journal, monkeypatch, capsys):
    """Ni routeur, ni worker, ni swarm, ni reseau, ni processus."""
    appels = []
    import subprocess
    for nom in ("Popen", "run", "call", "check_output"):
        if hasattr(subprocess, nom):
            monkeypatch.setattr(subprocess, nom,
                                lambda *a, **k: appels.append("subprocess") or None)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: appels.append("reseau") or None)

    _passer_par_main(_evenement_task(), capsys)
    assert appels == [], (
        "GEN-2 a declenche une execution : %r. La chaine s'arrete AU JOURNAL." % appels)


def test_le_swarm_n_est_pas_sollicite(journal, capsys):
    """Aucun module de routage/preuve ne doit etre charge par l'observation."""
    avant = {n for n in sys.modules if "swarm" in n}
    _passer_par_main(_evenement_task(), capsys)
    apres = {n for n in sys.modules if "swarm" in n}
    assert apres <= avant, (
        "l'observation a charge un module de swarm : %r. GEN-2 observe, "
        "il n'oriente pas encore." % sorted(apres - avant))
