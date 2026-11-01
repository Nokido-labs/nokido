# -*- coding: utf-8 -*-
"""NR -- 30/10 : la voie sans boucle rendait des drapeaux INVENTES (CODEX_MAX_TURNS, context_compaction) malgre la
consigne. Juge deterministe : un nom en `code` ou **gras** absent mot pour mot du dossier est marque et compte."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_enquete_sans_boucle as fesb  # noqa: E402


def test_nom_present_inchange_nom_invente_marque():
    dossier = "codex exec -c model_reasoning_effort=low ; AGENTS.md"
    texte = "Reglages : `model_reasoning_effort`, `CODEX_MAX_TURNS`, **AGENTS.md**, **context_compaction**."
    sortie, absents = fesb._marquer_noms_inventes(texte, dossier)
    assert absents == {"CODEX_MAX_TURNS", "context_compaction"}
    assert "`model_reasoning_effort`," in sortie  # present : intact
    assert "`CODEX_MAX_TURNS` [ABSENT DU DOSSIER]" in sortie
    assert "**context_compaction** [ABSENT DU DOSSIER]" in sortie


def test_refus_pare_feu_n_est_pas_une_reponse(tmp_path, monkeypatch):
    """30/10 : « [FIREWALL] envoi cloud bloque » etait clos OK_DONE. Il doit faire passer au fournisseur suivant."""
    monkeypatch.setenv("LAFORGE_TOKEN_CACHE_DIR", str(tmp_path))
    vus = []

    def faux(f, prompt):
        vus.append(f)
        if len(vus) == 1:
            return True, "[FIREWALL] envoi cloud bloque (x) : Prompt injection detectee", {}
        return True, "reponse locale", {}

    res = fesb.executer_enquete("q", [], [], str(tmp_path / "s.md"), fournisseur="groq", caller_fn=faux)
    assert len(vus) == 2 and res["fournisseur"] != "groq"
    assert "reponse locale" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_quota_journalier_vu_est_consigne_au_census(monkeypatch):
    vus = []
    import types
    faux = types.ModuleType("forge_free_tier_census")
    faux.consigner_quota_epuise = lambda f, m, d: vus.append((f, m))
    monkeypatch.setitem(sys.modules, "forge_free_tier_census", faux)
    err = ("RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b`"
           " in organization org_x service tier on_demand on tokens per day (TPD)'}}")
    fesb._consigner_quota_vu("groq", err)
    assert vus == [("groq", "openai/gpt-oss-120b")]
    fesb._consigner_quota_vu("groq", "Timeout apres 60s")  # pas un quota : rien
    assert len(vus) == 1


def test_premier_fournisseur_est_le_plus_fort():
    assert fesb.premier_fournisseur_gratuit() == fesb.FOURNISSEURS_GRATUITS_DEFAUT[0]


def test_phrases_en_gras_ignorees():
    sortie, absents = fesb._marquer_noms_inventes("**Points d'incertitude** et **Effet sur les tokens**", "")
    assert absents == set()
