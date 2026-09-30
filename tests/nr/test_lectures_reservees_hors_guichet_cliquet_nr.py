"""NR cliquet -- aucune NOUVELLE lecture d'un nom reserve hors du guichet (2b-2, 2026-09-28).

Consigne owner du 2026-09-28 : « toute lecture de secret via `get_secret` ». Un nom de
`NOMS_RESERVES` lu par l'environnement, par `vault_get` direct ou par un parseur maison
de `Nokido.env` contourne le coffre reserve ET le recensement : il ne verra jamais la
fermeture de l'etape 2b-6.

Mesure du 2026-09-28 (apres les lots 2b-1, A et B1) : 63 lectures dans 49 fichiers de
`app/` et `tools/`. Ce n'est pas une cible, c'est une DETTE : le compte par fichier ne
peut que BAISSER, et un fichier absent de la base ne peut pas en ajouter. Quand une
lecture disparait, baisser la base ici dans le meme commit.

Le guichet lui-meme (`forge_secrets`) et le coffre (`forge_machine_vault`) sont exclus :
ce sont eux qui lisent. Les ecritures (`os.environ["X"] = v`) ne sont pas des lectures.
"""
import ast
import re
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture
#   (l.104)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
EXCLUS = {"app/forge_secrets.py", "app/forge_machine_vault.py"}

BASE = {
    "app/_attic/shadow_mutation_2026-04/forge_integrity.py": 1,
    "app/forge_graph_explorer.py": 1,
    "app/forge_inspector.py": 2,
    "app/forge_resource_manager.py": 2,
    "app/forge_roles.py": 2,
    "app/forge_swarm_team.py": 1,
    "app/tui_adapters/commands_adapter.py": 2,
    "tools/claude_session_start.py": 1,
    "tools/claude_session_stop.py": 1,
    "tools/forge_bell.py": 1,
    "tools/forge_bundle_primitives.py": 1,
    "tools/forge_db_encrypt_migrate.py": 2,
    "tools/forge_execute_loop.py": 1,
    "tools/forge_freetier_probe.py": 1,
    "tools/forge_goap_online_launch.py": 1,
    "tools/forge_mcp_proxy.py": 1,
    "tools/forge_openai_proxy.py": 2,
    "tools/forge_py314t_flip_canary.py": 1,
    "tools/forge_py314t_readiness.py": 1,
    "tools/forge_self_patcher.py": 1,
    "tools/forge_skill_indexer.py": 1,
    "tools/forge_swebench_lats_runner.py": 1,
    "tools/forge_task_executor.py": 1,
    "tools/forge_ui_contrat_etats.py": 1,
    "tools/forge_ui_generator.py": 1,
    "tools/forge_wheel_probe_monthly.py": 1,
    "tools/gemini_hub_relay.py": 1,
    "tools/gemini_poll_daemon.py": 1,
    "tools/multi_llm_daemon.py": 1,
    "tools/nokido.py": 1,
    # dont 2 lectures de TRANSITION (admin, superviseur) jusqu'a 2b-7 : elles sont dites
    "tools/nokido_hub.py": 6,
    "tools/nokido_stdio_bridge.py": 1,
    "tools/nokido_web_hub.py": 1,
    "tools/ollama_cloud_proxy_agent.py": 1,
    "tools/patch_ingest_repo_fail_open.py": 2,
    "tools/patch_skill_indexer_secret.py": 1,
    "tools/test_hub_mcp_handshake.py": 2,
    "tools/test_software_creator_e2e.py": 1,
    "tools/tmp_sbxcheck.py": 1,
}


def _noms_reserves() -> set:
    """Lus dans la SOURCE du guichet (AST) : aucun import, donc aucun coffre touche."""
    src = (ROOT / "app" / "forge_secrets.py").read_text(encoding="utf-8")
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "NOMS_RESERVES"
                                             for t in n.targets):
            return {e.value for e in n.value.args[0].elts}
    raise AssertionError("NOMS_RESERVES introuvable dans forge_secrets.py")


def _motifs(noms: set):
    alt = "|".join(re.escape(x) for x in sorted(noms))
    return [
        re.compile(r"(?:environ\.get|getenv)\(\s*[\"'](?:%s)[\"']" % alt),
        re.compile(r"environ\[\s*[\"'](?:%s)[\"']\s*\](?!\s*=[^=])" % alt),
        re.compile(r"vault_get\(\s*[\"'](?:%s)[\"']" % alt),
        re.compile(r"startswith\(\s*[fr]?[\"'](?:%s)=" % alt),
    ]


def _compter(src: str, motifs) -> int:
    return sum(len(m.findall(src)) for m in motifs)


def test_contre_epreuve_le_compteur_voit_les_quatre_formes_et_pas_les_ecritures():
    m = _motifs({"NOM_RESERVE_NR"})
    lectures = ('os.environ.get("NOM_RESERVE_NR")\nos.getenv(\'NOM_RESERVE_NR\')\n'
                'x = os.environ["NOM_RESERVE_NR"]\nvault_get("NOM_RESERVE_NR")\n'
                'line.startswith("NOM_RESERVE_NR=")\n')
    assert _compter(lectures, m) == 5
    assert _compter('os.environ["NOM_RESERVE_NR"] = "x"\nget_secret("NOM_RESERVE_NR")\n', m) == 0


def test_les_lectures_hors_guichet_ne_peuvent_que_baisser():
    motifs = _motifs(_noms_reserves())
    hausses, vus = [], 0
    for d in ("app", "tools"):
        for p in (ROOT / d).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            if rel in EXCLUS or "/tests/" in rel or "__pycache__" in rel:
                continue
            vus += 1
            n = _compter(p.read_text(encoding="utf-8", errors="replace"), motifs)
            if n > BASE.get(rel, 0):
                hausses.append(f"{rel}: {n} > {BASE.get(rel, 0)}")
    assert vus > 500, f"balayage anormalement court ({vus} fichiers) : le cliquet ne voit rien"
    assert not hausses, ("nouvelle lecture d'un nom reserve hors get_secret -- passer par "
                         "le guichet : " + "; ".join(hausses))
