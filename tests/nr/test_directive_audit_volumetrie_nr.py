# -*- coding: utf-8 -*-
"""NR — un comptage d'erreurs sans denominateur ne se juge pas.

CE QUI A ETE PAYE (2026-09-18). En repondant a « est-ce que l'auto-amelioration a
servi », l'index d'enquetes donnait : aveux d'erreur par session **11,93 en aout,
28,68 en septembre** (mediane 7 -> 16, max 43 -> 112). Impossible d'en tirer quoi que
ce soit : si les sessions ont simplement grossi, la hausse est un artefact. Le
denominateur n'existait nulle part, et la mesure est restee INEXPLOITABLE.

`forge_recurrence_audit` ne peut pas le produire : il rend `ILLISIBLE` sur
`~/.claude/projects` depuis le compte du hub -- et c'est un REFUS CORRECT, pas une
panne a contourner en forcant des droits. Le seul module qui tourne du cote ou les
transcripts sont lisibles est `forge_directive_audit`, au SessionStart, et il les
parcourt DEJA. Le denominateur s'ajoute donc a son depot, sans nouveau scan ni
nouveau canal.

MORSURE PRINCIPALE (`test_le_denominateur_compte_les_EVENEMENTS`) : le compteur doit
porter sur les evenements du transcript, PAS sur les messages owner. Ce dernier
denominateur est biaise, et le biais a deja ete paye le 2026-07-30 -- un mois riche
en « ok » / « go » fait baisser mecaniquement tout taux rapporte a lui. Un transcript
ou l'assistant parle beaucoup et l'owner peu doit donc montrer un ecart FRANC entre
les deux compteurs ; s'ils se suivent, c'est que le mauvais est utilise.

Hermetique : transcripts fabriques en tmp_path, aucune lecture du corpus reel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_directive_audit as FDA  # noqa: E402


def _transcript(dossier: Path, nom: str, n_assistant: int, messages_owner: list[str]) -> Path:
    """Transcript JSONL minimal : du bruit assistant, puis les messages owner."""
    f = dossier / (nom + ".jsonl")
    lignes = []
    for i in range(n_assistant):
        lignes.append(json.dumps({"type": "assistant", "timestamp": "2026-09-18T10:00:00Z",
                                  "message": {"content": [{"type": "text", "text": "bloc %d" % i}]}}))
    for m in messages_owner:
        lignes.append(json.dumps({"type": "user", "timestamp": "2026-09-18T10:00:00Z",
                                  "message": {"content": [{"type": "text", "text": m}]}}))
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return f


def test_le_denominateur_compte_les_EVENEMENTS(tmp_path):
    """MORSURE — le volume ne doit PAS se confondre avec le nombre de messages owner."""
    f = _transcript(tmp_path, "aaaaaaaa", n_assistant=200,
                    messages_owner=["ok", "go", "continue quand meme sur ce point precis"])
    c: dict = {}
    textes, _ts = FDA.messages_owner(f, c)
    assert c["lignes"] == 203, "les evenements assistant ne sont pas comptes : %s" % c
    assert c["messages_owner"] == 3
    assert c["lignes"] > 10 * c["messages_owner"], (
        "les deux compteurs se suivent : le denominateur biaise (messages owner) "
        "serait indistinguable du volume reel, exactement le piege du 2026-07-30")


def test_le_compteur_est_optionnel_et_ne_casse_aucun_appelant(tmp_path):
    """La signature d'origine doit continuer de fonctionner telle quelle."""
    f = _transcript(tmp_path, "bbbbbbbb", 5, ["une directive durable et generale ici"])
    textes, ts = FDA.messages_owner(f)          # sans compteurs, comme avant
    assert isinstance(textes, list) and ts


def test_la_volumetrie_est_rendue_par_session(tmp_path):
    """Chaque session porte son volume : un agregat sans detail ne se verifie pas."""
    _transcript(tmp_path, "cccccccc", 50, ["il faut toujours mesurer avant d agir"])
    _transcript(tmp_path, "dddddddd", 10, ["ok"])
    res = FDA.directives(tmp_path)
    assert res["etat"] == "ok", res
    vol = {v["session"]: v for v in res["volumetrie"]}
    assert set(vol) == {"cccccccc", "dddddddd"}, vol
    assert vol["cccccccc"]["lignes"] == 51
    assert vol["dddddddd"]["lignes"] == 11


def test_un_dossier_illisible_ne_rend_pas_une_volumetrie_vide(tmp_path):
    """ILLISIBLE n'est pas « zero session » : sinon l'absence se lit rassurante."""
    res = FDA.directives(tmp_path / "nexiste_pas")
    assert res["etat"] == "ILLISIBLE", res
    assert "volumetrie" not in res, (
        "un etat ILLISIBLE ne doit pas porter de volumetrie, meme vide : "
        "un lecteur la prendrait pour une mesure")


def test_le_depot_transporte_la_volumetrie():
    """Dette de cablage : la volumetrie pourrait etre calculee et jamais deposee."""
    import inspect
    src = inspect.getsource(FDA)
    i = src.find("persona_directives.json")
    assert i > 0, "l'artefact de depot a disparu"
    assert '"volumetrie"' in src[i:i + 2000], (
        "la volumetrie est calculee mais PAS deposee : elle resterait invisible "
        "a `forge_recurrence_audit`, donc sans effet")
