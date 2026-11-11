# -*- coding: utf-8 -*-
"""NR -- 9/11 : depuis la cle OpenCode Zen au coffre (50b09def9), le modele PAR DEFAUT d'OpenCode passe par le COMPTE
(payant) : un `repli_modele` vide ("" = modele par defaut) a rendu « Insufficient account funds » (provider.quota) sur
les taches de GLM (job_06a65587, job_9aae541c). Un repli d'instance OpenCode est soit absent, soit un modele GRATUIT
explicite -- jamais le defaut silencieux."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "config" / "opencode_instances.json").read_text(encoding="utf-8"))


def _gratuit(modele: str) -> bool:
    m = modele.strip().lower()
    return m.endswith("-free") or m.endswith(":free") or m.startswith(("ollama/", "lmstudio/"))


def test_aucun_repli_vide_vers_le_defaut_payant():
    fautifs = [k for k, v in CFG.items() if isinstance(v, dict) and not k.startswith("_")
               and "repli_modele" in v and not str(v["repli_modele"] or "").strip()]
    assert not fautifs, "repli_modele vide = modele par defaut OpenCode, PAYANT avec la cle : %s" % fautifs


def test_tout_repli_declare_est_gratuit():
    payants = [(k, v["repli_modele"]) for k, v in CFG.items() if isinstance(v, dict) and not k.startswith("_")
               and str(v.get("repli_modele") or "").strip() and not _gratuit(str(v["repli_modele"]))]
    assert not payants, payants


def test_un_repli_ollama_cloud_a_toujours_un_repli_gratuit_derriere():
    # Ollama Cloud epuise (quota mensuel) + aucun repli_modele -> chemin du modele par defaut, payant avec la cle.
    nus = [k for k, v in CFG.items() if isinstance(v, dict) and not k.startswith("_")
           and v.get("repli_ollama_cloud") and not str(v.get("repli_modele") or "").strip()]
    assert not nus, nus


def test_tout_principal_opencode_zen_est_gratuit():
    zen = [(k, v["modele"]) for k, v in CFG.items() if isinstance(v, dict) and not k.startswith("_")
           and str(v.get("modele") or "").startswith("opencode/") and not _gratuit(str(v["modele"]))]
    assert not zen, zen
