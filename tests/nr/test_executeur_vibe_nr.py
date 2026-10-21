"""NR -- executeur Mistral Vibe sur le patron Codex (owner 16/10 : « tu ne peux pas utiliser plus de cli ? »).

RED ecrit par Claude AVANT le code. Faits mesures le 16/10 : %USERPROFILE%/.local/bin/vibe.exe = paquet uv
mistral_vibe 2.24.5 ; un SECOND `vibe` (npm\\vibe.cmd) est sur le PATH -> le binaire se designe par chemin absolu.
Mode programmatique (METADATA du paquet) : --prompt, --agent accept-edits (editions auto-approuvees, pas de shell),
--workdir, --output json, bornes --max-turns / --max-price (adaptation au quota, decision owner du 16/10).
"""
import os
import sys
from pathlib import Path

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_task_executor as T  # noqa: E402


def test_les_arguments_bornent_vibe_a_son_worktree_sans_shell():
    """Contrat revu le 17/10 (mesure : 1re tache de Vibe autonome NON LIVREE, « Waiting for approval to run
    mcp_nokido.run » en boucle -- `accept-edits` approuve les editions, pas les outils MCP, et en headless personne
    n'approuve). L'intention du garde d'origine (« jamais d'approbation totale (shell) ») est GARDEE et renforcee : les
    shells ne sont plus seulement non approuves, ils sont RETIRES du jeu d'outils (--disabled-tools, en plus de
    permission = never dans la config) ; l'approbation porte alors sur les outils MCP (gouvernes par le hub) et les
    editions du worktree. Borne de temps et confiance explicite pour l'automatisation (vibe --help, 1.x)."""
    args = T._args_vibe(Path("W"))
    assert args[args.index("--agent") + 1] == "auto-approve", args
    assert args[args.index("--workdir") + 1] == "W", args
    assert args[args.index("--output") + 1] == "json", args
    assert "--max-turns" in args and "--max-price" in args and "--time-limit" in args, "lancement sans borne : %s" % args
    assert "--trust" in args, args
    retires = [args[i + 1] for i, a in enumerate(args) if a == "--disabled-tools"]
    for shell in ("bash*", "git_bash*", "powershell*"):
        assert shell in retires, "shell natif disponible : %s" % args


def test_pas_de_lancement_sans_worktree_dedie(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_VIBE_WORKDIR", str(tmp_path / "absent"))
    ok, motif = T._peut_lancer_vibe()
    assert ok is False and "worktree" in motif.lower(), motif


def test_pas_de_lancement_sans_binaire_designe(tmp_path, monkeypatch):
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_VIBE_WORKDIR", str(wt))
    monkeypatch.setenv("LAFORGE_VIBE_BIN", str(tmp_path / "pas_de_vibe.exe"))
    ok, motif = T._peut_lancer_vibe()
    assert ok is False and "vibe" in motif.lower(), motif
