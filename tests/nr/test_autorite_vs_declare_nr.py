# -*- coding: utf-8 -*-
"""NR — une identité DÉCLARÉE ne décide jamais ; seule une autorité établie le peut.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la separation declare vs autorite"

CE QUI A ÉTÉ MESURÉ (2026-09-07). `forge_tool_gate._resolve_ring` faisait
`int(resolve_identity(agent))`. Or `resolve_identity` rend un **dict** : `int(dict)`
lève `TypeError`, l'`except Exception` l'avalait, et la fonction rendait **3 pour tout
le monde** — y compris un nom d'agent inventé. Prouvé à l'oracle :

    resolve_identity('CLAUDE')      -> {'ring': 4, 'via': 'header'}
    int(ident)                      -> TypeError
    _resolve_ring('N_IMPORTE_QUOI') -> 3

**Ce que ce défaut fait, et ce qu'il ne fait pas.** Il n'accorde aucun droit : aucune
branche de `decide()` ne compare le ring (0 comparaison dans tout le fichier — j'avais
d'abord annoncé une élévation de privilège, la mesure l'a démentie). En revanche le
ring part vers `forge_orchestration_gate.classify`, qui ne l'examine QUE pour
`ring == 0` = « LOCAL OBLIGATOIRE, souverain ». Une source qui ne peut produire que 3
rend donc **cette garantie de souveraineté inatteignable**.

Et corriger en lisant `ident["ring"]` n'y changerait rien : sans credential, le videur
rend `via=header` et le plancher anti-spoof, soit 4 — jamais 0. La correction est une
**migration d'autorité**, pas un patch de conversion.

Ce NR verrouille l'étape 1 : le mensonge silencieux disparaît, l'écart est MESURÉ, et
le ring hérité est nommé pour ce qu'il est.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_tool_gate as g  # noqa: E402

GATE = ROOT / "tools" / "forge_tool_gate.py"


# --- étape 1 : plus aucun ring inventé -------------------------------------------

def test_un_resolveur_qui_echoue_ne_rend_pas_un_ring(monkeypatch) -> None:
    """ILLISIBLE n'est pas un ring. C'est la confusion exacte qui a produit le defaut."""
    import forge_videur as v

    def boum(*_a, **_k):
        raise RuntimeError("resolveur indisponible")

    monkeypatch.setattr(v, "resolve_identity", boum)
    obs = g._observer_identite("CLAUDE")
    assert obs["statut"] == "ILLISIBLE"
    assert obs["ring_observe"] is None, "un echec ne doit JAMAIS produire un ring"
    assert "RuntimeError" in obs["motif"], "l'echec doit etre NOMME, pas avale"


def test_le_defaut_historique_est_attrape(monkeypatch) -> None:
    """`resolve_identity` rend un dict : le traiter comme un entier doit etre ILLISIBLE."""
    import forge_videur as v
    monkeypatch.setattr(v, "resolve_identity",
                        lambda *a, **k: {"agent": "CLAUDE", "ring": 4, "via": "header"})
    obs = g._observer_identite("CLAUDE")
    assert obs["statut"] == "OBSERVE"
    assert obs["ring_observe"] == 4, "le ring du videur doit etre lu, pas converti de force"
    assert obs["via"] == "header", "le canal d'etablissement doit remonter avec le ring"


def test_une_reponse_non_dict_est_illisible(monkeypatch) -> None:
    import forge_videur as v
    monkeypatch.setattr(v, "resolve_identity", lambda *a, **k: 2)
    obs = g._observer_identite("CLAUDE")
    assert obs["statut"] == "ILLISIBLE"
    assert obs["ring_observe"] is None


def test_une_reponse_sans_ring_est_inconnue(monkeypatch) -> None:
    """INCONNU n'est ni ILLISIBLE ni un ring : trois etats, jamais deux."""
    import forge_videur as v
    monkeypatch.setattr(v, "resolve_identity", lambda *a, **k: {"agent": "X", "via": "header"})
    obs = g._observer_identite("X")
    assert obs["statut"] == "INCONNU"
    assert obs["ring_observe"] is None


# --- étape 2 : le ring hérité est NOMMÉ, et il ne décide pas ----------------------

def test_le_ring_legacy_est_marque_non_autoritaire() -> None:
    src = GATE.read_text(encoding="utf-8", errors="replace")
    assert "_RING_DECLARE_LEGACY" in src, "le ring herite doit porter un nom qui le dit"
    i = src.find("_RING_DECLARE_LEGACY = ")
    assert i > 0
    assert "NOT_AUTHORITY" in src[i:i + 220], (
        "sans cette marque, un futur lecteur le prendra pour une autorite")


def test_aucune_decision_du_gate_ne_compare_le_ring() -> None:
    """Verrou de conception : si quelqu'un rebranche le ring herite sur une decision,
    ce test rougit. C'est la seule chose qui empeche la dette de revenir en silence."""
    import re
    src = GATE.read_text(encoding="utf-8", errors="replace")
    code = [l for l in src.splitlines()
            if not l.lstrip().startswith("#") and "ring" in l]
    comparaisons = [l for l in code
                    if re.search(r"\bring\b\s*(<=|>=|<|>|==|!=)|(<=|>=|<|>|==|!=)\s*\w*ring\b", l)]
    assert not comparaisons, (
        "le ring herite vient d'une identite DECLAREE : il ne doit fonder aucune "
        "decision tant qu'un credential ne l'etablit pas. Trouve : %r" % comparaisons[:3])


def test_resolve_ring_ne_leve_jamais_et_rend_le_legacy(monkeypatch) -> None:
    """Comportement PRESERVE : l'etape 1 ne bascule aucun appel sur un autre ring."""
    import forge_videur as v

    def boum(*_a, **_k):
        raise RuntimeError("indisponible")

    monkeypatch.setattr(v, "resolve_identity", boum)
    for nom in ("CLAUDE", "UNKNOWN", "", "N_IMPORTE_QUOI"):
        assert g._resolve_ring(nom) == g._RING_DECLARE_LEGACY


def test_le_journal_shadow_ne_casse_jamais_l_appel(monkeypatch) -> None:
    """Un journal qui leve dans un hook casse l'appel qu'il observe.

    Paye le 2026-09-06 sur le garde RSS du wrapper de job : il tuait le process puis
    mourait en ouvrant son propre `.err`, laissant le job « running » a vie."""
    monkeypatch.setattr(g, "_SHADOW_AUTORITE", "sandbox/\x00chemin-impossible.jsonl")
    g._journal_shadow("CLAUDE", {"statut": "OBSERVE", "ring_observe": 4, "via": "header"})
    assert g._resolve_ring("CLAUDE") == g._RING_DECLARE_LEGACY


def test_l_ecart_est_mesure_et_le_credential_declare_absent(tmp_path, monkeypatch) -> None:
    """L'observation doit dire l'ecart ET qu'aucun credential n'est parvenu au gate."""
    import json
    monkeypatch.setattr(g, "_SHADOW_AUTORITE", "sandbox/nr_authority_shadow.jsonl")
    cible = ROOT / "sandbox" / "nr_authority_shadow.jsonl"
    if cible.exists():
        cible.unlink()
    g._resolve_ring("CLAUDE")
    assert cible.is_file(), "l'ecart doit etre consigne, sinon la phase shadow ne mesure rien"
    ligne = json.loads(cible.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["ring_legacy"] == g._RING_DECLARE_LEGACY
    assert ligne["credential_recu"] is False, (
        "tant que le gate ne recoit aucun credential, l'autorite ne peut pas exister")
    assert "statut" in ligne and "ring_observe" in ligne
    cible.unlink()
