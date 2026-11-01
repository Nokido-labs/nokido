"""Juges deterministes du banc d'amelioration (tools/forge_banc_amelioration.py)."""
import importlib.util
import sys
from pathlib import Path


def charger_module(racine, nom: str, chemin_rel: str):
    """Module `chemin_rel` de l'arbre `racine`, charge PAR CHEMIN sous le nom `nom` -- jamais le module deja importe
    d'un autre arbre (un banc juge le worktree qu'on lui donne). Source unique des juges (cliquet clones 31/10 :
    banc_juge_ancrage et banc_redaction_dlp portaient chacun sa copie)."""
    racine = Path(racine)
    for p in (racine / "app", racine / "tools", racine):
        sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location(nom, racine / chemin_rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod
