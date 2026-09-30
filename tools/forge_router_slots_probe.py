#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Chaque slot du routeur est-il REELLEMENT appelable ?

Le 2026-08-18 on a decouvert que les 7 slots `github_*`, ajoutes en avril avec
la mention « 7 modeles testes OK », pointent sur un backend que GitHub a RETIRE
(410 Gone, mesure y compris sur une inference reelle). Personne ne l'avait vu :
le routeur mesure l'EXISTENCE d'un slot, jamais sa joignabilite.

TROIS COUCHES, et c'est tout le sujet :
  * `forge_llm_router.PROVIDERS` — la table de ROUTAGE (31 slots) ;
  * `forge_agent_proxy`          — le RUNTIME qui APPELLE vraiment ;
  * `forge_endpoint_registry`    — l'identite federee qui reconcilie les deux.
Un slot routable dont aucun runtime ne sait faire l'appel est un slot MORT qui
se presente comme vivant. On ne reconstruit donc aucune URL ici — une seconde
table d'URLs finirait par diverger de celle qui sert : on interroge le runtime.

TROIS VERDICTS, jamais deux :
  VIVANT       le runtime repond (ou se declare pret en mode preflight) ;
  MORT         le runtime existe et refuse explicitement (cle absente, 410…) ;
  NON_MESURE   aucun runtime ne porte ce slot, ou la sonde n'a pas pu conclure.
Confondre MORT et NON_MESURE est l'erreur qui a fabrique 21 faux morts le
2026-08-11 — d'ou la troisieme colonne.

COUT : `--live` envoie un « ping » de 1 token aux providers declares prets.
Sans ce drapeau, seul le preflight tourne, et il ne consomme aucun quota.

Usage :
    run action=run_job script=tools/forge_router_slots_probe.py online=true
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SORTIE = ROOT / "sandbox" / "router_slots_probe.json"
PING = "ping"


def slots_routeur() -> dict[str, dict]:
    from nokido_agent.app.forge_llm_router import PROVIDERS

    return dict(PROVIDERS)


def runtimes() -> dict[str, object]:
    """Providers que le runtime sait instancier, par nom."""
    from nokido_agent.app import forge_agent_proxy as AP

    noms = []
    try:
        noms = list(AP.list_providers() or [])
    except Exception as exc:  # noqa: BLE001
        print(f"[avert] list_providers indisponible ({type(exc).__name__}) — "
              f"la colonne runtime sera NON_MESURE")
    out = {}
    for n in noms:
        nom = n if isinstance(n, str) else (n.get("name") if isinstance(n, dict) else str(n))
        try:
            p = AP.get_provider(nom)
        except Exception:  # noqa: BLE001 - provider non instanciable
            p = None
        if p is not None:
            out[nom] = p
    return out


def correspondance(slot: str, dispo: dict[str, object]) -> str:
    """Nom runtime pour un slot du routeur, via le registre puis par prefixe."""
    if slot in dispo:
        return slot
    try:
        from nokido_agent.tools.forge_endpoint_registry import resolve

        fiche = resolve(slot) or {}
        rt = fiche.get("runtime")
        if rt and rt in dispo:
            return rt
    except Exception:  # noqa: BLE001 - registre absent
        pass
    famille = slot.split("_")[0]
    for nom in dispo:
        if nom == famille or nom.startswith(famille):
            return nom
    return ""


def _interroger(prov, timeout: int = 15) -> tuple[bool, str]:
    """(a repondu, motif). `Provider.ask` est ASYNC et prend cinq arguments :
    `(message, thread_messages, system_prompt, max_tokens, timeout)`.

    MESURE 2026-08-18, ma propre faute : appelee `ask(prompt)`, elle levait
    `TypeError: missing 4 required positional arguments` sur TREIZE providers,
    que la sonde a alors declares MORTS. Une sonde qui ne sait pas demander
    fabrique des cadavres — exactement le defaut du 2026-08-11. D'ou le garde
    ci-dessous : une erreur de SIGNATURE n'est jamais un verdict sur le service.
    """
    try:
        # `max_tokens=1` coupait AVANT le premier mot : plusieurs providers
        # rendaient une chaine vide et la sonde les comptait morts (troisieme
        # artefact du 2026-08-18). 16 tokens coutent une misere et suffisent a
        # obtenir du texte.
        appel = prov.ask("ping", [], "", 16, timeout)
        rep = asyncio.run(appel) if inspect.isawaitable(appel) else appel
    except TypeError as exc:
        return False, f"SONDE INADAPTEE ({exc})"[:90]
    except Exception as exc:  # noqa: BLE001 - l'echec d'un provider n'arrete pas la passe
        return False, f"{type(exc).__name__}: {exc}"[:90]
    texte = str(rep or "")
    if not texte:
        # Ni une reponse ni un refus : on ne sait pas. NON_MESURE, pas MORT.
        return False, "SONDE INADAPTEE (reponse vide, aucun message d'erreur)"
    if texte.lower().startswith(("error", "erreur")):
        return False, texte[:90]
    return True, ""


def _preflight(prov) -> tuple[bool, str]:
    try:
        pret = bool(prov.is_available())
    except Exception as exc:  # noqa: BLE001
        return False, f"is_available a leve {type(exc).__name__}"
    if pret:
        return True, ""
    motif = ""
    try:
        motif = str(prov.unavailable_reason() or "")[:70]
    except Exception:  # noqa: BLE001 - motif optionnel
        motif = ""
    return False, motif or "non disponible (sans motif)"


def _budget() -> float:
    """Secondes allouees a la passe live. Depasse -> les restants sont NON_MESURE."""
    for i, a in enumerate(sys.argv):
        if a == "--budget" and i + 1 < len(sys.argv):
            try:
                return float(sys.argv[i + 1])
            except ValueError:
                break
    return 90.0


def main() -> int:
    live = "--live" in sys.argv
    budget = _budget()
    depart = time.time()
    routeur = slots_routeur()
    dispo = runtimes()
    print(f"{len(routeur)} slot(s) de routage · {len(dispo)} runtime(s) instanciable(s) · "
          f"mode {'LIVE (1 token par provider pret)' if live else 'preflight (zero quota)'}")

    lignes = []
    for slot in sorted(routeur):
        rt = correspondance(slot, dispo)
        if not rt:
            lignes.append({"slot": slot, "runtime": "", "etat": "NON_MESURE",
                           "motif": "aucun runtime ne porte ce slot", "secondes": 0.0})
            continue
        pret, motif = _preflight(dispo[rt])
        if not pret:
            lignes.append({"slot": slot, "runtime": rt, "etat": "MORT",
                           "motif": motif, "secondes": 0.0})
            continue
        if not live:
            lignes.append({"slot": slot, "runtime": rt, "etat": "PRET",
                           "motif": "preflight seul", "secondes": 0.0})
            continue
        if time.time() - depart > budget:
            # Un slot non interroge faute de temps n'est PAS un slot mort.
            lignes.append({"slot": slot, "runtime": rt, "etat": "NON_MESURE",
                           "motif": f"budget de {budget:.0f}s epuise", "secondes": 0.0})
            continue
        debut = time.time()
        ok, motif = _interroger(dispo[rt])
        # Une sonde inadaptee ne prouve RIEN sur le service : NON_MESURE.
        etat = "VIVANT" if ok else ("NON_MESURE" if motif.startswith("SONDE INADAPTEE") else "MORT")
        lignes.append({"slot": slot, "runtime": rt, "etat": etat, "motif": motif,
                       "secondes": round(time.time() - debut, 2)})

    print(f"\n{'slot':26} {'runtime':22} {'etat':12} {'s':>5}  motif")
    for x in lignes:
        print(f"  {x['slot']:24} {x['runtime'][:20]:22} {x['etat']:12} "
              f"{x['secondes']:>5}  {x['motif']}")

    compte: dict[str, int] = {}
    for x in lignes:
        compte[x["etat"]] = compte.get(x["etat"], 0) + 1
    print("\nRESUME :", ", ".join(f"{k}={v}" for k, v in sorted(compte.items())))
    orphelins = sorted(n for n in dispo if not any(x["runtime"] == n for x in lignes))
    if orphelins:
        print(f"runtimes SANS slot de routage ({len(orphelins)}) : {', '.join(orphelins[:12])}")
        print("  -> capacite presente mais non routable : l'inverse du slot mort")

    # --tous : les orphelins AUSSI sont interroges. Ne sonder que les slots
    # routes laissait hors mesure les 24 runtimes qui n'ont pas de slot — or
    # c'est precisement la que dorment des capacites utilisables (openrouter,
    # lmstudio, litellm, les CLI sous OAuth…). Mesurer d'abord, router ensuite.
    if orphelins and "--tous" in sys.argv:
        print(f"\n--- {len(orphelins)} runtime(s) hors routage ---")
        for nom in orphelins:
            if time.time() - depart > budget:
                lignes.append({"slot": "(hors routage)", "runtime": nom,
                               "etat": "NON_MESURE", "motif": "budget epuise",
                               "secondes": 0.0})
                continue
            pret, motif = _preflight(dispo[nom])
            if not pret:
                etat, secondes = "MORT", 0.0
            elif not live:
                etat, motif, secondes = "PRET", "preflight seul", 0.0
            else:
                debut = time.time()
                ok, motif = _interroger(dispo[nom])
                etat = "VIVANT" if ok else (
                    "NON_MESURE" if motif.startswith("SONDE INADAPTEE") else "MORT")
                secondes = round(time.time() - debut, 2)
            print(f"  {nom:24} {etat:12} {secondes:>5}  {motif}")
            lignes.append({"slot": "(hors routage)", "runtime": nom, "etat": etat,
                           "motif": motif, "secondes": secondes})
        hors = [x for x in lignes if x["slot"] == "(hors routage)"]
        vivants = [x["runtime"] for x in hors if x["etat"] == "VIVANT"]
        print(f"\n  -> {len(vivants)} capacite(s) VIVANTE(S) mais non routable(s) : "
              f"{', '.join(vivants) or 'aucune'}")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"live": live, "slots": lignes,
                                      "runtimes_sans_slot": orphelins},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"detail : {SORTIE.relative_to(ROOT)}")
    except OSError as exc:
        print(f"(rapport non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
