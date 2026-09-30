"""Banc de mesure : l'anonymisation change-t-elle le verdict de NOS juges ?

Question posee. `karpathy/llm-council` anonymise les auteurs avant notation pour
qu'un modele « ne joue pas les favoris ». Le constat est fait sur des modeles
CLOUD. Nokido juge avec des modeles LOCAUX : rien ne garantit que l'effet se
transpose, donc on mesure avant de declarer un gain (greffe `50385c3d`).

CE BANC NE REINVENTE PAS LE CHEMIN D'APPEL. Deux campagnes ont ete perdues le
2026-08-04 (~1 h de calcul, 0 verdict exploitable) parce qu'il parlait a ollama
en HTTP brut, une requete monolithique par appel : a ~165 s de generation CPU,
tout depassait le budget. `forge_code._call_model` — celui qu'utilise la boucle
collegiale, et qui MARCHE — appelle en STREAMING avec 2 retries et backoff
exponentiel. C'est lui qu'on prend, avec `RoleOrchestrator.assign_roles(3)` qui
attribue les modeles par role exactement comme la boucle B3, et les
`ROLE_SYSTEM_PROMPTS` d'origine. Mesurer un simulateur ne mesure pas le systeme.

Protocole. K taches de correction de code, N modeles :
  1. chaque role proposant produit une proposition par tache ;
  2. chaque modele distinct classe ensuite les propositions, dans DEUX regimes :
     ANONYME (etiquettes A/B/C) et NOMINATIF (nom du modele auteur) ;
  3. on compte, par regime, la frequence a laquelle un juge met en tete une
     proposition ecrite par SON modele.

Le controle qui rend la mesure interpretable. Un juge peut preferer la premiere
position quel que soit l'auteur : sans le mesurer, tout ecart entre regimes peut
etre un artefact d'ORDRE. L'ordre est donc permute par tirage DETERMINISTE et
`pos1_en_tete` rapporte cette preference. Reference : le hasard vaut 1/N.

La notation utilise `forge_code.parse_classement`, le parseur de PRODUCTION.

Usage :
    run action=run_job script=tools/forge_council_bias_bench.py online=true
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
# ROOT en premier : `forge_code` importe `forge_agents`, qui fait
# `from app.core.settings import ...` — un sys.path limite a app/ et tools/ leve
# `ModuleNotFoundError: No module named 'app'` (mesure 2026-08-04).
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_agents import ROLE_SYSTEM_PROMPTS, AgentRole, RoleOrchestrator  # noqa: E402
from nokido_agent.app.forge_code import _call_model, parse_classement  # noqa: E402

RAM_MIN_GO = 2.0  # sous ce seuil on ARRETE au lieu de finir a tout prix

# Marge laissee libre APRES chargement du plus gros modele retenu. Le garde
# `_garde_ram` ne suffit pas : il mesure AVANT l'appel, alors que le chargement
# se produit PENDANT. Mesure 2026-08-04 : `assign_roles(3)` designe
# qwen2.5-coder:32b (19,85 Go) et deepseek-r1:14b (9,0 Go) pour ~7 Go libres —
# les charger, c'est le scenario du gel du 02/08, pas une mesure.
MARGE_CHARGEMENT_GO = 2.0

# Roles proposants de la boucle 3, dans l'ordre ou elle les utilise.
ROLES_PROPOSANTS = [AgentRole.ANALYSTE, AgentRole.DEBUGGER, AgentRole.STRATEGE]

TACHES = [
    ("moyenne",
     "def moyenne(xs):\n    return sum(xs) / len(xs)",
     "plante sur une liste vide"),
    ("dernier",
     "def dernier(xs):\n    return xs[len(xs)]",
     "index hors bornes"),
    ("compte",
     "def compte(mot, lettre):\n    n = 0\n    for c in mot:\n        if c == lettre:\n            n = 1\n    return n",
     "rend 1 au lieu du nombre d'occurrences"),
    ("pairs",
     "def pairs(xs):\n    return [x for x in xs if x % 2]",
     "rend les impairs alors que le nom promet les pairs"),
]

INCIDENTS: dict[str, int] = {}


def _noter(motif: str) -> None:
    INCIDENTS[motif] = INCIDENTS.get(motif, 0) + 1


class _CollecteurIncidents(logging.Handler):
    """`_call_model` rend "" sans dire pourquoi, mais il JOURNALISE la cause
    (HTTP non-200, timeout, erreur client). On la capte plutot que de compter
    des reponses vides indistinctes — un chemin d'erreur muet a deja coute deux
    campagnes ici."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            _noter(record.getMessage()[:90])


class RamInsuffisante(RuntimeError):
    pass


def _ram_libre_go() -> float:
    return psutil.virtual_memory().available / 1e9


def _garde_ram() -> None:
    libre = _ram_libre_go()
    if libre < RAM_MIN_GO:
        raise RamInsuffisante(
            f"RAM libre {libre:.2f} Go < {RAM_MIN_GO} Go — campagne interrompue "
            "(un banc de mesure ne vaut pas un poste gele)"
        )


def prompt_proposition(code: str, defaut: str) -> str:
    return (
        f"Cette fonction Python a un defaut : {defaut}.\n\n"
        f"```python\n{code}\n```\n\n"
        "Donne UNIQUEMENT la fonction corrigee, dans un bloc ```python. "
        "Pas d'explication."
    )


def prompt_classement(defaut: str, presentes: list[tuple[str, str]]) -> str:
    bloc = "\n\n".join(
        f"=== Reponse {lb} ===\n```python\n{txt[:900]}\n```" for lb, txt in presentes
    )
    etiquettes = ", ".join(lb for lb, _ in presentes)
    return (
        f"Defaut a corriger : {defaut}\n\n{bloc}\n\n"
        f"Classe CES {len(presentes)} reponses, de la meilleure a la pire.\n"
        f"Format OBLIGATOIRE, rien d'autre :\n"
        f"CLASSEMENT: {etiquettes}"
    )


def _tailles(tags_url: str) -> dict[str, float]:
    """{modele: Go} depuis /api/tags. Vide si illisible — et l'appelant le DIT."""
    import urllib.request

    try:
        with urllib.request.urlopen(tags_url, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        _noter(f"tailles illisibles: {type(e).__name__}")
        return {}
    return {m["name"]: m.get("size", 0) / 1e9 for m in d.get("models", [])}


async def campagne(args) -> dict:
    from app.core.settings import get_settings

    st = get_settings()
    url = st.ollama_url
    orc = RoleOrchestrator(url, st.ollama_tags_url)
    # Memes roles, meme attribution que la boucle 3 : run_benchmark=False comme
    # elle, sinon on paierait un banc de modeles avant de commencer.
    assignments = await orc.assign_roles(3, False, None)

    proposants = [(r, assignments[r]) for r in ROLES_PROPOSANTS if assignments.get(r)]
    comparateur = assignments.get(AgentRole.COMPARATEUR)
    libre = _ram_libre_go()
    plafond = max(1.0, libre - MARGE_CHARGEMENT_GO)
    tailles = _tailles(st.ollama_tags_url)

    retenus, trop_gros = [], []
    for r, m in proposants:
        taille = tailles.get(m)
        if taille is None:
            trop_gros.append({"role": r.value, "modele": m, "raison": "taille inconnue"})
        elif taille > plafond:
            trop_gros.append({"role": r.value, "modele": m,
                              "go": round(taille, 2), "plafond_go": round(plafond, 2)})
        else:
            retenus.append((r, m))
    modeles = sorted({m for _, m in retenus})

    rapport: dict = {
        "chemin": "forge_code._call_model (streaming, 2 retries) + assign_roles(3)",
        "attribution": {r.value: m for r, m in assignments.items()},
        "comparateur": comparateur,
        "ram_libre_go_depart": round(libre, 2),
        "plafond_modele_go": round(plafond, 2),
        "ecartes_trop_gros": trop_gros,
        "modeles_distincts": modeles,
    }
    if len(modeles) < 2:
        # Completer par les generatifs qui TIENNENT, plutot que d'abandonner ou
        # de charger un modele qui ferait swaper la machine.
        candidats = sorted(
            (m for m, g in tailles.items()
             if g <= plafond and not any(x in m.lower() for x in
                                         ("bge", "embed", "rerank", "nomic", "llava", "moondream"))),
            key=lambda m: -tailles[m],
        )
        for m in candidats:
            if m not in modeles:
                modeles.append(m)
                retenus.append((ROLES_PROPOSANTS[len(retenus) % len(ROLES_PROPOSANTS)], m))
            if len(modeles) >= 3:
                break
        rapport["remplacants"] = modeles
    rapport["proposants"] = [(r.value, m) for r, m in retenus]
    if len(modeles) < 2:
        rapport["verdict"] = (
            f"MESURE IMPOSSIBLE : {len(modeles)} modele distinct tenant sous "
            f"{plafond:.1f} Go. Un juge ne peut reconnaitre SA proposition que si "
            "les auteurs different."
        )
        return rapport
    proposants = retenus

    taches = TACHES[: max(1, args.taches)]

    # ── Phase 1 : propositions ────────────────────────────────────────────
    propositions: dict[str, dict[str, str]] = {t[0]: {} for t in taches}
    vides = 0
    for role, modele in proposants:  # role en boucle externe : 1 chargement/modele
        for nom_t, code, defaut in taches:
            _garde_ram()
            rep = await _call_model(
                modele, prompt_proposition(code, defaut), url,
                timeout=args.timeout,
                system_prompt=ROLE_SYSTEM_PROMPTS.get(role, ""),
            )
            if rep.strip():
                propositions[nom_t][modele] = rep.strip()
            else:
                vides += 1
    rapport["propositions_vides"] = vides
    rapport["propositions_par_tache"] = {t: len(d) for t, d in propositions.items()}

    # ── Phase 2 : notation croisee, 2 regimes ─────────────────────────────
    sys_cmp = ROLE_SYSTEM_PROMPTS.get(AgentRole.COMPARATEUR, "")
    lignes: list[dict] = []
    for juge in modeles:
        for regime in ("anonyme", "nominatif"):
            for nom_t, _code, defaut in taches:
                dispo = propositions[nom_t]
                if len(dispo) < 2:
                    continue
                auteurs = list(dispo.keys())
                rng = random.Random(f"{args.seed}|{nom_t}|{juge}|{regime}")
                rng.shuffle(auteurs)
                if regime == "anonyme":
                    labels = [chr(65 + i) for i in range(len(auteurs))]
                else:
                    labels = [a.upper().replace(":", "_").replace("-", "_") for a in auteurs]
                    if len(set(labels)) < len(labels):
                        continue
                label_to_auteur = dict(zip(labels, auteurs))
                presentes = [(lb, dispo[label_to_auteur[lb]]) for lb in labels]

                _garde_ram()
                rep = await _call_model(
                    juge, prompt_classement(defaut, presentes), url,
                    timeout=args.timeout, system_prompt=sys_cmp,
                )
                rangs = parse_classement(rep, label_to_auteur)
                if not rangs:
                    lignes.append({"regime": regime, "tache": nom_t, "juge": juge,
                                   "classement": "illisible"})
                    continue
                tete = min(rangs, key=rangs.get)
                lignes.append({
                    "regime": regime,
                    "tache": nom_t,
                    "juge": juge,
                    "complet": len(rangs) == len(auteurs),
                    "tete": tete,
                    "juge_a_propose": juge in dispo,
                    "auto_en_tete": tete == juge,
                    "pos1_en_tete": tete == label_to_auteur[labels[0]],
                })

    # ── Synthese ──────────────────────────────────────────────────────────
    synthese: dict = {}
    for regime in ("anonyme", "nominatif"):
        v = [x for x in lignes if x["regime"] == regime and x.get("tete")
             and x.get("juge_a_propose")]
        illisibles = len([x for x in lignes if x["regime"] == regime
                          and x.get("classement") == "illisible"])
        if not v:
            synthese[regime] = {"verdicts_exploitables": 0, "illisibles": illisibles}
            continue
        synthese[regime] = {
            "verdicts_exploitables": len(v),
            "illisibles": illisibles,
            "auto_en_tete": round(sum(x["auto_en_tete"] for x in v) / len(v), 3),
            "pos1_en_tete": round(sum(x["pos1_en_tete"] for x in v) / len(v), 3),
            "hasard": round(1 / len(modeles), 3),
        }

    rapport["taches"] = [t[0] for t in taches]
    rapport["synthese"] = synthese
    rapport["detail"] = lignes
    rapport["lecture"] = (
        "auto_en_tete = frequence a laquelle un juge met en tete une proposition "
        "ecrite par SON modele. Comparer les deux regimes ENTRE EUX, et chacun au "
        "hasard (1/n). pos1_en_tete proche de auto_en_tete = l'ecart tient a la "
        "POSITION, pas a la reconnaissance de l'auteur : la mesure ne conclut alors "
        "rien sur l'anonymisation. Un faible nombre de verdicts exploitables ne "
        "conclut rien non plus."
    )
    return rapport


def main() -> int:
    ap = argparse.ArgumentParser(description="Biais de juge : anonyme vs nominatif")
    ap.add_argument("--taches", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--seed", type=int, default=20260804)
    args = ap.parse_args()

    logging.getLogger().addHandler(_CollecteurIncidents())
    logging.getLogger().setLevel(logging.WARNING)

    t0 = time.time()
    try:
        rapport = asyncio.run(campagne(args))
    except RamInsuffisante as e:
        print(json.dumps({"verdict": "INTERROMPU", "raison": str(e),
                          "incidents": dict(INCIDENTS)}, ensure_ascii=False, indent=2))
        return 2
    rapport["duree_s"] = round(time.time() - t0, 1)
    rapport["ram_libre_go_fin"] = round(_ram_libre_go(), 2)
    rapport["incidents"] = dict(INCIDENTS) or "aucun"
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
