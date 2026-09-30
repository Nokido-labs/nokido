# -*- coding: utf-8 -*-
"""forge_m2m_conformance.py — compteur de conformite M2M (OBSERVATION SEULE).

POURQUOI CE MODULE EXISTE. `forge_m2m_protocol.check` publiait deja les
VIOLATIONS sur le bus (`m2m_violation`) et jamais les messages conformes. On
avait donc un NUMERATEUR SANS DENOMINATEUR : 2836 violations mesurees du
2026-07-05 au 2026-09-01, sans savoir si cela fait 5 % ou 95 % du trafic. Un
taux inconnu n'autorise aucune decision, et c'est exactement ce qui manquait
pour armer le garde en mode `error` sans risquer de rendre le corps muet.

CE QU'IL NE FAIT PAS : il n'ajoute aucun protocole, ne change aucun verdict et
ne refuse rien. Il compte ce que le validateur decide deja. Le jour ou le mode
passe a `error`, c'est `check()` qui refuse, jamais ce module.

TROIS ETATS, JAMAIS DEUX. Un `pointer_ref` est RESOLU, INTROUVABLE ou
NON_VERIFIABLE. Tant qu'aucun resolveur n'est branche, le compteur
`invalid_pointer_ref` reste a zero parce qu'il n'a PAS D'EMETTEUR -- ce n'est
pas un zero mesure, et l'etat le dit explicitement. Declarer invalide ce qu'on
ne sait pas verifier fabriquerait des defauts.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

# Le module declare son organe : sans cette ligne le census le classe `non classe`,
# et un module non classe est un module dont personne ne surveille la regulation.
# ATTENTION au vocabulaire : le deducteur (`forge_module_census._organ_by_text`)
# reconnait des MOTS-CLES, pas les noms d'organes. `SNC/...` est REFUSE (mesure
# 2026-09-01) alors que `cerveau/` et `moelle/` passent ; `observabilite/` et
# `trace/` classent en Observabilite/Trace, ce que ce compteur EST.
__FORGE_COLOR__ = "observabilite/conformite-canal-m2m"

_ROOT = Path(__file__).resolve().parent.parent
_ETAT = _ROOT / "sandbox" / "m2m_conformance.json"

# Verdicts que le validateur considere comme acceptables.
_CODES_OK = frozenset({"M2M_OK", "M2M_OK_PROSE"})

# Schemas de pointer_ref reconnus. Reconnaitre n'est PAS resoudre : la presence
# d'un schema connu ne prouve pas que la cible existe.
_SCHEMAS = ("bb:", "blackboard:", "commit ", "git:", "rag:", "sandbox/", "docs/",
            "critical_events:", "organ_pulse:", "file:", "job:", "tests/")

_VERROU = threading.Lock()
_FLUSH_SECONDES = 30.0
_FLUSH_COUPS = 200

_compteurs: Dict[str, Any] = {}
_depuis_flush = 0
_dernier_flush = 0.0


def _neuf() -> Dict[str, Any]:
    return {
        "messages_total": 0,
        "messages_conformes": 0,
        "missing_intent": 0,
        "missing_pointer_ref": 0,
        "invalid_pointer_ref": 0,
        "prose_trop_longue": 0,
        "intent_inconnu": 0,
        "par_canal": {},
        "par_code": {},
        "depuis": time.time(),
        "maj": 0.0,
    }


def _charger() -> None:
    global _compteurs, _dernier_flush
    if _compteurs:
        return
    try:
        _compteurs = json.loads(_ETAT.read_text(encoding="utf-8"))
        for k, v in _neuf().items():
            _compteurs.setdefault(k, v)
    except Exception:  # noqa: BLE001 - etat absent ou illisible : on repart a neuf
        _compteurs = _neuf()
    _dernier_flush = time.time()


def _ecrire() -> None:
    """Ecriture atomique : un lecteur ne doit jamais voir un fichier tronque."""
    global _depuis_flush, _dernier_flush
    try:
        _ETAT.parent.mkdir(parents=True, exist_ok=True)
        _compteurs["maj"] = time.time()
        tmp = _ETAT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_compteurs, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _ETAT)
        _depuis_flush = 0
        _dernier_flush = time.time()
    except OSError as e:
        print(f"[m2m_conformance] etat NON persiste ({e}) | consequence: le taux "
              f"repartira de zero au prochain demarrage", flush=True)


def pointer_statut(ref: Any) -> str:
    """RESOLU | INTROUVABLE | NON_VERIFIABLE | MANQUANT.

    Aucun resolveur n'est branche : un schema reconnu rend NON_VERIFIABLE, pas
    RESOLU. Le jour ou une resolution existera, seul ce point changera.
    """
    if ref is None or (isinstance(ref, str) and not ref.strip()):
        return "MANQUANT"
    s = str(ref).strip()
    if any(s.startswith(p) for p in _SCHEMAS):
        return "NON_VERIFIABLE"
    return "NON_VERIFIABLE"


def noter(canal: str, verdict: Dict[str, Any] | None) -> None:
    """Compte UN verdict rendu par `forge_m2m_protocol.validate`.

    Best-effort : ce compteur ne doit jamais casser un canal (meme contrat que
    `publish` sur le bus).
    """
    if not isinstance(verdict, dict):
        return
    try:
        with _VERROU:
            _charger()
            global _depuis_flush
            code = str(verdict.get("code") or "")
            _compteurs["messages_total"] += 1
            _compteurs["par_canal"][str(canal)] = _compteurs["par_canal"].get(str(canal), 0) + 1
            _compteurs["par_code"][code] = _compteurs["par_code"].get(code, 0) + 1
            if code in _CODES_OK:
                _compteurs["messages_conformes"] += 1
            elif code == "M2M_ERR_UNKNOWN_INTENT":
                _compteurs["intent_inconnu"] += 1
            elif code == "M2M_WARN_PROSE":
                _compteurs["prose_trop_longue"] += 1
            for v in verdict.get("violations") or []:
                t = str(v)
                if "intent" in t and ("absent" in t or "manquant" in t):
                    _compteurs["missing_intent"] += 1
                elif "pointer_ref" in t and "manquant" in t:
                    _compteurs["missing_pointer_ref"] += 1
            _depuis_flush += 1
            if (_depuis_flush >= _FLUSH_COUPS
                    or time.time() - _dernier_flush >= _FLUSH_SECONDES):
                _ecrire()
    except Exception:  # noqa: BLE001  # muet-ok : un compteur ne casse jamais un canal
        pass


def etat() -> Dict[str, Any]:
    """Compteurs + le taux, avec ce qui N'EST PAS mesurable dit explicitement."""
    with _VERROU:
        _charger()
        d = json.loads(json.dumps(_compteurs))
    total = d.get("messages_total", 0)
    d["taux_conformite"] = (d["messages_conformes"] / total) if total else None
    d["non_conformes"] = total - d["messages_conformes"]
    d["non_emis"] = {
        "invalid_pointer_ref": "aucun resolveur de pointer_ref n'est branche : "
                               "ce zero est une ABSENCE D'EMETTEUR, pas une mesure",
    }
    if not total:
        d["reserve"] = ("aucun message compte : le compteur n'est pas cable, ou le "
                        "hub n'a pas redemarre depuis son cablage. Ne pas lire ce "
                        "vide comme un trafic nul.")
    return d


def reinitialiser() -> None:
    """Remet les compteurs a zero (tests, ou nouvelle fenetre de mesure)."""
    global _compteurs, _depuis_flush
    with _VERROU:
        _compteurs = _neuf()
        _depuis_flush = 0
        _ecrire()


def _main() -> int:
    d = etat()
    t = d.get("taux_conformite")
    print(f"messages_total       {d['messages_total']}")
    print(f"messages_conformes   {d['messages_conformes']}"
          f"{'' if t is None else f'  ({t * 100:.2f} %)'}")
    print(f"non_conformes        {d['non_conformes']}")
    for k in ("missing_intent", "missing_pointer_ref", "invalid_pointer_ref",
              "prose_trop_longue", "intent_inconnu"):
        print(f"{k:20} {d[k]}")
    print("par_canal :", d.get("par_canal"))
    print("par_code  :", d.get("par_code"))
    for k, v in d.get("non_emis", {}).items():
        print(f"NON EMIS  {k} : {v}")
    if "reserve" in d:
        print("RESERVE :", d["reserve"])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
