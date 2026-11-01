"""NR 28/10 : un module charge par un test d'appui n'ECRIT aucun fichier au chargement.

Mesure : tools/patch_mcp_registry_netcfg.py et tools/hub_rt_patch.py reecrivaient app/forge_mcp_registry.py et
tools/nokido_hub.py (fichiers CRITIQUES) a chaque `import_module` de leur test d'appui -- donc a chaque CI. Seule
l'ACL du bac a sable (lecture) l'a revele, par un PermissionError. Un import qui ecrit est un test qui touche
l'etat vivant. Ce garde lit l'AST : toute ecriture (write_text, write_bytes, open en mode w/a/x/+) au niveau
module, hors fonction et hors `if __name__ == "__main__"`, est refusee.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RE_IMPORT = re.compile(r"import_module\(\s*[\"']([\w.]+)[\"']\s*\)")


def _modules_appui():
    noms = set()
    for t in (ROOT / "tests" / "nr").glob("test_appui_*_nr.py"):
        noms.update(_RE_IMPORT.findall(t.read_text(encoding="utf-8", errors="replace")))
    return sorted(noms)


def _chemin(nom):
    for base in ("tools", "app"):
        p = ROOT / base / (nom.replace(".", "/") + ".py")
        if p.is_file():
            return p
    return None


def _est_garde_main(n):
    return (isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__")


def _ecritures_au_chargement(src):
    """Lignes des ecritures executees a l'import (corps de module, hors def/class/garde __main__)."""
    fautes = []

    def visiter(noeuds):
        for n in noeuds:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) or _est_garde_main(n):
                continue
            for c in ast.walk(n):
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    break
                if not isinstance(c, ast.Call):
                    continue
                f = c.func
                nom = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                if nom in ("write_text", "write_bytes"):
                    fautes.append(c.lineno)
                elif nom == "open":
                    modes = [a.value for a in c.args[1:2] if isinstance(a, ast.Constant)]
                    modes += [k.value.value for k in c.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                    if any(isinstance(m, str) and re.search(r"[wax+]", m) for m in modes):
                        fautes.append(c.lineno)
    visiter(ast.parse(src).body)
    return fautes


def test_le_garde_voit_une_ecriture_au_chargement():
    assert _ecritures_au_chargement("from pathlib import Path\nPath('x').write_text('y')\n") == [2]
    assert _ecritures_au_chargement("def main():\n    open('x', 'w')\nif __name__ == '__main__':\n    main()\n") == []


# CLIQUET (28/10, mesure : 13 fautifs a la pose du garde). Un fautif CONNU est toleré le temps de sa reparation ;
# un NOUVEAU fait echouer ; un fautif repare DOIT sortir de la liste (sinon le cliquet se desserre en silence).
# 28/10 soir : 8 repares par CLAUDE_HEADLESS (c6aefb725) et retires ; restent 5.
# 28/10 nuit : 4 de plus repares (93a6153bb). app/forge_tool_forger.py RESTE fautif (l.35 : cree
# forge_tools_dynamic/__init__.py a l'import si absent -- idempotent, mais une ecriture) ; la livraison l'avait retire
# SANS le reparer, le cliquet l'a vu. Reparation attendue : creation paresseuse dans les fonctions qui l'utilisent.
# forge_tool_forger repare dans la foulee (creation paresseuse, _assurer_paquet) : la liste est VIDE, le cliquet strict.
_FAUTIFS_CONNUS = frozenset()
# Reparés le 28/10 : ils reecrivaient un fichier CRITIQUE a l'import. Ne doivent jamais revenir.
_REPARES = ("tools/patch_mcp_registry_netcfg.py", "tools/hub_rt_patch.py")


def _fautifs():
    out = {}
    for nom in _modules_appui():
        p = _chemin(nom)
        if p is None:
            continue
        lignes = _ecritures_au_chargement(p.read_text(encoding="utf-8", errors="replace"))
        if lignes:
            out[p.relative_to(ROOT).as_posix()] = lignes
    return out


def test_aucun_nouveau_module_d_appui_n_ecrit_a_l_import():
    f = _fautifs()
    nouveaux = {k: v for k, v in f.items() if k not in _FAUTIFS_CONNUS}
    assert not nouveaux, "ecriture de fichier a l'IMPORT (test d'appui = etat vivant touche) : %s" % nouveaux
    assert not [r for r in _REPARES if r in f], "un script repare ecrit de nouveau a l'import"


def test_le_cliquet_se_resserre():
    """Un fautif connu repare doit etre retire de _FAUTIFS_CONNUS."""
    assert not sorted(_FAUTIFS_CONNUS - set(_fautifs())), "fautif(s) repare(s) a retirer de _FAUTIFS_CONNUS"
