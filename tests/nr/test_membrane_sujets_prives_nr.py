"""NR -- le prive ne sort pas vers les agents exposes : un seul organe, la membrane, et une seule definition, sujets_prives.

Choix owner du 6/11 : on classe la tache, pas le modele. Mesure du meme jour : 86 appels d'agents OpenCode et Vibe touchaient
un mot ou un chemin prive en octobre, alors que `config/sujets_prives.txt` ne protegeait que la publication.
Les sujets de ce test sont FICTIFS : ce fichier part dans le depot public.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_sovereign_membrane as M  # noqa: E402

pytestmark = pytest.mark.timeout(60)
SUJETS = {"chemins": ["docs/projetfictif/*", "**/projetfictif_*"], "mots": ["projet\\s*fictif"], "caviarder": ["README.md"],
          "retirer": ["phrase fictive a retirer"], "erreurs": []}


@pytest.fixture(autouse=True)
def sujets(monkeypatch):
    monkeypatch.setattr(M, "_lire_sujets", lambda: SUJETS)
    monkeypatch.setattr(M, "_cle_sujets", lambda: object())


@pytest.fixture
def membrane(tmp_path):
    return M.SovereignMembrane(mission_id="nr_sujets", db_path=str(tmp_path / "m.db"), hmac_secret=b"n" * 32)


def test_le_mode_reversible_aliase_et_restitue(membrane):
    texte = "le projet fictif avance ; phrase fictive a retirer"
    sortie = membrane.wrap_objet(texte)
    assert "fictif" not in sortie.lower().replace("srv_", "") or "projet fictif" not in sortie
    assert "projet fictif" not in sortie and "phrase fictive a retirer" not in sortie
    assert membrane.unwrap_objet(sortie, "m") == texte


def test_le_mode_de_reconnaissance_masque_aussi(membrane):
    assert "projet fictif" not in membrane.wrap("le projet fictif avance").content


@pytest.mark.parametrize("agent", ["OPENCODE_GLM", "opencode_nemotron", "VIBE_HEADLESS", "MISTRAL", "CODEX", "agt_cline", "OAUTH_nkc_inconnu"])
def test_agents_exposes(agent):
    assert M.agent_expose(agent)


@pytest.mark.parametrize("agent", ["CLAUDE", "CLAUDE_HEADLESS", "ANTIGRAVITY", "agt_antigravity", "POST_COMMIT", "TRAY", "HUB", ""])
def test_agents_non_exposes(agent):
    assert not M.agent_expose(agent)


@pytest.mark.parametrize("agent,ring,attendu", [
    ("IDENTITE_INCONNUE", 4, True), ("IDENTITE_INCONNUE", 3, True), ("IDENTITE_INCONNUE", 2, False), ("IDENTITE_INCONNUE", None, False),
    ("POST_COMMIT", 3, False), ("CLAUDE", 3, False), ("CLAUDE_HOOK", 4, False), ("OPENCODE_GLM", 1, True),
])
def test_le_ring_expose_une_identite_inconnue_jamais_un_service(agent, ring, attendu):
    """Mesure du 6/11 : `read` et `rag` s'ouvrent aux rings 3 et 4, le filtre ne visait que des noms connus. Liste blanche : un
    service declare au registre reste interne, tout le reste de ring 3 ou 4 est expose."""
    assert M.agent_expose(agent, ring) is attendu


def test_le_hub_passe_le_ring_au_filtre():
    assert "filtrer_sortie_agent(result, agent, args, ring)" in _source_fonction("app/forge_mcp_registry.py", "dispatch")


def test_client_oauth_lu_par_son_nom_inscrit(monkeypatch):
    monkeypatch.setattr(M, "_nom_client_oauth", lambda c: "Claude Code (nokido-oauth)" if "CLAUDE" in c.upper() else "OpenCode")
    assert not M.agent_expose("OAUTH_nkc_CLAUDEX")
    assert M.agent_expose("OAUTH_nkc_autre")


def test_sortie_caviardee_pour_un_agent_expose_texte_et_structure():
    assert "projet fictif" not in M.filtrer_sortie_agent("voici le projet fictif", "OPENCODE_GLM", {})
    d = M.filtrer_sortie_agent({"a": ["Projet  Fictif"], "n": 3}, "VIBE_HEADLESS", {})
    assert d["n"] == 3 and M.MASQUE_SUJET in d["a"][0]


def test_sortie_intacte_pour_un_agent_non_expose():
    assert M.filtrer_sortie_agent("voici le projet fictif", "CLAUDE", {}) == "voici le projet fictif"
    assert M.filtrer_sortie_agent("voici le projet fictif", "POST_COMMIT", {}) == "voici le projet fictif"


def test_un_document_seulement_a_caviarder_n_est_pas_un_sujet():
    """Paye le 6/11 : le premier audit comptait `caviarder` (README.md) comme un sujet prive."""
    assert M.filtrer_sortie_agent("lire README.md", "OPENCODE_GLM", {"path": "README.md"}) == "lire README.md"


@pytest.mark.parametrize("chemin", ["docs/projetfictif/a.md", r"C:\Users\x\Nokido\docs\projetfictif\a.md"])
def test_un_chemin_prive_est_refuse_pour_un_agent_expose(chemin):
    sortie = M.filtrer_sortie_agent("contenu secret du fichier", "OPENCODE_GLM", {"path": chemin})
    assert "contenu secret" not in sortie and "[SUJET PRIVE]" in sortie


def test_filtre_en_panne_ferme_pour_un_agent_expose_seulement(monkeypatch):
    def casse():
        raise RuntimeError("liste illisible")
    monkeypatch.setattr(M, "_lire_sujets", casse)
    assert "[SUJET PRIVE]" in M.filtrer_sortie_agent("contenu", "OPENCODE_GLM", {})
    assert M.filtrer_sortie_agent("contenu", "CLAUDE", {}) == "contenu"


def test_liste_absente_ne_masque_rien(monkeypatch):
    """Distribution publique : la liste n'existe pas, il n'y a rien a proteger."""
    monkeypatch.setattr(M, "_lire_sujets", lambda: {"chemins": [], "mots": [], "caviarder": [], "retirer": [], "erreurs": []})
    assert M.filtrer_sortie_agent("contenu", "OPENCODE_GLM", {}) == "contenu"


def test_consigne_privee_refusee_pour_un_agent_expose():
    motif = M.refus_sujet_prive("analyse le projet fictif", "OPENCODE_GLM")
    assert motif and "[SUJET PRIVE]" in motif and "projet fictif" not in motif
    assert M.refus_sujet_prive("ouvre docs/projetfictif/a.md", "VIBE") and M.refus_sujet_prive("analyse le projet fictif", "CLAUDE") is None
    assert M.refus_sujet_prive("corrige le juge de livraison", "OPENCODE_GLM") is None


# --- Worktree : mesure du 6/11, 65 fichiers prives suivis sur alpha, donc lisibles localement par le CLI d'un agent expose


@pytest.fixture(scope="module")
def executeur():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sujets_prives_executeur_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["sujets_prives_executeur_nr"] = m
    spec.loader.exec_module(m)
    return m


def _depot(tmp_path):
    import os
    import subprocess
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def g(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-C", str(tmp_path), *a],
                              check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env).stdout
    g("init", "-q")
    (tmp_path / "docs" / "projetfictif").mkdir(parents=True)
    (tmp_path / "docs" / "projetfictif" / "a.md").write_text("contenu prive", encoding="utf-8")
    (tmp_path / "public.txt").write_text("contenu public", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "base")
    return g


def test_les_fichiers_prives_quittent_le_worktree_sans_salir_git(executeur, tmp_path):
    g = _depot(tmp_path)
    assert executeur._retirer_fichiers_prives_worktree(tmp_path) == 1
    assert not (tmp_path / "docs" / "projetfictif" / "a.md").exists()
    assert (tmp_path / "public.txt").read_text(encoding="utf-8") == "contenu public"
    assert g("status", "--short") == ""


def test_worktree_sans_fichier_prive_reste_intact(executeur, tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_lire_sujets", lambda: dict(SUJETS, chemins=["autre/*"]))
    _depot(tmp_path)
    assert executeur._retirer_fichiers_prives_worktree(tmp_path) == 0
    assert (tmp_path / "docs" / "projetfictif" / "a.md").exists()


def test_un_retrait_impossible_leve(executeur, tmp_path, monkeypatch):
    _depot(tmp_path)
    vrai = executeur._wt_git

    class Refus:
        returncode = 1
        stderr = "refuse"
        stdout = ""
    monkeypatch.setattr(executeur, "_wt_git", lambda c, *a: Refus() if "update-index" in a else vrai(c, *a))
    with pytest.raises(RuntimeError):
        executeur._retirer_fichiers_prives_worktree(tmp_path)
    assert (tmp_path / "docs" / "projetfictif" / "a.md").exists()


def test_le_retrait_precede_le_travail_de_l_agent():
    corps = _source_fonction("tools/forge_task_executor.py", "_avec_worktree_tache")
    assert "agent_expose(agent)" in corps
    assert corps.index("_retirer_fichiers_prives_worktree(") < corps.index("_WT_TACHE.set(wt)")


def _source_fonction(rel, nom):
    src = (RACINE / rel).read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return "\n".join(src.splitlines()[n.lineno - 1:n.end_lineno])
    raise AssertionError(nom)


def test_le_hub_filtre_au_point_d_envoi_unique():
    corps = _source_fonction("app/forge_mcp_registry.py", "dispatch")
    assert corps.index("await handler(args, agent, ring)") < corps.index("filtrer_sortie_agent(")


def test_l_executeur_refuse_avant_toute_distribution():
    src = (RACINE / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    assert src.index("refus_sujet_prive(") < src.index('_params_enquete = _mode_enquete(task["description"]')
