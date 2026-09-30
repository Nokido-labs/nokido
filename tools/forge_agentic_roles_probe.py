#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quels ROLES AGENTIQUES chaque endpoint peut-il reellement tenir ?

Les `use_case` disent QUI REPOND ; les roles disent QUI PEUT FAIRE QUOI dans une
boucle d'agent. Nokido en nomme sept — PLANNER, EXECUTOR, REVIEWER, ROUTER,
SUMMARIZER, SENTINEL, MONITOR — et ils n'ont jamais ete confrontes aux modeles
qui sont censes les tenir.

Chaque role repose sur une aptitude VERIFIABLE, et pas sur une impression :

  REVIEWER   rendre un verdict STRUCTURE (JSON parsable, champs attendus)
  PLANNER    decomposer en etapes numerotees, en JSON exploitable
  ROUTER     choisir UNE etiquette dans un ensemble ferme, sans bavarder
  SENTINEL   verdict binaire immediat sur un extrait
  MONITOR    idem, mais assez economique pour tourner en boucle
  EXECUTOR   appeler des outils (mesure deja faite par forge_tool_call_probe)
  SUMMARIZER condenser — exige surtout une grande fenetre de contexte

Les trois epreuves ci-dessous sont volontairement severes sur la FORME : un
modele qui repond « Bien sur ! Voici le JSON : {...} » casse un parseur en
production. On mesure donc ce qu'un agent recevrait vraiment, pas ce qu'un
humain indulgent lirait entre les lignes.

    run action=run_job script=tools/forge_agentic_roles_probe.py online=true
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.tools.forge_endpoint_commun import catalogue, lire, plus_petits  # noqa: E402

SORTIE = ROOT / "sandbox" / "agentic_roles.json"
TIMEOUT = 40
PAR_FOURNISSEUR = 2

SURFACES = [
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    ("lmstudio", "LMSTUDIO_TOKEN", "http://127.0.0.1:1234/v1"),
]

ETIQUETTES = ("securite", "performance", "lisibilite", "aucun")


def _sans_accents(texte: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn")


def fiche_du_modele(providers: dict, fournisseur: str, modele: str) -> dict:
    """Le slot qui declare CE modele — pas le premier du fournisseur.

    MESURE 2026-08-18 : associer par prefixe donnait a `allam-2-7b` la fiche de
    `groq_fast` (`outils: True`) alors qu'allam REFUSE les outils. Il heritait
    donc d'EXECUTOR, c'est-a-dire du role qu'un slot distinct avait justement
    ete cree pour lui interdire. Un rapprochement approximatif rend un verdict
    faux avec l'aplomb d'un verdict mesure.
    """
    court = modele.split("/")[-1].lower()
    for nom, fiche in (providers or {}).items():
        for declare in (fiche.get("models") or []):
            if str(declare).split("/")[-1].lower() == court:
                return dict(fiche, _slot=nom)
    return {}


def _completer(base: str, cle: str, modele: str, message: str,
               max_tokens: int = 200) -> tuple[str, float, str]:
    """(texte, secondes, motif d'echec). Jamais d'exception vers l'appelant."""
    charge = json.dumps({"model": modele,
                         "messages": [{"role": "user", "content": message}],
                         "max_tokens": max_tokens,
                         "temperature": 0}).encode("utf-8")
    depart = time.time()
    code, corps, _ = lire(f"{base}/chat/completions", cle, charge, timeout=TIMEOUT)
    ecoule = round(time.time() - depart, 2)
    if code != 200:
        return "", ecoule, f"HTTP {code}"
    try:
        message_recu = (json.loads(corps).get("choices") or [{}])[0].get("message") or {}
        return (message_recu.get("content") or "").strip(), ecoule, ""
    except ValueError:
        return "", ecoule, "reponse illisible"


def _json_dans(texte: str) -> dict | None:
    """Tolere un JSON encadre de texte, mais SIGNALE que la forme etait sale."""
    try:
        return json.loads(texte)
    except ValueError:
        pass
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut >= 0 and fin > debut:
        try:
            return json.loads(texte[debut:fin + 1])
        except ValueError:
            return None
    return None


def epreuve_verdict(base: str, cle: str, modele: str) -> dict:
    """REVIEWER : rendre un verdict structure, exploitable sans post-traitement."""
    texte, secondes, motif = _completer(base, cle, modele,
        'Analyse ce code : `def f(x): return eval(x)`. '
        'Reponds UNIQUEMENT par un objet JSON, sans phrase autour, '
        'de la forme {"verdict": "ok"|"risque", "raison": "<20 mots"}.')
    if motif:
        return {"reussi": False, "motif": motif, "secondes": secondes}
    brut = _json_dans(texte)
    if brut is None:
        return {"reussi": False, "motif": f"pas de JSON : {texte[:60]!r}", "secondes": secondes}
    propre = texte.startswith("{")
    if "verdict" not in brut or "raison" not in brut:
        return {"reussi": False, "motif": f"champs manquants : {list(brut)[:4]}",
                "secondes": secondes}
    return {"reussi": True, "propre": propre, "verdict": str(brut.get("verdict"))[:20],
            "secondes": secondes}


def epreuve_etiquette(base: str, cle: str, modele: str) -> dict:
    """ROUTER / SENTINEL : choisir dans un ensemble ferme, sans commentaire."""
    texte, secondes, motif = _completer(base, cle, modele,
        "Classe ce rapport dans UNE categorie parmi : "
        + ", ".join(ETIQUETTES)
        + ". Rapport : « la fonction lit une variable d'environnement en clair ». "
          "Reponds par le seul mot de la categorie, rien d'autre.",
        max_tokens=16)
    if motif:
        return {"reussi": False, "motif": motif, "secondes": secondes}
    # Normaliser les accents : le modele qui repond « securité » a RAISON, c'est
    # la reference qui etait ecrite sans accent. Comparer des formes differentes
    # faisait echouer une reponse juste (mesure 2026-08-18).
    mot = _sans_accents(texte.lower().strip(" .\n\"'`"))
    exact = mot in ETIQUETTES
    contient = any(e in mot for e in ETIQUETTES)
    if not contient:
        return {"reussi": False, "motif": f"hors ensemble : {texte[:40]!r}", "secondes": secondes}
    return {"reussi": True, "exact": exact, "reponse": mot[:24], "secondes": secondes}


def epreuve_plan(base: str, cle: str, modele: str) -> dict:
    """PLANNER : decomposer en etapes exploitables par une boucle d'agent."""
    texte, secondes, motif = _completer(base, cle, modele,
        'Decompose en 3 etapes la tache « ajouter un test de non-regression a un '
        'module Python ». Reponds UNIQUEMENT par un JSON '
        '{"etapes": ["...", "...", "..."]}, sans phrase autour.')
    if motif:
        return {"reussi": False, "motif": motif, "secondes": secondes}
    brut = _json_dans(texte)
    if brut is None or not isinstance(brut.get("etapes"), list):
        return {"reussi": False, "motif": f"pas de plan exploitable : {texte[:60]!r}",
                "secondes": secondes}
    etapes = [e for e in brut["etapes"] if isinstance(e, str) and e.strip()]
    if len(etapes) < 3:
        return {"reussi": False, "motif": f"{len(etapes)} etape(s) au lieu de 3",
                "secondes": secondes}
    return {"reussi": True, "etapes": len(etapes), "secondes": secondes}


def roles_tenus(resultats: dict, fiche_slot: dict) -> list[str]:
    """Les roles que ces MESURES autorisent — aucun n'est accorde par defaut."""
    roles = []
    if resultats["verdict"]["reussi"]:
        roles.append("REVIEWER")
    if resultats["plan"]["reussi"]:
        roles.append("PLANNER")
    if resultats["etiquette"].get("exact"):
        roles.append("ROUTER")
        if resultats["etiquette"]["secondes"] <= 2.0:
            roles += ["SENTINEL", "MONITOR"]
    if fiche_slot.get("outils") is True:
        roles.append("EXECUTOR")
    if int(fiche_slot.get("contexte") or 0) >= 100_000:
        roles.append("SUMMARIZER")
    return roles


def main() -> int:
    from nokido_agent.app.forge_secrets import get_secret

    try:
        from nokido_agent.app.forge_llm_router import PROVIDERS
    except Exception:  # noqa: BLE001 - routeur indisponible
        PROVIDERS = {}

    rapport = []
    for etiquette, env_key, base in SURFACES:
        cle = (get_secret(env_key) or "") if env_key else ""
        _code, modeles, _ = catalogue(base, cle)
        if not modeles:
            print(f"\n=== {etiquette} — catalogue muet, NON MESURE")
            continue
        print(f"\n=== {etiquette}")
        for meta in plus_petits(modeles, PAR_FOURNISSEUR):
            modele = str(meta.get("id"))
            resultats = {
                "verdict": epreuve_verdict(base, cle, modele),
                "etiquette": epreuve_etiquette(base, cle, modele),
                "plan": epreuve_plan(base, cle, modele),
            }
            # Les capacites deja mesurees vivent dans la table du routeur : on
            # ne les remesure pas, on les LIT — pour CE modele precisement.
            fiche_slot = fiche_du_modele(PROVIDERS, etiquette, modele)
            fiche_modele = dict(fiche_slot)
            fiche_modele["contexte"] = meta.get("context_length") or fiche_slot.get("contexte") or 0
            roles = roles_tenus(resultats, fiche_modele)
            marques = "".join("V" if resultats[c]["reussi"] else "-"
                              for c in ("verdict", "etiquette", "plan"))
            print(f"  {modele[:38]:40} [{marques}] {', '.join(roles) or 'AUCUN role tenu'}")
            for nom_epreuve in ("verdict", "etiquette", "plan"):
                r = resultats[nom_epreuve]
                if not r["reussi"]:
                    print(f"        {nom_epreuve:10} echoue — {r.get('motif', '')[:70]}")
            rapport.append({"fournisseur": etiquette, "modele": modele,
                            "roles": roles, "epreuves": resultats})

    print("\n--- qui peut tenir quoi ---")
    par_role: dict[str, list[str]] = {}
    for x in rapport:
        for role in x["roles"]:
            par_role.setdefault(role, []).append(f"{x['fournisseur']}:{x['modele'][:26]}")
    for role in ("PLANNER", "EXECUTOR", "REVIEWER", "ROUTER", "SUMMARIZER",
                 "SENTINEL", "MONITOR"):
        tenants = par_role.get(role) or []
        etat = ", ".join(tenants) if tenants else "AUCUN endpoint mesure ne le tient"
        print(f"  {role:11} {etat}")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"rapport": rapport}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"\ndetail : {SORTIE.relative_to(ROOT)}")
    except OSError as exc:
        print(f"(rapport non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
