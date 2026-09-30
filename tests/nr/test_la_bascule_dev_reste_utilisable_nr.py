"""NR — la bascule dev doit rester UTILISABLE, et le geste annonce doit EXISTER.

DIRECTIVE OWNER 2026-09-21 : « ne casse pas les bascules sur les mode dev
possible (en cas de gros debug) ».

Un durcissement qui rend le debug impossible sera contourne, puis desarme. Et un
refus qui indique une commande INOPERANTE coute des heures a celui qui la tape.

MESURE QUI MOTIVE CE NR, et c'est ma propre faute
=================================================
`tools/forge_dev_mode.py` prend une ACTION NUE :

    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if action == "arm": ...   /   "disarm"   /   "status"

J'avais ecrit `--arm` dans SIX messages de refus -- dans le commit meme ou je
corrigeais ce defaut ailleurs (`LAFORGE_ALLOW_SECRETS_READ=1` ne debloquait plus
rien). `--arm` n'est pas reconnu : il tombe dans l'aide et rend 1. Le refus
annoncait donc un geste qui ne marche pas.

CE QUE CE NR VERROUILLE
=======================
1. Toute commande `forge_dev_mode.py <x>` citee dans un message de refus doit
   etre une action que le CLI RECONNAIT.
2. `status` reste consultable SANS elevation -- savoir si on est arme ne doit
   jamais exiger d'etre admin.
3. `disarm` existe : une bascule qui ne se referme pas n'est pas une bascule.
4. Le bail vit dans un FICHIER relu a chaque appel, donc armer atteint les
   process DEJA LANCES. C'est ce qu'une variable d'environnement ne pouvait pas
   faire : un service demarre ne voit jamais une variable posee apres coup.
   Le durcissement rend donc le debug PLUS utilisable, pas moins.
5. `is_dev_mode()` (LAFORGE_ENV=dev / LAFORGE_MCP_DEV=true) reste INTACT et
   mordant sur les gardes qui l'ecoutent. Il n'a pas ete touche par le
   durcissement du breakglass, et ce test l'empeche de l'etre par megarde.
"""
import ast
import importlib
import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
DEV = "nokido_agent.tools.forge_dev_mode"
GUARD = "nokido_agent.app.forge_secret_guard"


def _actions_reconnues() -> set[str]:
    """Les actions que `main()` teste REELLEMENT, lues dans son AST."""
    src = (RACINE / "tools" / "forge_dev_mode.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    actions: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Compare) and isinstance(noeud.left, ast.Name) \
                and noeud.left.id == "action":
            for c in noeud.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    actions.add(c.value)
    return actions


def test_le_cli_reconnait_des_actions():
    actions = _actions_reconnues()
    assert {"arm", "disarm", "status"} <= actions, (
        "le CLI doit offrir armer, desarmer ET consulter : %s" % sorted(actions)
    )


@pytest.mark.parametrize("module", ["app/forge_secret_guard.py",
                                    "app/forge_mcp_registry.py"])
def test_les_gestes_annonces_sont_reconnus_par_le_cli(module):
    """LA regle : un refus ne doit jamais proposer une commande inoperante."""
    actions = _actions_reconnues()
    txt = (RACINE / module).read_text(encoding="utf-8", errors="replace")
    cites = re.findall(r"forge_dev_mode\.py[\s'\"]+([A-Za-z\-]+)", txt)
    assert cites, "%s doit nommer le geste de deblocage" % module
    for c in cites:
        assert not c.startswith("-"), (
            "%s annonce '%s' : le CLI prend une ACTION NUE, un prefixe en "
            "tirets tombe dans l'aide et rend 1" % (module, c)
        )
        assert c in actions, (
            "%s annonce '%s', que le CLI ne reconnait pas (%s)"
            % (module, c, sorted(actions))
        )


def test_consulter_l_etat_n_exige_aucune_elevation():
    """Savoir si l'on est arme ne doit jamais demander d'etre admin."""
    dev = importlib.import_module(DEV)
    arme, restant = dev.is_armed()
    assert isinstance(arme, bool)
    assert isinstance(restant, int)
    assert restant >= 0


def test_le_bail_est_un_fichier_relu_donc_il_atteint_les_process_vivants():
    """Le point qui rend le durcissement UTILISABLE.

    Une variable d'environnement n'atteint jamais un service deja demarre : il
    fallait le relancer. Un bail sur fichier, relu a chaque appel, prend effet
    immediatement partout -- et `disarm` le retire de la meme facon.
    """
    dev = importlib.import_module(DEV)
    assert hasattr(dev, "TOKEN_FILE")
    assert hasattr(dev, "disarm"), "une bascule qui ne se referme pas n'en est pas une"
    src = (RACINE / "tools" / "forge_dev_mode.py").read_text(
        encoding="utf-8", errors="replace")
    corps = src[src.find("def is_armed"):]
    assert "read_text" in corps[:900], (
        "is_armed doit RELIRE le bail a chaque appel ; le mettre en cache "
        "empecherait un disarm de prendre effet sur un process vivant"
    )


# ------------------------------------------- la bascule dev n'a pas ete cassee

def test_le_mode_dev_par_environnement_est_intact(monkeypatch):
    """`is_dev_mode()` n'a PAS ete touche par le durcissement du breakglass.

    Ce test existe pour qu'il ne le soit pas par megarde plus tard : c'est la
    voie de debug ordinaire, distincte de l'attestation.
    """
    guard = importlib.import_module(GUARD)
    monkeypatch.delenv("LAFORGE_MCP_DEV", raising=False)
    monkeypatch.setenv("LAFORGE_ENV", "dev")
    assert guard.is_dev_mode() is True
    monkeypatch.setenv("LAFORGE_ENV", "prod")
    monkeypatch.setenv("LAFORGE_MCP_DEV", "true")
    assert guard.is_dev_mode() is True
    monkeypatch.setenv("LAFORGE_MCP_DEV", "false")
    assert guard.is_dev_mode() is False


def test_le_mode_dev_mord_toujours_sur_les_gardes_qui_l_ecoutent(monkeypatch):
    """Mesure du comportement, pas du texte : en dev, le code suspect passe en
    WARN au lieu d'etre bloque."""
    guard = importlib.import_module(GUARD)
    dev = importlib.import_module(DEV)
    monkeypatch.setattr(dev, "is_armed", lambda: (False, 0))   # PAS d'attestation
    monkeypatch.setenv("LAFORGE_ENV", "dev")
    monkeypatch.delenv("LAFORGE_MCP_DEV", raising=False)
    assert guard.sanitize_python_code("open('Nokido.env')", "NR", 0) is None, (
        "en mode dev, sanitize_python_code doit avertir et non bloquer -- "
        "c'est la voie de gros debug, elle ne doit pas disparaitre"
    )


def test_hors_dev_et_sans_attestation_le_garde_bloque(monkeypatch):
    """Le pendant : la bascule preservee ne doit pas devenir une passoire."""
    guard = importlib.import_module(GUARD)
    dev = importlib.import_module(DEV)
    monkeypatch.setattr(dev, "is_armed", lambda: (False, 0))
    monkeypatch.setenv("LAFORGE_ENV", "prod")
    monkeypatch.setenv("LAFORGE_MCP_DEV", "false")
    monkeypatch.setenv("LAFORGE_ALLOW_SECRETS_READ", "1")      # sans effet desormais
    assert guard.sanitize_python_code("open('Nokido.env')", "NR", 0) is not None
