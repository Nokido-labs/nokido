"""NR -- l'installeur PRODUIT (nokido-composants) pose aussi les modeles et le Knowledge Pack (2026-10-13).

Mesure du parcours paquet : installe par pip, aucune commande ne posait bge-m3 ni le pack RAG -- seul le banc de test
le savait. Owner : « certains elements du RAG doivent etre presents via l'installeur ».

Ce qui est garde :
  * `--tout` couvre modeles ET connaissances ; les modeles vont dans data/llm_models sous leur nom epingle ;
  * le pack est juge sur « inserted » (l'artefact), jamais sur le rc seul ; un schema en echec arrete avant l'import ;
  * le doctor NOMME la commande quand un BLOQUANT est posable par elle (llama, modele), et pas pour deno ;
  * `nokido-composants` est une commande publique du paquet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for p in (RACINE / "tools", RACINE / "app", RACINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_composants as F  # noqa: E402


def test_tout_couvre_modeles_et_connaissances():
    assert "modeles" in F.COMPOSANTS and "connaissances" in F.COMPOSANTS
    assert F.POSEURS["modeles"] is F.poser_modeles and F.POSEURS["connaissances"] is F.poser_connaissances


def test_modeles_poses_sous_leur_nom_epingle(monkeypatch):
    poses: list = []
    monkeypatch.setattr(F, "telecharger", lambda c, dossier: poses.append((c["id"], dossier)) or dossier / c["id"])
    ok, detail = F.poser_modeles()
    assert ok, detail
    assert [cid for cid, _ in poses] == list(F.MODELES)
    assert all(d == F.ROOT / "data" / "llm_models" for _, d in poses)


@pytest.mark.parametrize("sorties, attendu", [
    ([(0, "schema ok"), (0, '{"inserted": 29700, "skipped": 0}')], True),
    ([(0, "schema ok"), (0, "rien importe")], False),          # rc 0 sans artefact : pas un succes
    ([(1, "schema KO"), (0, '{"inserted": 1}')], False),       # schema en echec : l'import n'est pas tente
])
def test_connaissances_jugees_sur_l_artefact(monkeypatch, sorties, attendu):
    appels: list = []

    def faux_sh(cmd, timeout=600, cwd=None, env=None):
        appels.append(cmd)
        return sorties[len(appels) - 1]

    monkeypatch.setattr(F, "sh", faux_sh)
    monkeypatch.delenv("NOKIDO_PACK_FICHIER", raising=False)
    ok, _detail = F.poser_connaissances()
    assert ok is attendu
    assert appels[0][-1].endswith("forge_db_bootstrap.py")
    if sorties[0][0] == 0:
        assert "--download" in appels[1] and appels[1][1].endswith("forge_knowledge_pack_import.py")
    else:
        assert len(appels) == 1


def test_la_repetition_importe_le_pack_CANDIDAT_local(monkeypatch, tmp_path):
    """2026-10-16 : 0.20.12 a ete essayee avec le pack 0.20.9 (defaut fige), le pack livre etait refuse par
    l'importeur. La repetition importe le fichier de la release BROUILLON (NOKIDO_PACK_FICHIER), sha verifie ;
    fichier annonce mais absent = ECHEC dit, jamais un repli silencieux sur une release publiee."""
    appels: list = []

    def faux_sh(cmd, timeout=600, cwd=None, env=None):
        appels.append(cmd)
        return (0, '{"inserted": 40990, "skipped": 0}')

    monkeypatch.setattr(F, "sh", faux_sh)
    pack = tmp_path / "nokido_knowledge_pack_v9.9.9.npz"
    pack.write_bytes(b"x")
    monkeypatch.setenv("NOKIDO_PACK_FICHIER", str(pack))
    monkeypatch.setenv("NOKIDO_PACK_SHA256", "ab" * 32)
    ok, detail = F.poser_connaissances()
    assert ok and "CANDIDAT" in detail
    imp = appels[1]
    assert "--from" in imp and imp[imp.index("--from") + 1] == str(pack) and "--download" not in imp
    assert imp[imp.index("--expect-sha256") + 1] == "ab" * 32
    appels.clear()
    monkeypatch.setenv("NOKIDO_PACK_FICHIER", str(tmp_path / "absent.npz"))
    ok, detail = F.poser_connaissances()
    assert ok is False and "ABSENT" in detail and len(appels) == 1, "pas d'import de repli"


def test_le_doctor_nomme_la_commande_quand_elle_leve_le_bloquant():
    import nokido_doctor as D
    b = D.P.bilan(inclure_optionnels=False, profil="dev")
    b["bloquants"] = ["llama_server", "modele:bge-m3-Q8_0.gguf"]
    assert "nokido-composants --tout" in D.rendre_texte(b, verbeux=False)
    b["bloquants"] = ["deno"]
    assert "nokido-composants --tout" in D.rendre_texte(b, verbeux=False)
    b["bloquants"] = ["git"]   # hors de portee de l'installeur : ne pas promettre ce qu'il ne fait pas
    assert "nokido-composants" not in D.rendre_texte(b, verbeux=False)


def test_deno_epingle_sur_les_quatre_plateformes_et_pose_en_standard(monkeypatch, tmp_path):
    for p in ("windows-x64", "linux-x64", "macos-arm64", "macos-x64"):
        c = F.composant("deno-%s" % p)
        assert c["url"].startswith("https://github.com/denoland/deno/releases/download/v")
        assert len(c["sha256"]) == 64 and c["taille"] > 10_000_000
    assert F.COMPOSANTS[0] == "deno" and F.POSEURS["deno"] is F.poser_deno
    monkeypatch.setattr(F.shutil, "which", lambda nom: None)
    monkeypatch.setattr(F.Path, "home", classmethod(lambda cls: tmp_path))
    poses: list = []

    def faux_extraire(arch, cible):
        poses.append(cible)
        cible.mkdir(parents=True, exist_ok=True)
        (cible / ("deno" + F.EXE)).write_bytes(b"x")

    monkeypatch.setattr(F, "telecharger", lambda c, dl: tmp_path / "a.zip")
    monkeypatch.setattr(F, "extraire", faux_extraire)
    monkeypatch.setattr(F, "_executable", lambda p: None)
    monkeypatch.setattr(F, "sh", lambda cmd, timeout=600, cwd=None, env=None: (0, "deno 2.9.7"))
    ok, detail = F.poser_deno()
    assert ok and poses == [tmp_path / ".deno" / "bin"], detail


@pytest.mark.parametrize("rcs, attendu", [((0, 0), True), ((0, 3), False), ((1, 0), False)])
def test_jeton_du_premier_client_seme_et_relu(monkeypatch, rcs, attendu):
    appels: list = []

    def faux_sh(cmd, timeout=600, cwd=None, env=None):
        appels.append(cmd)
        return rcs[len(appels) - 1], "sortie sans valeur"

    monkeypatch.setattr(F, "sh", faux_sh)
    ok, detail = F.poser_jetons()
    assert ok is attendu, detail
    assert appels[0][1].endswith("forge_vault_seed_agent_tokens.py")
    # jamais --overwrite (pas de rotation) ; --from-registre : EDITOR n'est pas dans la liste figee du generateur
    assert appels[0][2:] == ["--generate-missing", "--from-registre", "--agents", "EDITOR"]
    assert "FORGE_TOKEN_EDITOR" in appels[1][-1] and F.COMPOSANTS[-1] == "jetons"


def test_editor_n_est_semable_que_depuis_le_registre():
    """Chemin REEL du generateur, pas un argv recopie : le NR precedent figeait l'argv sans --from-registre et
    passait pendant que le semis ne posait rien sur les 3 OS (parcours paquet du 13/10, « AGENT(S) NON TROUVE(S) »)."""
    import forge_vault_seed_agent_tokens as G
    assert "FORGE_TOKEN_EDITOR" not in G.EXPECTED_KEYS
    assert "FORGE_TOKEN_EDITOR" in G._cles_du_registre(3)


def test_cli_presente_le_jeton_derive_sans_maitre(monkeypatch):
    import llama_cli as C
    coffre = {"FORGE_TOKEN_EDITOR": "derive-de-test"}
    monkeypatch.setattr(C, "get_secret", lambda k: coffre.get(k))
    monkeypatch.setattr(C, "_hub_token", lambda: "")
    h = C._hub_headers()
    assert h["X-Agent-Name"] == "EDITOR" and h["Authorization"] == "Bearer derive-de-test"
    monkeypatch.setattr(C, "_hub_token", lambda: "maitre-de-test")      # poste owner : comportement inchange
    h = C._hub_headers()
    assert h["X-Agent-Name"] == "LAFORGE_CLI" and h["Authorization"] == "Bearer maitre-de-test"
    coffre.clear()
    monkeypatch.setattr(C, "_hub_token", lambda: "")
    assert "Authorization" not in C._hub_headers()


@pytest.mark.parametrize("texte, attendu", [
    ('{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}', "ok"),
    ('event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{"p":1}}\n\n'
     'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"fini"}]}}\n\n', "fini"),
])
def test_cli_lit_json_et_sse(texte, attendu):
    import llama_cli as C
    d = C.decoder_reponse_mcp(texte)
    assert d["result"]["content"][0]["text"] == attendu


def test_cli_reponse_illisible_dite_pas_de_traceback():
    import llama_cli as C
    d = C.decoder_reponse_mcp("<html>502 Bad Gateway</html>")
    assert "illisible" in d["error"]


def test_cli_suit_le_port_du_hub(monkeypatch):
    import importlib

    import llama_cli as C
    monkeypatch.setenv("LAFORGE_HUB_PORT", "18766")
    try:
        assert importlib.reload(C).HUB_BASE.endswith(":18766")
    finally:
        monkeypatch.delenv("LAFORGE_HUB_PORT")
        importlib.reload(C)


def test_commande_publique_declaree():
    pyproject = (RACINE / "pyproject.toml").read_text(encoding="utf-8")
    assert 'nokido-composants = "nokido_agent.tools.forge_composants:main"' in pyproject
