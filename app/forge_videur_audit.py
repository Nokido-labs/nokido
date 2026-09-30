# -*- coding: utf-8 -*-
"""forge_videur_audit.py — vue d'audit AGREGEE du videur (OBSERVATION SEULE).

__FORGE_COLOR__ = "observabilite/vue-audit-videur"

POURQUOI CE MODULE EXISTE
    Le journal du videur (`sandbox/videur_identity.log`, 131 Mo) est chiffre en
    DPAPI **USER scope** : mesure du 2026-09-02, il appartient a `DESKTOP-…\\user`
    et le compte de service (`LaForgeSbxOffline`, USERPROFILE=C:\\Users\\Default)
    n'a meme pas de magasin DPAPI -- `CryptUnprotectData` rend « fichier
    introuvable ». C'est une FRONTIERE D'ACCES voulue, pas une panne : la trace
    forensique appartient a l'owner.

    Consequence : aucune statistique ne peut etre construite en RELISANT ce
    journal depuis le corps. La vue doit donc etre produite AU MOMENT de
    l'observation, sur le chemin reel, exactement comme `forge_m2m_conformance`.

CE QU'ELLE PERMET DE MESURER, ET QUI EST LA QUESTION DU JOUR
    `via=master_token` conserve l'agent declare dans l'en-tete ET son ring : le
    porteur du maitre DEVIENT l'agent qu'il nomme (mesure : maitre + CLAUDE ->
    ring 1). Avant de durcir ce comportement il faut savoir s'il est ENCORE
    UTILISE, et par qui -- durcir sans mesurer, c'est le `m2m_mode=error` arme a
    100 % de refus le meme soir.

        master_token_total          combien d'appels par le maitre
        master_token_as_master      dont ceux qui s'annoncent MASTER (honnetes)
        master_token_impersonation  dont ceux qui prennent un AUTRE nom

CE QU'ELLE N'EXPOSE JAMAIS
    Aucun token, JWT, cle, certificat, ni payload. `agent` est une IDENTITE
    LOGIQUE (VIBE, CLAUDE, MASTER) et non un secret : c'est precisement ce qui
    rend la ventilation lisible sans rien divulguer. `token_h` est volontairement
    ECARTE, meme s'il est deja hashe.

CE QU'ELLE NE FAIT PAS
    Aucun verdict. Elle ne decide rien, ne refuse rien, ne modifie ni
    `resolve_identity`, ni `authorize`, ni un ring, ni un scope.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

__FORGE_COLOR__ = "observabilite/vue-audit-videur"

_ROOT = Path(__file__).resolve().parent.parent
_VUE = _ROOT / "sandbox" / "videur_audit_view.json"

_VERROU = threading.Lock()
_FLUSH_COUPS = 100
_FLUSH_SECONDES = 30.0

_vue: Dict[str, Any] = {}
_depuis_flush = 0
_dernier_flush = 0.0

# Champs comptes. `token_h` est ABSENT de cette liste : deja hashe, il n'a
# aucune valeur d'agregation et sa place est dans la trace forensique.
#
# `acteur` / `sujet` ajoutes le 2026-09-21 (P1-S). Mesure qui l'exige : sur
# 314 206 observations, via/agent/ring/tool sont renseignes a 100 %, la
# `decision` manque dans 93,7 % des cas, et la PROVENANCE n'etait comptee
# NULLE PART -- alors que `capture()` la recoit deja.
#
#     UNE ABSENCE D'AXE N'EST PAS UNE ABSENCE DE DONNEE
#
# Ce sont deux questions distinctes et jamais interchangeables : `agent` dit
# QUI porte l'appel, `acteur` dit AU NOM DE QUI il agit. Les confondre est la
# confusion que la campagne d'autorite mesure.
_AXES = ("via", "agent", "tool", "decision", "reason", "scope", "ring",
         "acteur", "sujet")


def _neuf() -> Dict[str, Any]:
    return {
        "total": 0,
        **{f"by_{a}": {} for a in _AXES},
        # Ventilation dediee : la seule question qui decide du durcissement.
        "master_token": {
            "total": 0, "as_master": 0, "impersonation": 0,
            "by_agent": {}, "by_tool": {}, "by_decision": {}, "by_reason": {},
        },
        # Croisement agent x via : LA question du volet identification (2026-09-06).
        # `by_via` et `by_agent` separes disaient « 5 970 baux, 650 en-tetes nus,
        # 2 657 impersonations » sans jamais dire QUI porte quoi -- or la doctrine
        # RBAC anatomique exige que chaque organe porte SON marqueur. Cle "AGENT|via".
        "by_agent_via": {},
        # ECART SI BORNE -- 2026-09-21. `resolve_identity` expose ce que le ring
        # VAUDRAIT si le plancher anti-spoof s'appliquait aussi au porteur du
        # maitre. Le champ etait produit et lu par PERSONNE : PRODUCED != CONSUMED.
        #
        # Pourquoi le compter ICI plutot que l'estimer : l'estimation « 33 % du
        # trafic » croisait une table STATIQUE de rings avec des volumes cumules.
        # Elle suppose que la composition du trafic ne bouge pas, et ne dit rien
        # de l'instant. Une decision d'AUTORITE se prend sur une mesure vivante.
        #
        # Ce compteur n'arme rien et ne modifie aucun ring. Il OBSERVE.
        "ecart_si_borne": {"observes": 0, "declasses": 0, "illisibles": 0,
                           "by_agent": {}},
        "window_start": None, "window_end": None,
        "lifetime_start": time.time(),
    }


def _charger() -> None:
    global _vue, _dernier_flush
    if _vue:
        return
    try:
        _vue = json.loads(_VUE.read_text(encoding="utf-8"))
        for k, v in _neuf().items():
            _vue.setdefault(k, v)
    except Exception:  # noqa: BLE001  # muet-ok : vue absente ou illisible -> on repart
        _vue = _neuf()
    _dernier_flush = time.time()


def _ecrire() -> None:
    """Ecriture ATOMIQUE : un lecteur ne doit jamais voir un fichier tronque."""
    global _depuis_flush, _dernier_flush
    try:
        _VUE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _VUE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_vue, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _VUE)
        _depuis_flush = 0
        _dernier_flush = time.time()
    except OSError as e:
        print(f"[videur_audit] vue NON persistee ({e}) | consequence: les compteurs "
              f"repartiront de zero au prochain demarrage", flush=True)


def _incr(d: dict, cle: Any) -> None:
    k = "(absent)" if cle is None or cle == "" else str(cle)
    d[k] = d.get(k, 0) + 1


def noter(identity: Dict[str, Any] | None, tool: str = "",
          extra: Dict[str, Any] | None = None) -> None:
    """Compte UNE observation du videur. Best-effort : ne casse jamais un appel.

    ATTENTION AU DENOMINATEUR : `capture()` est invoquee a CHAQUE point de
    controle traverse. Une meme requete HTTP peut donc etre comptee PLUSIEURS
    fois -- mesure a l'identique sur le compteur M2M, ou un notify unique a
    produit 3 comptages. `total` compte donc des OBSERVATIONS, pas des requetes.
    Les taux restent justes (meme denominateur des deux cotes) ; le volume, non.
    """
    if not isinstance(identity, dict):
        return
    try:
        with _VERROU:
            _charger()
            global _depuis_flush
            ex = extra or {}
            valeurs = {
                "via": identity.get("via"), "agent": identity.get("agent"),
                "ring": identity.get("ring"), "tool": tool,
                "decision": ex.get("decision"), "reason": ex.get("reason"),
                "scope": ex.get("scope") or ex.get("required_scope"),
                # Lue dans l'IDENTITE puis dans `extra` : `_resolve_ring` la
                # passe en SUPPLEMENT, et ne lire qu'un seul emplacement
                # rendrait 100 % d'absence sur le chemin REEL.
                #
                # Aucune valeur de repli, jamais l'agent a defaut : une
                # provenance non resolue reste `(absent)`.
                #
                #     ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE
                #     une absence se voit, une invention se croit
                "acteur": identity.get("acteur") or ex.get("acteur"),
                "sujet": identity.get("sujet") or ex.get("sujet"),
            }
            _vue["total"] += 1
            for a in _AXES:
                _incr(_vue[f"by_{a}"], valeurs[a])
            _incr(_vue.setdefault("by_agent_via", {}),
                  f"{valeurs['agent'] or '(absent)'}|{valeurs['via'] or '(absent)'}")
            maintenant = time.time()
            if _vue.get("window_start") is None:
                _vue["window_start"] = maintenant
            _vue["window_end"] = maintenant

            if valeurs["via"] == "master_token":
                m = _vue["master_token"]
                m["total"] += 1
                agent = str(valeurs["agent"] or "").upper()
                # « MASTER_TOKEN » est le nom honnete ; tout autre nom porte par
                # le maitre est une usurpation d'identite applicative.
                if agent in ("MASTER", "MASTER_TOKEN"):
                    m["as_master"] += 1
                else:
                    m["impersonation"] += 1
                _incr(m["by_agent"], valeurs["agent"])
                _incr(m["by_tool"], tool)
                _incr(m["by_decision"], valeurs["decision"])
                _incr(m["by_reason"], valeurs["reason"])

                # Combien d'appels SERAIENT declasses si l'on armait le plancher,
                # et LESQUELS. Un total ne suffit pas : couper 33 % du trafic n'a
                # pas le meme sens selon que c'est le superviseur ou un client
                # anonyme.
                e = _vue.setdefault(
                    "ecart_si_borne",
                    {"observes": 0, "declasses": 0, "illisibles": 0, "by_agent": {}})
                try:
                    _reel = int(identity.get("ring"))
                    _borne = int(identity.get("ring_si_borne"))
                except (TypeError, ValueError):
                    # UNKNOWN != NO : ce qui n'a PAS pu etre juge se compte a
                    # part, jamais du cote sain.
                    e["illisibles"] = e.get("illisibles", 0) + 1
                else:
                    e["observes"] += 1
                    if _borne > _reel:
                        e["declasses"] += 1
                        _incr(e["by_agent"], valeurs["agent"])

            _depuis_flush += 1
            if (_depuis_flush >= _FLUSH_COUPS
                    or time.time() - _dernier_flush >= _FLUSH_SECONDES):
                _ecrire()
    except Exception:  # noqa: BLE001  # muet-ok : une vue ne casse jamais l'auth
        pass


def vue() -> Dict[str, Any]:
    """Rend la vue, avec ce qui N'EST PAS mesurable dit explicitement."""
    with _VERROU:
        _charger()
        d = json.loads(json.dumps(_vue))
    d["note_denominateur"] = (
        "`total` compte des OBSERVATIONS (points de controle traverses), pas des "
        "requetes : une requete peut en produire plusieurs.")
    d["non_exposes"] = ["token", "token_h", "jwt", "cle", "certificat", "payload"]
    d.setdefault("ecart_si_borne",
                 {"observes": 0, "declasses": 0, "illisibles": 0, "by_agent": {}})
    d["ecart_si_borne"]["note"] = (
        "compte les OBSERVATIONS du porteur du maitre dont le ring CHANGERAIT "
        "si le plancher anti-spoof lui etait applique. N'arme rien, ne refuse "
        "rien : c'est le chiffre qui permet de decider, pas la decision.")
    d["note_agent_via"] = (
        "`by_agent_via` (cle AGENT|via) ne compte que depuis le redemarrage du hub "
        "qui l'a charge (2026-09-06) : une vue chargee avant n'en porte aucune, "
        "ce vide n'est pas une absence de trafic.")
    if not d["total"]:
        d["reserve"] = (
            "aucune observation comptee : la vue n'est pas cablee dans capture(), "
            "ou le hub n'a pas redemarre depuis son cablage. Ne pas lire ce vide "
            "comme une absence de trafic.")
    return d


def reinitialiser() -> None:
    """Ouvre une nouvelle fenetre. NE TOUCHE PAS au journal forensique."""
    global _vue, _depuis_flush
    with _VERROU:
        garde = _vue.get("lifetime_start") if _vue else None
        _vue = _neuf()
        if garde:
            _vue["lifetime_start"] = garde
        _depuis_flush = 0
        _ecrire()


def _main() -> int:
    import datetime as _dt
    d = vue()
    def _h(t):
        return _dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "-"
    print(f"observations         {d['total']}")
    print(f"fenetre              {_h(d.get('window_start'))} -> {_h(d.get('window_end'))}")
    m = d["master_token"]
    print(f"\nmaster_token total   {m['total']}")
    print(f"  as_master          {m['as_master']}")
    print(f"  IMPERSONATION      {m['impersonation']}   <- master + agent != MASTER")
    if m["by_agent"]:
        print("  par agent          ", dict(sorted(m["by_agent"].items(), key=lambda kv: -kv[1])[:8]))
    if m["by_tool"]:
        print("  par tool           ", dict(sorted(m["by_tool"].items(), key=lambda kv: -kv[1])[:8]))
    for a in ("via", "agent", "ring", "decision"):
        v = d.get(f"by_{a}") or {}
        if v:
            print(f"\nby_{a:9}        ", dict(sorted(v.items(), key=lambda kv: -kv[1])[:8]))
    if "reserve" in d:
        print("\nRESERVE :", d["reserve"])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
