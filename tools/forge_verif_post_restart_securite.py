"""Verification des corrections de securite du 2026-09-12, apres redemarrage du hub.

__FORGE_COLOR__ = "immunitaire/guard : verification post-redemarrage des gardes"

POURQUOI CET OUTIL EXISTE — une mesure, pas une precaution de style.

Le 2026-09-12, quatre entrees ont ete ajoutees a `CRITICAL_FILES`. Immediatement
apres, deux ecritures IDENTIQUES en forme ont ete tentees sans derogation, a la
meme seconde, par le meme compte :

    app/forge_rbac.py      (entree ANCIENNE)  -> REFUSE
    app/forge_mcp_rbac.py  (entree AJOUTEE)   -> PASSE

Le garde etait donc ARME, et AVEUGLE aux entrees neuves. Cause : `governed_write`
s'execute IN-PROCESS du hub et importe `forge_mcp_security` depuis `sys.modules`,
ou il est charge depuis le demarrage. Une correction de source n'est pas une
correction d'effet tant que le processus qui la porte n'a pas ete relance.

Ce que cet outil separe, et ne melange jamais :

  PREDIT  — ce qu'un processus NEUF constate en important la source. C'est ce
            que le hub verra APRES son redemarrage. Ce n'est pas un effet.
  OBSERVE — ce qui ne peut se constater que par un geste reel contre le hub
            VIVANT. Cet outil ne peut pas l'emettre (il n'est pas client MCP) :
            il IMPRIME la sequence exacte a jouer, et ce qu'il faut voir.

Un rapport qui melangerait les deux rendrait « vert » un garde qui ne mord pas.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT.parent), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --- PREDIT : lu depuis une source fraiche -----------------------------------

#: (chemin, pourquoi il porte une autorite) — mesure du 2026-09-12.
AUTORITES = (
    ("app/forge_mcp_rbac.py", "decision d'autorisation par tool (check_tool_capability)"),
    ("app/forge_opsec.py", "etat de l'off-switch humain"),
    ("app/forge_corrigibility.py", "garde qui consulte l'off-switch au dispatch"),
    ("tools/forge_governed_edit.py", "ecrivain qui applique CRITICAL_FILES"),
)


def predit() -> dict:
    """Ce qu'un processus neuf constate. NE PROUVE AUCUN EFFET."""
    r: dict = {"nature": "PREDIT (processus neuf, pas le hub vivant)"}

    try:
        from nokido_agent.app import forge_mcp_security as S
        r["critical_files"] = {rel: bool(S._is_critical(rel)) for rel, _ in AUTORITES}
        r["critical_files_total"] = len(S.CRITICAL_FILES)
    except Exception as e:  # noqa: BLE001
        r["critical_files"] = "ILLISIBLE %s: %s" % (type(e).__name__, str(e)[:120])

    try:
        from nokido_agent.app import forge_opsec as O
        etat, motif = O.human_lock_state()
        r["off_switch"] = {"etat": etat, "motif": motif,
                           "trois_etats_exposes": hasattr(O, "human_lock_state")}
    except Exception as e:  # noqa: BLE001
        r["off_switch"] = "ILLISIBLE %s: %s" % (type(e).__name__, str(e)[:120])

    try:
        from nokido_agent.app import forge_ps_sandbox as P
        r["ps_sandbox_modes"] = {"modes_declares": list(P.MODES_AUTORISES),
                                 "mode_inconnu_refuse": not P.mode_valide("zzz")}
    except Exception as e:  # noqa: BLE001
        r["ps_sandbox_modes"] = "ILLISIBLE %s: %s" % (type(e).__name__, str(e)[:120])

    try:
        from nokido_agent.tools import forge_dev_mode as D
        arme, detail = D.is_armed()
        r["attestation_dev"] = {"armee": bool(arme), "detail": str(detail)[:160]}
    except Exception as e:  # noqa: BLE001
        r["attestation_dev"] = "ILLISIBLE %s: %s" % (type(e).__name__, str(e)[:120])

    return r


# --- OBSERVE : ne peut se constater que contre le hub vivant ------------------

GESTES = (
    {
        "geste": "governed_edit path=app/forge_rbac.py SANS allow_critical "
                 "(bloc SEARCH/REPLACE identique)",
        "attendu": "REFUS 'GOVERNED EDIT BLOCKED (critical)'",
        "role": "CONTROLE POSITIF — deja vrai avant redemarrage. S'il passe, "
                "le garde entier est tombe, et rien d'autre dans cette liste "
                "n'a de sens.",
    },
    {
        "geste": "governed_edit path=app/forge_mcp_rbac.py SANS allow_critical "
                 "(bloc SEARCH/REPLACE identique)",
        "attendu": "REFUS 'GOVERNED EDIT BLOCKED (critical)'",
        "role": "LE TEST. Mesure du 2026-09-12 AVANT redemarrage : il PASSAIT. "
                "S'il passe encore apres redemarrage, la cause n'etait PAS le "
                "cache de modules et il faut rouvrir l'enquete.",
    },
    {
        "geste": "run action=shell sandbox=ps_clm code=\"echo x\" avec "
                 "l'attestation DEV NON armee",
        "attendu": "REFUS nommant forge_dev_mode",
        "role": "transfert de code vers un executeur SYSTEM",
    },
    {
        "geste": "run action=shell sandbox=ps_clm code=\"echo x\" avec "
                 "l'attestation DEV armee par l'owner",
        "attendu": "EXECUTION normale",
        "role": "CONTROLE POSITIF — sans lui, un garde qui refuse TOUT "
                "passerait le test precedent sans rien prouver.",
    },
)


#: OBSERVATIONS REELLES contre le hub redemarre. Un geste sans date ni
#: resultat n'est pas une observation : c'est une intention.
#: Redemarrage constate a 22:38:20 le 2026-09-12 (pid 12940 mort, nssm.exe
#: parent de deno.exe neufs — la signature documentee du restart reussi).
OBSERVATIONS = (
    {
        "geste": "governed_edit app/forge_mcp_rbac.py SANS allow_critical",
        "avant_restart": "PASSE (mesure 22:0x)",
        "apres_restart": "REFUSE — 'GOVERNED EDIT BLOCKED (critical)'",
        "quand": "2026-09-12 22:40",
        "etat": "RUNTIME_OBSERVED",
        "conclusion": "la cause etait bien le cache de modules du hub, et non "
                      "un defaut de la liste. L'hypothese est FERMEE.",
    },
    {
        "geste": "run action=shell sandbox=ps_clm, attestation DEV NON armee",
        "avant_restart": "non mesure sous cette forme",
        "apres_restart": "REFUSE — 'SECURITY: sandbox=ps_clm exige l'attestation "
                         "DEV (forge_dev_mode)'",
        "quand": "2026-09-12 22:40",
        "etat": "RUNTIME_OBSERVED",
        "conclusion": "PS_CLM_DEV_BOUND : cas NEGATIF observe. Le cas POSITIF "
                      "(DEV attestee -> execution) reste NON OBSERVE : le jeton "
                      "est ACL SYSTEM+Administrators, le client ne peut pas "
                      "l'armer. BLOCKED_BY_ENVIRONMENT.",
    },
    {
        "geste": "run action=shell sandbox=local (usage legitime)",
        "avant_restart": "fonctionnait",
        "apres_restart": "EXECUTE normalement",
        "quand": "2026-09-12 22:40",
        "etat": "RUNTIME_OBSERVED",
        "conclusion": "CONTROLE POSITIF : les gardes ne refusent pas tout. Sans "
                      "lui, les deux refus ci-dessus ne prouveraient rien.",
    },
)

#: SECOND REDEMARRAGE, constate a 22:57:38 le 2026-09-12 (nssm.exe parent de
#: deno.exe neufs, posterieur au premier de 22:38:20). Il porte les corrections
#: faites APRES la premiere vague : sentinelle is_active, declaration des 14
#: outils natifs, desarmement du defaut permissif cote natifs.
OBSERVATIONS_2E_VAGUE = (
    {
        "geste": "governed_edit app/forge_opsec.py SANS allow_critical",
        "attendu": "REFUS (ajoute a CRITICAL_FILES le 2026-09-12)",
        "observe": "REFUSE — 'GOVERNED EDIT BLOCKED (critical)'",
        "quand": "2026-09-12 23:0x",
        "etat": "RUNTIME_OBSERVED",
    },
    {
        "geste": "tool_scope action=status (outil NATIF declare ce soir)",
        "attendu": "fonctionne — la declaration ne devait rien changer",
        "observe": "OK, {'intent_code': 'SCOPE_STATUS', 'scoped': False}",
        "quand": "2026-09-12 23:0x",
        "etat": "RUNTIME_OBSERVED (non-regression)",
    },
    {
        "geste": "forge_list_dynamic_tools (chemin ROUTE _handle_forge_dynamic)",
        "attendu": "fonctionne — desarmer le defaut permissif ne devait PAS "
                   "couper les routes",
        "observe": "OK, 3 outils forges listes",
        "quand": "2026-09-12 23:0x",
        "etat": "RUNTIME_OBSERVED (le controle qui comptait le plus)",
    },
)

#: TROISIEME REDEMARRAGE, constate a 23:41:02 le 2026-09-12. Il porte le
#: plancher de ring de ps_clm et le transport d'autorite des delegations.
OBSERVATIONS_3E_VAGUE = (
    {
        "geste": "lecture du schema de sandbox/tasks.db AVANT puis APRES une "
                 "sollicitation LECTURE SEULE du hub (task action=status)",
        "attendu": "la colonne from_ring apparait : la migration s'applique "
                   "dans le processus vivant",
        "observe": "AVANT : 14 colonnes, from_ring ABSENTE. APRES : 15 "
                   "colonnes, from_ring PRESENTE. 49 lignes heritees a NULL.",
        "quand": "2026-09-12 23:42",
        "etat": "RUNTIME_OBSERVED",
        "portee": "PREMIERE observation POSITIVE d'un correctif de la soiree — "
                  "les precedentes etaient des refus ou des non-regressions. "
                  "Les 49 NULL sont exactement le cas ou `int(x or 0)` "
                  "donnerait MASTER ; `_ring_delegant` les ramene a 4.",
    },
    {
        "geste": "run sandbox=ps_clm depuis un client de ring 1",
        "attendu": "refus par l'ATTESTATION, pas par le RING",
        "observe": "'SECURITY: sandbox=ps_clm exige l'attestation DEV' — le "
                   "plancher a laisse passer (1 <= 1), l'attestation a arrete",
        "quand": "2026-09-12 23:42",
        "etat": "RUNTIME_OBSERVED",
        "portee": "controle POSITIF du plancher : s'il avait ete pose trop "
                  "haut, le refus aurait nomme le ring et le canal documente "
                  "de lecture du profil owner serait coupe",
    },
    {
        "geste": "governed_edit app/forge_corrigibility.py sans allow_critical ; "
                 "forge_list_dynamic_tools ; tool_scope",
        "attendu": "refus critique ; route intacte ; natif declare intact",
        "observe": "REFUSE ; 3 outils forges listes ; SCOPE_STATUS rendu",
        "quand": "2026-09-12 23:42",
        "etat": "RUNTIME_OBSERVED (non-regression a travers trois redemarrages)",
    },
)

#: CE QUI N'A PAS PU ETRE OBSERVE DE LA 2E VAGUE, et pourquoi.
#: Le refus d'un outil natif NON declare n'est pas observable : les 81 handlers
#: sont desormais declares, donc le cas ne se presente plus en production. Il
#: est couvert au niveau du dispatch par tests/test_outil_natif_non_declare.py,
#: ce qui n'est pas une preuve d'effet runtime. Le dire plutot que compter la
#: non-regression pour une demonstration du correctif.

#: Ce que le runtime ne peut PAS demontrer sans geste interdit ou action owner.
NON_OBSERVABLE_SANS_RISQUE = (
    {"propriete": "capteur d'off-switch ILLISIBLE -> refus des mutants",
     "pourquoi": "exige de rendre RAG/embeddings.db illisible — geste destructif",
     "couverture": "unitaire (tmp_path) + NR de source"},
    {"propriete": "RBAC indisponible -> refus fail-closed",
     "pourquoi": "exige de casser l'import de forge_mcp_rbac dans le hub vivant",
     "couverture": "NR de source"},
    {"propriete": "mode inconnu -> refus",
     "pourquoi": "le parametre `mode` n'est atteignable que par ps_clm, "
                 "lui-meme refuse sans attestation DEV",
     "couverture": "unitaire (mode_valide) + NR de source"},
    {"propriete": "DEV attestee -> ps_clm autorise",
     "pourquoi": "le jeton est ACL SYSTEM+Administrators : action OWNER",
     "couverture": "AUCUNE — trou assume, a lever au prochain armement DEV"},
)


def a_observer() -> list:
    return list(GESTES)


def observations() -> tuple:
    """Ce qui a ETE observe, avec sa date. Ne pas confondre avec `a_observer`."""
    return OBSERVATIONS


def main() -> int:
    rapport = {
        "chantier": "verification post-redemarrage des gardes du 2026-09-12",
        "avertissement": (
            "PREDIT n'est PAS OBSERVE. Un processus neuf lit la source corrigee ; "
            "le hub vivant execute le code charge a son demarrage. Les deux ont "
            "diverge le 2026-09-12, et la divergence etait invisible en lecture."),
        "quatre_etats": {
            "SOURCE_CORRECT": "oui — corrections ecrites et relues",
            "TESTS_GREEN": "oui — 145 NR verts",
            "RUNTIME_ACTIVE": "oui — hub redemarre le 2026-09-12 a 22:38:20",
            "RUNTIME_OBSERVED": "PARTIEL — voir `observations` et "
                                "`non_observable_sans_risque`",
        },
        "predit": predit(),
        "observations": list(OBSERVATIONS),
        "observations_2e_vague": list(OBSERVATIONS_2E_VAGUE),
        "observations_3e_vague": list(OBSERVATIONS_3E_VAGUE),
        "non_observable_sans_risque": list(NON_OBSERVABLE_SANS_RISQUE),
        "a_observer_contre_le_hub_vivant": a_observer(),
    }
    print(json.dumps(rapport, indent=1, ensure_ascii=False, default=str))

    manques = [rel for rel, ok in
               (rapport["predit"].get("critical_files") or {}).items() if not ok] \
        if isinstance(rapport["predit"].get("critical_files"), dict) else ["ILLISIBLE"]
    if manques:
        print("\nPREDIT ROUGE — hors CRITICAL_FILES : %s" % (manques,), file=sys.stderr)
        return 1
    # La ligne de sortie se DERIVE des observations : figee, elle annoncait
    # encore « aucun geste joue » apres trois observations reelles — un rapport
    # perime ment toujours dans le sens rassurant (defaut corrige le 2026-09-12).
    observes = (len(OBSERVATIONS) + len(OBSERVATIONS_2E_VAGUE)
                + len(OBSERVATIONS_3E_VAGUE))
    restants = len(NON_OBSERVABLE_SANS_RISQUE)
    print("\nPREDIT vert. RUNTIME_OBSERVED : %d geste(s) joue(s) contre le hub "
          "redemarre. %d propriete(s) restent NON OBSERVABLES sans geste "
          "interdit ou action owner — elles ne sont couvertes qu'au niveau "
          "unitaire/source, ce qui n'est PAS une preuve d'effet."
          % (observes, restants), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
