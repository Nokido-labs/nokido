# -*- coding: utf-8 -*-
"""NR — `forge_mcp_json_sync --emit-headers` sert de headersHelper sans jamais emettre le maitre.

Reglage (c) accorde par l'owner le 24/09 : le jeton du hub ne doit plus vivre en clair dans
`.mcp.json`. Doc Claude Code (mcp.md) : `headersHelper` = commande lancee a chaque connexion,
qui ecrit sur stdout un objet JSON d'en-tetes. Contrat verifie par le vrai `main()` :
  1. jeton propre present -> JSON d'en-tetes sur stdout (Authorization + noms d'agent) ;
  2. jeton propre absent  -> RIEN sur stdout, code non nul, JAMAIS de repli sur le maitre
     (AUTH-2 : le maitre ne devient pas une identite d'organe ; AUTH-4 : absence = refus) ;
  3. --verifier           -> cles et longueur seulement, jamais la valeur ;
  4. la synchronisation ne reecrit JAMAIS en clair un serveur qui a un headersHelper.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import DIRECT, pas importorskip : sur le livrable teste, un import qui echoue doit
# rougir, pas se lire comme un test passe (faux vert paye le 08/09).
import forge_mcp_json_sync as fms  # noqa: E402

JETON = "ab" * 32


def _coffre(monkeypatch, valeurs):
    monkeypatch.setattr(fms, "vault_get", lambda cle: valeurs.get(cle))
    monkeypatch.setattr(fms, "vault_available", lambda: True)


def _lancer(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["forge_mcp_json_sync.py", *args])
    rc = fms.main()
    return rc, capsys.readouterr()


def test_emet_le_jeton_propre(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON, "FORGE_MCP_TOKEN": "maitre"})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    entetes = json.loads(sortie.out)
    assert rc == 0 and entetes["Authorization"] == "Bearer " + JETON
    assert entetes["X-Agent-Name"] == "CLAUDE"


def test_jamais_le_maitre_en_repli(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_MCP_TOKEN": "maitre"})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    assert rc != 0 and sortie.out == "", "jeton propre absent : aucun en-tete, surtout pas le maitre"
    assert "maitre" not in sortie.out


def test_verifier_n_expose_pas_la_valeur(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE", "--verifier")
    assert rc == 0 and JETON not in sortie.out
    assert json.loads(sortie.out)["longueur_jeton"] == len(JETON)


def test_cli_reel_provenance_verifier_liste_la_cle_sans_la_valeur():
    """Traverse le VRAI main() en sous-processus ; seul le coffre est simule (jeton factice)."""
    import subprocess
    prog = ("import sys; sys.path.insert(0, %r); import forge_mcp_json_sync as f; "
            "f.vault_get = lambda k: 'jeton-factice-nr' if k == 'FORGE_TOKEN_NR_X' else None; "
            "f.vault_available = lambda: True; sys.argv = ['x'] + sys.argv[1:]; sys.exit(f.main())"
            % str(Path(__file__).resolve().parents[2] / "tools"))
    base = [sys.executable, "-c", prog, "--emit-headers", "NR_X"]
    kw = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    p = subprocess.run(base + ["--provenance", "task_executor", "--verifier"], **kw)
    assert p.returncode == 0
    d = json.loads(p.stdout)
    assert "LaForge-Provenance" in d["cles"] and d["longueur_jeton"] == len("jeton-factice-nr")
    assert "jeton-factice-nr" not in p.stdout + p.stderr
    p = subprocess.run(base + ["--provenance", "task_executor"], **kw)
    assert json.loads(p.stdout)["LaForge-Provenance"] == "TASK_EXECUTOR"
    p = subprocess.run(base, **kw)
    assert json.loads(p.stdout)["LaForge-Provenance"] == "INCONNUE"


def test_un_serveur_a_helper_n_est_jamais_reecrit_en_clair(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    cfg = {"mcpServers": {"hub": {"type": "http", "headersHelper": "x",
                                  "headers": {"X-Agent-Name": "CLAUDE"}}}}
    nouveau, changements = fms._patch_config(cfg)
    assert "Authorization" not in nouveau["mcpServers"]["hub"]["headers"]
    assert changements[0][1].startswith("HEADERS_HELPER")


# --- Phase 2 identites : mesure de CLAUDE_CODE_ENTRYPOINT (journal, sans changer l'identite) ---

def _chemin_journal(tmp_path):
    return tmp_path / "sandbox" / "logs" / "headers_helper.jsonl"


def _journal(tmp_path):
    p = _chemin_journal(tmp_path)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_journal_entrypoint_cli(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE", "--provenance", "x")
    lignes = _journal(tmp_path)
    assert rc == 0 and len(lignes) == 1
    assert lignes[0]["entrypoint"] == "cli" and lignes[0]["agent"] == "CLAUDE"
    assert set(lignes[0]) == {"ts", "agent", "provenance", "entrypoint", "parent_pid"}
    assert json.loads(sortie.out)["Authorization"] == "Bearer " + JETON


def test_journal_entrypoint_absent(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    assert _journal(tmp_path)[0]["entrypoint"] == "ABSENT"


def test_journal_sans_jeton(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    brut = _chemin_journal(tmp_path).read_text(encoding="utf-8")
    assert JETON not in brut and "Bearer" not in brut


def test_echec_ecriture_journal_ne_change_rien(monkeypatch, capsys, tmp_path):
    fichier = tmp_path / "pasundossier"
    fichier.write_text("x")
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(fichier))
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    assert rc == 0 and json.loads(sortie.out)["Authorization"] == "Bearer " + JETON
