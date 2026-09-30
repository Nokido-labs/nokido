#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/nr/test_capability_ratchet_nr.py — le cliquet de capacites detecte-t-il ?

Un cliquet qui rend CONFORME sur le socle qu'il vient d'ecrire ne prouve rien : c'est
le faux-vert du 2026-08-15 (trois coches vertes rendues sans avoir rien mesure). Ces
tests injectent des regressions SYNTHETIQUES et exigent le verdict exact.

Hermetiques : aucun test ne lit le working tree (leçon du 2026-08-15 -- un test
d'effet qui lisait des fichiers non versionnes passait en local et cassait sur
checkout CI propre). Le socle est un tmp_path, la matrice un dict fabrique. Seule
exception assumee : le socle du depot, qui EST versionne.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _socle(tmp_path, capacites):
    p = tmp_path / "capability_socle.json"
    p.write_text(json.dumps({"capacites": capacites}), encoding="utf-8")
    return str(p)


def _cap(tool, keys, forme, calls=500, derive=False, recente=None):
    return {"tool": tool, "arg_keys": keys, "forme": forme,
            "forme_recente": recente or forme, "derive": derive,
            "calls": calls, "last_ts": "2026-08-16T00:00:00"}


def _gel(tool, keys, forme, tier, derive=False, calls=500):
    return {"tool": tool, "arg_keys": keys, "forme": forme, "tier": tier,
            "derive": derive, "calls_au_gel": calls,
            "last_ts_au_gel": "2026-08-16T00:00:00"}


def _courant(capacites, struct=None, exposed=None, actions=None):
    tools = {c["tool"] for c in capacites.values()}
    return {"observable": True, "matrice": "test", "inventaire": "test",
            "capacites": capacites,
            "struct": tools if struct is None else struct,
            "exposed": tools if exposed is None else exposed,
            "actions": set() if actions is None else actions}


# ── ce qui doit BLOQUER ─────────────────────────────────────────────────────

def test_contrat_change_sur_capacite_garantie_bloque(tmp_path, monkeypatch):
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"run|action": _gel("run", ["action"], "obj:ok,rc,stdout", "garanti")}))
    code, r = R._verdict(_courant({"run|action": _cap("run", ["action"], "obj:error,ok")}))
    assert code == 1, r
    assert r["etat"] == "REGRESSION"
    assert len(r["block"]) == 1
    assert r["block"][0]["motif"] == "CONTRAT CHANGE"


def test_capacite_garantie_disparue_du_code_bloque(tmp_path, monkeypatch):
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"run|action": _gel("run", ["action"], "obj:ok", "garanti")}))
    # Plus dans la matrice, plus dans le code, plus offerte : perte prouvee.
    code, r = R._verdict(_courant({}, struct=set(), exposed=set()))
    assert code == 1, r
    assert r["block"][0]["motif"] == "DISPARUE"


def test_capacite_garantie_encore_codee_mais_plus_offerte_bloque(tmp_path, monkeypatch):
    """Encore un handle_*, plus au catalogue, et pas davantage une action de tool.

    Pour l'agent, une capacite muette est perdue : il ne peut plus la decouvrir.
    (Ne pas prendre `poll` pour exemple -- mesure du 2026-08-16 : c'est une ACTION
    de `hub`, jamais un tool, cf. test_action_dun_tool_nest_jamais_muette.)
    """
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"biblio|action": _gel("biblio", ["action"], "obj:ok", "garanti")}))
    code, r = R._verdict(_courant({}, struct={"biblio"}, exposed=set()))
    assert code == 1, r
    assert r["muet"] and r["muet"][0]["motif"] == "MUET"
    assert any(b["motif"] == "MUET" for b in r["block"])


# ── ce qui ne doit PAS bloquer ──────────────────────────────────────────────

def test_contrat_change_sur_opportuniste_signale_sans_bloquer(tmp_path, monkeypatch):
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"crawl|url": _gel("crawl", ["url"], "obj:ok,pages", "opportuniste")}))
    code, r = R._verdict(_courant({"crawl|url": _cap("crawl", ["url"], "obj:error")}))
    assert code == 0, r
    assert r["etat"] == "CONFORME"
    assert len(r["review"]) == 1 and not r["block"]


def test_longueur_de_texte_nest_pas_un_changement_de_contrat(tmp_path, monkeypatch):
    """6 des 30 derives mesurees le 2026-08-16 n'etaient que du bruit de seuil."""
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"run|action": _gel("run", ["action"], "texte:long", "garanti")}))
    code, r = R._verdict(_courant({"run|action": _cap("run", ["action"], "texte:moyen")}))
    assert code == 0, r
    assert not r["block"] and not r["review"]
    assert r["pass"] == 1


def test_capacite_encore_offerte_mais_non_appelee_nest_pas_une_perte(tmp_path, monkeypatch):
    """Sortie de la fenetre faute d'appels != disparue. Leçon des 24 faux PERDU."""
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"biblio|action": _gel("biblio", ["action"], "obj:ok", "garanti")}))
    code, r = R._verdict(_courant({}, struct={"biblio"}, exposed={"biblio"}))
    assert code == 0, r
    assert not r["block"] and not r["muet"]
    assert r["pass"] == 1


def test_action_dun_tool_nest_jamais_muette(tmp_path, monkeypatch):
    """Le cas `poll` : ~35 000 appels, un handle_poll, mais ce n'est pas un tool.

    `poll` est `hub(action="poll")`. Le journal reseau enregistre l'action dans la
    colonne `tool`, donc un inventaire naif la cherche au catalogue, ne l'y trouve
    pas, et crie MUET. La capacite est pourtant parfaitement offerte.
    """
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"poll|ack": _gel("poll", ["ack"], "obj:ok", "garanti")}))
    code, r = R._verdict(_courant({}, struct={"poll"}, exposed={"hub"},
                                  actions={"poll", "notify", "get_mode"}))
    assert code == 0, r
    assert not r["block"] and not r["muet"]
    assert r["pass"] == 1


def test_capacite_nouvelle_est_un_ADD_jamais_un_blocage(tmp_path, monkeypatch):
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(tmp_path, {}))
    code, r = R._verdict(_courant({"neuf|x": _cap("neuf", ["x"], "obj:ok", calls=3)}))
    assert code == 0, r
    assert len(r["add"]) == 1 and not r["block"]


def test_derive_qui_apparait_passe_en_review(tmp_path, monkeypatch):
    """Contrat qui BASCULE : la forme dominante tient encore, la recente a change."""
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"task|action": _gel("task", ["action"], "obj:job_id,ok", "opportuniste")}))
    cur = _cap("task", ["action"], "obj:job_id,ok", derive=True, recente="obj:ok,reason")
    code, r = R._verdict(_courant({"task|action": cur}))
    assert code == 0, r
    assert r["review"] and r["review"][0]["motif"] == "CONTRAT QUI BASCULE"


# ── ce qui doit rester INDETERMINE ──────────────────────────────────────────

def test_socle_absent_rend_indetermine_jamais_conforme(tmp_path, monkeypatch):
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", str(tmp_path / "absent.json"))
    code, r = R._verdict(_courant({"run|action": _cap("run", ["action"], "obj:ok")}))
    assert code == 3
    assert r["etat"] == "INDETERMINE"


def test_inventaire_non_observable_rend_indetermine(tmp_path, monkeypatch):
    """Un refus n'est pas une absence : sans inventaire, aucune conclusion."""
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle(
        tmp_path, {"run|action": _gel("run", ["action"], "obj:ok", "garanti")}))
    code, r = R._verdict({"observable": False, "raison": "import KO"})
    assert code == 3
    assert r["etat"] == "INDETERMINE"


def test_matrice_perimee_rend_indetermine(tmp_path, monkeypatch):
    """Une matrice vieille decrit un passe : conclure dessus fabrique un vert."""
    import forge_capability_ratchet as R

    class _FauxRM:
        MATRIX = str(tmp_path / "matrice.json")

    Path(_FauxRM.MATRIX).write_text(
        json.dumps({"generated_ts": "2020-01-01T00:00:00", "capabilities": []}),
        encoding="utf-8")
    monkeypatch.setattr(R, "FRAICHEUR_H", 72)
    doc, motif = R._charger_matrice(_FauxRM)
    assert doc is None
    assert "perimee" in motif


def test_refus_de_geler_un_etat_non_observe(tmp_path, monkeypatch):
    import forge_capability_ratchet as R

    monkeypatch.setattr(R, "SOCLE", str(tmp_path / "socle.json"))
    assert R._ecrire_socle({"observable": False, "raison": "matrice absente"}) == 3
    assert not Path(R.SOCLE).exists()


# ── le socle du depot est-il exploitable ? ──────────────────────────────────

def test_le_socle_du_depot_est_utilisable():
    import forge_capability_ratchet as R

    gele = json.loads(Path(R.SOCLE).read_text(encoding="utf-8"))
    caps = gele.get("capacites", {})
    assert caps, "socle vide -- regenerer avec --ecrire-socle"
    garanties = [v for v in caps.values() if v.get("tier") == "garanti"]
    # Un socle ou TOUT est garanti arme un blocage permanent et finit desarme ;
    # un socle ou RIEN ne l'est ne bloque jamais. Les deux sont des faux gardes.
    assert 0 < len(garanties) < len(caps)
    for v in caps.values():
        assert v.get("tier") in {"garanti", "opportuniste"}
        assert v.get("forme")
