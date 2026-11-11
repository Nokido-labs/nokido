#!/usr/bin/env python3
"""tools/forge_parite_ring.py — Audit de parite Ring 1 entre agents Nokido.

Regles et contraintes :
1. Agregat par liste blanche : statut global VRAI seulement si TOUS les champs sont VRAI.
   Un FAUX ou un ILLISIBLE l'interdit.
2. Un chemin sous C:\\Users\\Default (HOME du compte de job), ou tout chemin illisible
   a ton compte : ILLISIBLE, jamais FAUX. N'utilise pas expanduser pour conclure.
3. Une dimension du profil jamais lue : ILLISIBLE, pas OK. Ce lot ne lit que 2 sources
   reelles : proxy_deno/core/services.toml (executeur present) et tools/bash_guard.py
   (lecture ast, jamais d'import, passthroughs). Toutes les autres dimensions restent
   ILLISIBLE et nommees.
4. EXCEPTION_VALIDEE seulement pour AGY --sandbox (tools/forge_task_executor.py:1688).
   Toutes les autres deviennent A_CONFIRMER_OWNER, listees en tete meme sans --detail.
   Cline --yolo est une exception separee, A_CONFIRMER_OWNER.
5. --check : rc 1 s'il existe un ecart non declare ou un ILLISIBLE sur une dimension lue ;
   la ligne de resume dit le nombre de dimensions non lues, jamais « 0 derive » seul.
"""
from __future__ import annotations

__FORGE_COLOR__ = "Immunitaire/audit"

import argparse
import ast
import json
import os
import sys
from pathlib import Path

# Constantes de statut
STATUT_VRAI = "VRAI"
STATUT_FAUX = "FAUX"
STATUT_ILLISIBLE = "ILLISIBLE"

STATUT_EXCEPTION_VALIDEE = "EXCEPTION_VALIDEE"
STATUT_A_CONFIRMER_OWNER = "A_CONFIRMER_OWNER"


def est_chemin_illisible_ou_default(p: str | Path) -> bool:
    """Verifie si un chemin est sous C:\\Users\\Default ou inaccessible/illisible."""
    s = str(p).replace("/", "\\")
    if "c:\\users\\default" in s.lower():
        return True
    try:
        path_obj = Path(p)
        if not path_obj.exists():
            return False  # n'existe pas
        # Verification d'acces en lecture
        if path_obj.is_file():
            with open(path_obj, "rb") as f:
                f.read(1)
        elif path_obj.is_dir():
            os.listdir(path_obj)
        return False
    except (PermissionError, OSError):
        return True


def analyser_services_toml(services_path: Path) -> dict:
    """Lit proxy_deno/core/services.toml et verifie la presence d'executeurs/services."""
    if est_chemin_illisible_ou_default(services_path):
        return {"statut": STATUT_ILLISIBLE, "details": "Fichier sous Default ou permission refusee"}
    if not services_path.is_file():
        return {"statut": STATUT_ILLISIBLE, "details": "services.toml introuvable"}

    try:
        content = services_path.read_text(encoding="utf-8", errors="replace")
        # Verification executeurs presents (NokidoMCP, etc.)
        if 'name = "NokidoMCP"' in content:
            return {"statut": STATUT_VRAI, "details": "NokidoMCP et executeurs trouves"}
        return {"statut": STATUT_FAUX, "details": "NokidoMCP absent de services.toml"}
    except (PermissionError, OSError) as e:
        return {"statut": STATUT_ILLISIBLE, "details": f"Erreur lecture services.toml: {e}"}


def analyser_bash_guard_ast(bash_guard_path: Path) -> dict:
    """Analyse statique AST de tools/bash_guard.py sans jamais l'importer."""
    if est_chemin_illisible_ou_default(bash_guard_path):
        return {"statut": STATUT_ILLISIBLE, "details": "Fichier sous Default ou permission refusee"}
    if not bash_guard_path.is_file():
        return {"statut": STATUT_ILLISIBLE, "details": "bash_guard.py introuvable"}

    try:
        source = bash_guard_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(bash_guard_path))
        
        # Recherche des passthroughs et de segment_ok
        has_segment_ok = False
        allowed_recovery_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "segment_ok":
                has_segment_ok = True
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "ALLOWED_RECOVERY":
                        allowed_recovery_found = True
        
        if has_segment_ok and allowed_recovery_found:
            return {"statut": STATUT_VRAI, "details": "segment_ok et ALLOWED_RECOVERY valides dans l'AST"}
        return {"statut": STATUT_FAUX, "details": "Structure attendue non trouvee dans bash_guard.py"}
    except (PermissionError, OSError) as e:
        return {"statut": STATUT_ILLISIBLE, "details": f"Erreur lecture bash_guard.py: {e}"}
    except Exception as e:
        return {"statut": STATUT_ILLISIBLE, "details": f"Erreur parse AST bash_guard.py: {e}"}


def evaluer_exceptions(exceptions_cfg: dict) -> list[dict]:
    """Evalue les exceptions selon la regle 4 :
    Seul AGY --sandbox (tools/forge_task_executor.py:1688) est EXCEPTION_VALIDEE.
    Toutes les autres deviennent A_CONFIRMER_OWNER.
    """
    res = []
    for cle, exc in exceptions_cfg.items():
        nom_agent = exc.get("agent", "")
        source = exc.get("source", "")
        motif = exc.get("motif", "")
        
        # Regle 4 : EXCEPTION_VALIDEE seulement pour AGY --sandbox
        if nom_agent.lower() in ("antigravity", "agy") and "1688" in source and "sandbox" in motif.lower():
            statut = STATUT_EXCEPTION_VALIDEE
        else:
            statut = STATUT_A_CONFIRMER_OWNER
            
        res.append({
            "cle": cle,
            "agent": nom_agent,
            "motif": motif,
            "source": source,
            "statut": statut,
        })
    return res


def auditer_parite(racine: Path, profil_path: Path) -> dict:
    """Execute l'audit de parite complet."""
    if est_chemin_illisible_ou_default(profil_path):
        return {
            "statut_global": STATUT_ILLISIBLE,
            "dimensions": {},
            "exceptions": [],
            "dimensions_non_lues": 0,
            "dimensions_lues_invalides": 1,
            "ecarts_non_declares": 0,
            "erreur": "Profil sous Default ou illisible",
        }

    try:
        with open(profil_path, "r", encoding="utf-8") as f:
            profil = json.load(f)
    except Exception as e:
        return {
            "statut_global": STATUT_ILLISIBLE,
            "dimensions": {},
            "exceptions": [],
            "dimensions_non_lues": 0,
            "dimensions_lues_invalides": 1,
            "ecarts_non_declares": 0,
            "erreur": f"Impossible de charger le profil: {e}",
        }

    dimensions_cfg = profil.get("dimensions", {})
    exceptions_cfg = profil.get("exceptions", {})

    dimensions_res = {}
    dimensions_non_lues = 0
    dimensions_lues_invalides = 0
    ecarts_non_declares = 0

    # Seules 2 sources sont reelles dans ce lot
    # 1. supervisor_service -> proxy_deno/core/services.toml
    # 2. bash_guard_ast -> tools/bash_guard.py
    for dim_nom, dim_info in dimensions_cfg.items():
        if dim_nom == "supervisor_service":
            services_file = racine / "proxy_deno" / "core" / "services.toml"
            res_dim = analyser_services_toml(services_file)
            dimensions_res[dim_nom] = res_dim
            if res_dim["statut"] == STATUT_ILLISIBLE:
                dimensions_lues_invalides += 1
            elif res_dim["statut"] == STATUT_FAUX:
                ecarts_non_declares += 1
        elif dim_nom == "bash_guard_ast":
            bash_guard_file = racine / "tools" / "bash_guard.py"
            res_dim = analyser_bash_guard_ast(bash_guard_file)
            dimensions_res[dim_nom] = res_dim
            if res_dim["statut"] == STATUT_ILLISIBLE:
                dimensions_lues_invalides += 1
            elif res_dim["statut"] == STATUT_FAUX:
                ecarts_non_declares += 1
        else:
            # Dimension non lue : ILLISIBLE, pas OK (Regle 3)
            dimensions_res[dim_nom] = {
                "statut": STATUT_ILLISIBLE,
                "details": f"Dimension non lue dans ce lot ({dim_info.get('source', '')})",
            }
            dimensions_non_lues += 1

    # Evaluation des exceptions
    exceptions_res = evaluer_exceptions(exceptions_cfg)

    # Regle 1 : Agregat par liste blanche : statut global VRAI seulement si TOUS les champs sont VRAI.
    # Un FAUX ou un ILLISIBLE l'interdit.
    tous_vrais = True
    for dim_nom, res_dim in dimensions_res.items():
        if res_dim["statut"] != STATUT_VRAI:
            tous_vrais = False
            break

    statut_global = STATUT_VRAI if tous_vrais else STATUT_FAUX

    return {
        "statut_global": statut_global,
        "dimensions": dimensions_res,
        "exceptions": exceptions_res,
        "dimensions_non_lues": dimensions_non_lues,
        "dimensions_lues_invalides": dimensions_lues_invalides,
        "ecarts_non_declares": ecarts_non_declares,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit de parite Ring 1")
    parser.add_argument("--check", action="store_true", help="Retourne rc 1 s'il existe une derive ou un illisible sur dimension lue")
    parser.add_argument("--detail", action="store_true", help="Affiche le detail de toutes les dimensions")
    parser.add_argument("--profil", default=None, help="Chemin vers profil_ring1_parite.json")
    parser.add_argument("--racine", default=None, help="Racine du depot/worktree")

    args = parser.parse_args()

    racine = Path(args.racine).resolve() if args.racine else Path(__file__).resolve().parent.parent
    profil_path = Path(args.profil).resolve() if args.profil else racine / "config" / "profil_ring1_parite.json"

    resultats = auditer_parite(racine, profil_path)

    # Regle 4 : Exceptions listees en tete meme sans --detail
    exceptions_a_confirmer = [e for e in resultats["exceptions"] if e["statut"] == STATUT_A_CONFIRMER_OWNER]
    exceptions_validees = [e for e in resultats["exceptions"] if e["statut"] == STATUT_EXCEPTION_VALIDEE]

    print("=== EXCEPTIONS RING 1 ===")
    for exc in exceptions_a_confirmer:
        print(f"  [A_CONFIRMER_OWNER] {exc['agent']} - {exc['motif']} ({exc['source']})")
    for exc in exceptions_validees:
        print(f"  [EXCEPTION_VALIDEE] {exc['agent']} - {exc['motif']} ({exc['source']})")
    print("=========================")

    if args.detail:
        print("\n=== DETAIL DIMENSIONS ===")
        for dim, res in resultats["dimensions"].items():
            print(f"  {dim}: [{res['statut']}] {res.get('details', '')}")
        print("=========================\n")

    # Regle 5 : la ligne de resume dit le nombre de dimensions non lues, jamais « 0 derive » seul.
    dims_non_lues = resultats["dimensions_non_lues"]
    ecarts = resultats["ecarts_non_declares"]
    illibles_lus = resultats["dimensions_lues_invalides"]
    global_status = resultats["statut_global"]

    resume = (
        f"Statut global: {global_status} | "
        f"Ecarts non declares: {ecarts} | "
        f"Illisibles sur dimensions lues: {illibles_lus} | "
        f"Dimensions non lues: {dims_non_lues} (nommees et reservees)"
    )
    print(resume)

    if args.check:
        # rc 1 s'il existe un ecart non declare ou un ILLISIBLE sur une dimension lue
        if ecarts > 0 or illibles_lus > 0 or global_status != STATUT_VRAI:
            return 1
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
