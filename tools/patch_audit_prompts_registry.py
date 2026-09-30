"""tools/patch_audit_prompts_registry.py -- descriptions d'outils MCP exactes (audit de prompts 2026-09-26).

Owner 26/09 : « ok applique tout ». Quatre constats de l'audit /claude-api prompt-audit sur
app/forge_mcp_registry.py (CRITICAL_FILE : governed_edit allow_critical y a COUPE le hub le 27/08 --
chemin eprouve = patcher committe + run action=trusted_script, hors du process du hub) :
  #1  `read` : la description taisait que action=file rend le fichier ENTIER (`lines`/`pattern` ne
      servent qu'a tail_logs) -- deux depassements de sortie mesures le 26/09 ;
  #7  `blackboard_read_zone` : la zone `tree_locks`, exigee par le protocole de coordination, manquait ;
  #13 `introspect` : injonctions en majuscules (sur-declenchement), contrat garde ;
  #14 `hub` : 4 actions de l'enum sur 10 non decrites.
GARDES : chaque ancien texte doit etre UNIQUE ; ast.parse AVANT ecriture ; fins de ligne PRESERVEES
(write_text sous Windows convertirait tout le fichier en CRLF) ; relecture apres ecriture.
Effet en service : au prochain redemarrage du hub (le registre est lu au demarrage).
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : patcher one-shot des descriptions d'outils MCP (audit de prompts 26/09)"

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

EDITS = [
    ("#1 read",
     '                "description": "Lire fichier ou logs (stub/full/tail)",\n'
     '                "inputSchema": {\n'
     '                    "type": "object",\n'
     '                    "properties": {\n'
     '                        "action": {"type": "string", "enum": ["file", "tail_logs", "archived"]},\n'
     '                        "path": {"type": "string"},\n'
     '                        "pattern": {"type": "string"},\n'
     '                        "lines": {"type": "integer"},\n',
     '                "description": (\n'
     '                    "Lit un fichier du depot ou la fin d\'un journal. action=file rend le fichier ENTIER : "\n'
     '                    "aucun fenetrage, `lines` et `pattern` y sont ignores -- pour une fonction, "\n'
     '                    "read_function_body ; pour la structure, get_file_skeleton ; pour une plage, Read "\n'
     '                    "offset/limit. action=tail_logs rend les `lines` dernieres lignes (defaut 100) d\'un "\n'
     '                    "journal : `path` explicite, ou `pattern` qui resout le .log de l\'organe et filtre les "\n'
     '                    "lignes contenant ce texte. action=archived rend une sortie mise de cote par le garde "\n'
     '                    "(`id` = ccr_...)."\n'
     '                ),\n'
     '                "inputSchema": {\n'
     '                    "type": "object",\n'
     '                    "properties": {\n'
     '                        "action": {"type": "string", "enum": ["file", "tail_logs", "archived"]},\n'
     '                        "path": {"type": "string", "description": "Fichier ; pour tail_logs, le .log vise."},\n'
     '                        "pattern": {"type": "string",\n'
     '                                    "description": "tail_logs seulement : resout le journal et filtre les lignes."},\n'
     '                        "lines": {"type": "integer",\n'
     '                                  "description": "tail_logs seulement : dernieres lignes (defaut 100). Ignore par action=file."},\n'),
    ("#7 blackboard_read_zone",
     'Zones: mission, architecture_rules, discovered_facts, active_bugs, scratch.",',
     'Zones: mission, architecture_rules, discovered_facts, active_bugs, scratch, tree_locks (verrous '
     'd\'edition entre agents : cle = agent, fait = fichiers reclames ; lue par governed_edit et le gate git).",'),
    ("#13 introspect",
     '                    "INTERROGER LE CORPS AVANT D\'AGIR - un seul verbe pour 21 organes "\n'
     '                    "d\'introspection. Rend, pour une question en langage naturel : les "\n'
     '                    "symboles qui EXISTENT vraiment (aucune piste inventee), ou ils sont "\n'
     '                    "definis, si l\'attribution de leurs appelants est SURE "\n'
     '                    "(RESOLU / AMBIGU / ILLISIBLE), et si Nokido a DEJA enquete sur ce "\n'
     '                    "symptome. Declare toujours ce qu\'il n\'a PAS consulte. Borne a "\n'
     '                    "5 symboles et au budget demande. A appeler AVANT grep, avant "\n'
     '                    "lecture de fichier, et avant d\'ecrire quoi que ce soit."\n',
     '                    "Point d\'entree d\'introspection (21 organes). Pour une question en langage "\n'
     '                    "naturel, rend les symboles qui existent vraiment, ou ils sont definis, si "\n'
     '                    "l\'attribution de leurs appelants est sure (RESOLU / AMBIGU / ILLISIBLE), et si "\n'
     '                    "Nokido a deja enquete sur ce symptome ; declare ce qu\'il n\'a pas consulte. "\n'
     '                    "Borne a 5 symboles et au budget demande. A utiliser avant un grep, une lecture "\n'
     '                    "ou une ecriture sur un domaine pas encore connu : c\'est le moyen le moins cher "\n'
     '                    "de ne pas reinventer un module existant."\n'),
    ("#14 hub",
     '                "description": "Etat hub: action=get_mode|set_mode|poll|notify|list_providers|search_recent. '
     'notify: to=claude|gemini|cline|daemon (explicite) + message.",\n',
     '                "description": (\n'
     '                    "Etat hub: action=get_mode|set_mode|poll|notify|list_providers|search_recent|whoami|"\n'
     '                    "quota_model|quota_report|emit_telemetry. notify: to=claude|gemini|cline|daemon (explicite) "\n'
     '                    "+ message. whoami : identite et ring de l\'appelant, taches non reclamees par agent. "\n'
     '                    "quota_report : declare le % utilise (flash, flash_lite, pro, preview_pro). quota_model : "\n'
     '                    "choisit un modele selon quality=high|medium|low|ultra (apply pour l\'appliquer). "\n'
     '                    "emit_telemetry : lire le handler avant usage."\n'
     '                ),\n'),
]


def appliquer(texte: str, edits) -> str:
    """Remplace chaque ancien texte, qui doit etre present EXACTEMENT une fois (sinon ValueError, rien n'est ecrit)."""
    for label, ancien, nouveau in edits:
        n = texte.count(ancien)
        if n != 1:
            raise ValueError("%s : ancien texte present %d fois (attendu 1) -- aucune ecriture" % (label, n))
        texte = texte.replace(ancien, nouveau)
    return texte


def main() -> int:
    brut = CIBLE.read_bytes().decode("utf-8")
    crlf = "\r\n" in brut
    texte = brut.replace("\r\n", "\n")
    try:
        nouveau = appliquer(texte, EDITS)
    except ValueError as exc:
        print("REFUS :", exc, flush=True)
        return 3
    ast.parse(nouveau)  # invalide = exception AVANT toute ecriture
    CIBLE.write_bytes((nouveau.replace("\n", "\r\n") if crlf else nouveau).encode("utf-8"))
    relu = CIBLE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    ok = relu == nouveau and all(nv in relu for _l, _a, nv in EDITS)
    print("%s : %d remplacement(s), fins de ligne %s, relecture %s"
          % (CIBLE.name, len(EDITS), "CRLF" if crlf else "LF", "OK" if ok else "ECART"), flush=True)
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
