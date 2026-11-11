# -*- coding: utf-8 -*-
"""NR — Action `formes` du hub, extraction AST sans import de hook, schéma réel (v3).

Contrat :
1. `formes` est présent dans l'action enum du schéma réel de `hub` retourné par get_tool_list().
2. `build_formes_liste()` et `handle_formes` n'importent aucun script de hook dans sys.modules
   (en particulier `bash_guard`, `hook_capability_gate`, `hook_search_guard` ne sont pas importés, stdin non lu).
3. Toutes les règles de `REGLES` dans `hook_capability_gate.py` sont soit servies dans
   `regles_capability_gate`, soit répertoriées dans `ecartees` avec leur raison (len(REGLES) == servies + ecartees).
4. Un garde illisible ou absent produit une entrée explicite dans `gardes` avec état 'ILLISIBLE'
   (aucune valeur par défaut / secours codée en dur).
5. Invoqué depuis `handle_hub` ou le registry, `formes` rend du JSON valide avec ok=True.
"""

import ast
import json
import sys
from pathlib import Path
import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_mcp_registry import ToolRegistry
import forge_formes as ff

pytestmark = pytest.mark.timeout(30)


def test_schema_mcp_contient_action_formes():
    """Prouve que `formes` est dans l'action enum du schema reel de `hub`."""
    reg = ToolRegistry(root_dir=RACINE)
    tools = reg.get_tool_list(ring=0, agent="TEST")
    hub_tool = next((t for t in tools if t.get("name") == "hub"), None)
    assert hub_tool is not None, "L'outil 'hub' doit être présent dans get_tool_list()"
    actions = hub_tool.get("inputSchema", {}).get("properties", {}).get("action", {}).get("enum", [])
    assert "formes" in actions, f"'formes' doit figurer dans l'enum de l'action de 'hub' (obtenu: {actions})"


def test_aucun_import_de_script_hook_dans_sys_modules():
    """Prouve que construire la liste n'importe AUCUN script de hook."""
    # S'assurer que les modules de hook ne sont pas pré-importés
    for hook_mod in ("bash_guard", "hook_capability_gate", "hook_search_guard",
                     "tools.bash_guard", "tools.hook_capability_gate", "tools.hook_search_guard"):
        sys.modules.pop(hook_mod, None)

    res_raw = ff.build_formes_liste()
    data = json.loads(res_raw)
    assert data.get("ok") is True

    # Vérifier qu'aucun hook n'a été importé
    for hook_mod in ("bash_guard", "hook_capability_gate", "hook_search_guard"):
        assert hook_mod not in sys.modules, f"{hook_mod} ne doit JAMAIS être importé dans sys.modules"


def test_regles_exhaustives_servies_plus_ecartees():
    """Toute règle de REGLES doit être servie ou comptée dans ecartees avec sa raison."""
    cap_path = RACINE / "tools" / "hook_capability_gate.py"
    assert cap_path.exists(), "tools/hook_capability_gate.py doit exister"

    # Lecture AST indépendante pour comparer la taille exacte
    source = cap_path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    regles_node = None
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            target_id = None
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == "REGLES":
                        target_id = t.id
                        break
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "REGLES":
                target_id = n.target.id
            if target_id == "REGLES":
                regles_node = n.value
                break

    assert regles_node is not None, "La constante REGLES doit exister dans hook_capability_gate.py"
    regles_ast = ast.literal_eval(regles_node)
    nb_total = len(regles_ast)

    res_raw = ff.build_formes_liste()
    data = json.loads(res_raw)

    servies = len(data.get("regles_capability_gate", []))
    ecartees = len(data.get("ecartees", []))

    assert nb_total == servies + ecartees, (
        f"len(REGLES) ({nb_total}) doit être exactement égal à servies ({servies}) + écartées ({ecartees})"
    )


def test_garde_manquant_ou_illisible_produit_etat_illisible(tmp_path, monkeypatch):
    """Un garde illisible ou absent produit une entrée explicite ILLISIBLE nommée sans fallback en dur."""
    monkeypatch.setattr(ff, "_ROOT", tmp_path)
    res_raw = ff.build_formes_liste()
    data = json.loads(res_raw)

    gardes = data.get("gardes", {})
    assert "bash_guard_passthroughs" in gardes
    assert gardes["bash_guard_passthroughs"].get("etat") == "ILLISIBLE"
    assert "hook_search_guard_size_limit" in gardes
    assert gardes["hook_search_guard_size_limit"].get("etat") == "ILLISIBLE"


@pytest.mark.asyncio
async def test_dispatch_hub_formes():
    """Appel de l'action formes via le registre ToolRegistry."""
    reg = ToolRegistry(root_dir=RACINE)
    res_str = await reg.dispatch("hub", {"action": "formes"}, agent="agt_antigravity", ring=1)
    data = json.loads(res_str)
    assert data.get("ok") is True
    assert "formes" in data
    assert "regles_capability_gate" in data
    assert len(data["formes"]) > 0
