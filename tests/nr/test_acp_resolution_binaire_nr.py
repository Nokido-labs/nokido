# -*- coding: utf-8 -*-
"""NR — ne PAS brancher le client ACP sur un binaire qui ne parle pas ACP.

HISTOIRE COMPLETE, parce que c'est elle qui protege (2026-09-18).

`forge_acp_client --probe` rend « gemini introuvable: [WinError 2] » depuis un compte
de service, alors qu'au MEME instant `forge_task_executor._delegate_to_agy` lance un CLI
avec succes par un chemin ABSOLU (`LAFORGE_AGY_BIN`). J'en ai deduit qu'il manquait un
repli, et je l'ai ecrit.

LA DEDUCTION ETAIT FAUSSE, et c'est agy qui l'a dit quand on le lui a demande :

    agy 1.2.6 — `--experimental-acp` : **ABSENT** de son aide.
    A la place : `--continue` / `--conversation` (session persistante),
    `remote-control` (mode demon), `--input-format` / `--output-format stream-json`.

`agy.exe` (`~\\AppData\\Local\\agy\\bin\\agy.exe`) est le CLI **Antigravity** ; le
`gemini` npm officiel, lui, porte bien `--experimental-acp`. Meme modele, binaire
different. Replier sur le premier donnerait un chemin VALIDE pour un drapeau INVALIDE :
le handshake echouerait en plein vol avec un message obscur, au lieu du franc
« introuvable ». C'est strictement pire -- et c'est la definition meme de la dette de
cablage que ce depot combat : un mecanisme branche sur une capacite qui n'existe pas.

CE QUE CE NR VERROUILLE : l'echec reste LISIBLE, la resolution ne devine rien, et
personne ne re-branchera ce repli sans lire pourquoi il a ete retire.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_acp_client as CLI  # noqa: E402


@pytest.fixture(autouse=True)
def _env_propre(monkeypatch):
    for v in ("GEMINI_ACP_CMD", "CLAUDE_ACP_CMD", "CODEX_ACP_CMD", "LAFORGE_AGY_BIN"):
        monkeypatch.delenv(v, raising=False)
    # PATH volontairement aveugle : la situation exacte d'un compte de service.
    monkeypatch.setattr(CLI.shutil, "which", lambda *a, **k: None)


def test_le_binaire_agy_n_est_JAMAIS_substitue(tmp_path, monkeypatch):
    """MORSURE PRINCIPALE — le repli que j'avais ecrit ne doit pas revenir.

    Si un jour `agy` gagne un mode ACP, ce test echouera et il faudra le MESURER
    (lire son aide) avant de rouvrir le chemin -- pas le deduire d'un chemin qui existe.
    """
    faux = tmp_path / "agy.exe"
    faux.write_text("", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_AGY_BIN", str(faux))
    for agent in ("gemini", "agy", "claude", "codex"):
        cmd = CLI._resolve_cmd(agent)
        assert str(faux) not in cmd, (
            "%s serait pilote par agy.exe, qui n'a PAS --experimental-acp : "
            "le handshake echouerait en plein vol au lieu de dire introuvable. %s"
            % (agent, cmd))


def test_l_echec_reste_LISIBLE(monkeypatch):
    """Sans binaire trouvable, on rend la commande NUE : l'erreur dira « introuvable ».

    Le drapeau attendu est celui du CLI COURANT (`--acp`) : ce test verrouillait
    `--experimental-acp` et il a legitimement echoue quand la migration a eu lieu.
    On le rattache a la constante du module plutot qu'a un littéral, pour qu'il suive
    la source au lieu de la contredire.
    """
    assert CLI._resolve_cmd("gemini") == ["gemini", CLI.ACP_FLAG]


def test_l_override_explicite_reste_le_seul_moyen_de_forcer(monkeypatch):
    """Un operateur peut TOUJOURS designer le binaire — mais il le fait EXPLICITEMENT.

    C'est la difference entre une deduction (interdite ici) et une decision (permise).
    """
    monkeypatch.setenv("GEMINI_ACP_CMD", json.dumps([r"C:\un\chemin\gemini.cmd",
                                                     "--experimental-acp"]))
    assert CLI._resolve_cmd("gemini") == [r"C:\un\chemin\gemini.cmd", "--experimental-acp"]


def test_le_PATH_reste_la_voie_normale(monkeypatch):
    """Quand le binaire est reellement joignable, rien de tout ceci n'intervient."""
    monkeypatch.setattr(CLI.shutil, "which",
                        lambda n: r"C:\npm\gemini.cmd" if "gemini" in n else None)
    assert CLI._resolve_cmd("gemini")[0] == r"C:\npm\gemini.cmd"


def test_chaque_agent_garde_SA_commande(monkeypatch):
    """Un agent ne doit jamais heriter de la commande d'un autre."""
    vus = {a: CLI._resolve_cmd(a)[0] for a in ("gemini", "claude", "codex")}
    assert len(set(vus.values())) == 3, vus
