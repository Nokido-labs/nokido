"""NR -- le compte d'execution se DECLARE dans le script et se VERIFIE a l'appel (owner 15/10 : « les problemes de
compte sont recurrents, corrige-le pour de bon dans le process d'appel des tools »).

Mesure qui l'impose : CI de reference lancee `run_job online=true` par un RELAIS ; la regle existante ne lisait que le
texte de l'appel (le chemin du relais), n'a rien vu, et la CI est morte en REFUS (`.git/worktrees: Permission denied`).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import hook_capability_gate as g  # noqa: E402

RUN = "mcp__laforge-sovereign-hub__run"


def _depot(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_ci_reference.py").write_text(
        '"""doc"""\n# nokido-compte: hors_ligne  -- worktree git\nimport sys\n', encoding="utf-8")
    (tmp_path / "tools" / "forge_reseau.py").write_text("# nokido-compte: en_ligne\n", encoding="utf-8")
    (tmp_path / "tools" / "forge_owner.py").write_text("# nokido-compte: owner\n", encoding="utf-8")
    (tmp_path / "tools" / "forge_libre.py").write_text("print('rien de declare')\n", encoding="utf-8")
    relais = tmp_path / "relais_ci.py"
    relais.write_text('OUTIL = r"C:/x/Nokido/tools/forge_ci_reference.py"\n', encoding="utf-8")
    return str(tmp_path), str(relais)


def _lire(racine):
    return lambda script: g.compte_declare(script, racine=racine)


def test_un_relais_herite_de_la_declaration_de_l_outil_qu_il_appelle(tmp_path):
    racine, relais = _depot(tmp_path)
    assert g.compte_declare(relais, racine=racine) == ("hors_ligne", "tools/forge_ci_reference.py")
    bloque, msg = g.verdict_compte(RUN, {"action": "run_job", "script": relais, "online": True}, lire=_lire(racine))
    assert bloque and "SANS `online`" in msg and "worktrees" in msg
    assert g.verdict_compte(RUN, {"action": "run_job", "script": relais}, lire=_lire(racine)) == (False, "")


def test_en_ligne_lance_hors_ligne_est_refuse(tmp_path):
    racine, _ = _depot(tmp_path)
    bloque, msg = g.verdict_compte(RUN, {"action": "run_job", "script": "tools/forge_reseau.py"}, lire=_lire(racine))
    assert bloque and "online=true" in msg
    assert g.verdict_compte(RUN, {"action": "run_job", "script": "tools/forge_reseau.py", "online": True},
                            lire=_lire(racine)) == (False, "")


def test_owner_n_est_jamais_un_job(tmp_path):
    racine, _ = _depot(tmp_path)
    for entree in ({"action": "run_job", "script": "tools/forge_owner.py"},
                   {"action": "run_job", "script": "tools/forge_owner.py", "online": True},
                   {"action": "trusted_script", "path": "tools/forge_owner.py"}):
        bloque, msg = g.verdict_compte(RUN, entree, lire=_lire(racine))
        assert bloque and "CONSOLE" in msg


def test_sans_declaration_le_gate_ne_devine_rien(tmp_path):
    racine, _ = _depot(tmp_path)
    for entree in ({"action": "run_job", "script": "tools/forge_libre.py", "online": True},
                   {"action": "run_job", "script": "tools/absent.py"},
                   {"action": "shell", "code": "tools/forge_owner.py"}):
        assert g.verdict_compte(RUN, entree, lire=_lire(racine)) == (False, "")
    assert g.verdict_compte("mcp__autre__run_job", {"action": "run_job", "script": "x"}) == (False, "")


def test_les_outils_payes_portent_leur_declaration():
    attendu = {"ci_local.py": "hors_ligne", "forge_ci_reference.py": "hors_ligne",
               "forge_lean_provision.py": "owner", "forge_card_summarize.py": "owner"}
    for nom, compte in attendu.items():
        assert g.compte_declare(os.path.join("tools", nom), racine=str(ROOT))[0] == compte, nom
