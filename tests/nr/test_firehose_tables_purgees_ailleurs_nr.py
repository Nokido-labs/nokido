"""NR : une table dite « purgee ailleurs » l'est vraiment, et le garde firehose ne la signale plus.

5/11 : le garde signalait a chaque commit quatre tables de forge_critical_events comme croissance illimitee, parce qu'il ne
cherche que leur nom dans forge_log_retention.py. Mesure : 2,02 Mo, evenements traites de 7,0 j au plus, flaps du seul jour
courant. Les purges existent ailleurs. La declaration n'a de valeur que si l'appel qu'elle cite existe : sinon elle ne
ferait que faire taire le garde.
"""
import ast
import importlib.util
import pathlib

RACINE = pathlib.Path(__file__).resolve().parents[2]


def _declaration() -> dict:
    arbre = ast.parse((RACINE / "tools" / "forge_log_retention.py").read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and getattr(noeud.targets[0], "id", "") == "PURGEES_AILLEURS":
            return ast.literal_eval(noeud.value)
    raise AssertionError("PURGEES_AILLEURS absent de forge_log_retention.py")


def test_chaque_table_cite_un_appel_qui_existe():
    declaration = _declaration()
    assert {"forge_critical_events", "alertes_owner", "alertes_etat", "alertes_flaps"} <= set(declaration)
    for table, (module, appel) in declaration.items():
        assert appel in (RACINE / module).read_text(encoding="utf-8"), f"{table} : {appel} absent de {module}"


def test_le_garde_ne_signale_plus_ces_tables():
    spec = importlib.util.spec_from_file_location("firehose_nr", RACINE / "tools" / "forge_firehose_guard.py")
    garde = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(garde)
    tables = [w for w in garde.scan(["app/forge_critical_events.py"]) if "CREATE TABLE" in w]
    assert tables == []
