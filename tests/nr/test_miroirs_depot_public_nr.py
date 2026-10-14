# -*- coding: utf-8 -*-
"""NR - les miroirs ne publient QUE le depot public (owner 2026-10-13).

Owner : « attention c'est le depot nokido PUBLIC que je veux publier sur ces plateformes » ;
« sur codeberg un NOUVEAU depot correspondant au public uniquement, pas le depot prive a rendre
public ». Le mode historique de publish_multi pousse DEPUIS l'atelier (ROOT) : le mode miroirs
ne doit jamais en faire autant.

Contrats :
  1. la seule source clonee est SOURCE_PUBLIQUE ; aucun appel git ne vise l'atelier ;
  2. a blanc (sans --push) : aucun push, aucune creation ;
  3. le jeton passe par l'environnement, jamais par argv ni par l'URL ;
  4. le verdict se lit sur le DISTANT : rc=0 sans le bon sha = NON_PUBLIE, rc=1 avec = PUBLIE ;
  5. une cible creee l'est EN PUBLIC ; seules branches et tags partent (pas refs/pull/*).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import publish_multi as P  # noqa: E402

SHA = "a" * 40
JETON = "JETON-SENTINELLE-NR"


class _Git:
    """Faux git : rejoue clone/symbolic-ref/rev-parse/ls-remote/push et garde chaque argv."""

    def __init__(self, distant_apres: str, push_rc: int = 0):
        self.appels: list = []
        self.distant = ""
        self.distant_apres = distant_apres
        self.push_rc = push_rc

    def __call__(self, args, env, timeout=900):
        self.appels.append(list(args))
        out, rc = "", 0
        if "symbolic-ref" in args:
            out = "main\n"
        elif "rev-parse" in args:
            out = SHA + "\n"
        elif "ls-remote" in args:
            out = (self.distant + "\trefs/heads/main\n") if self.distant else ""
        elif "push" in args:
            rc = self.push_rc
            self.distant = self.distant_apres
        return subprocess.CompletedProcess(args, rc, out, "refus simule" if rc else "")


@pytest.fixture
def faux(monkeypatch):
    monkeypatch.setattr(P, "_secret", lambda nom: JETON)
    creations: list = []

    def creer(nom, m, agir):
        creations.append((nom, agir))
        return "creee:public" if agir else "absente(http 404)"

    monkeypatch.setattr(P, "_creer_cible", creer)
    return creations


def test_source_unique_le_depot_public_et_rien_a_blanc(monkeypatch, faux):
    git = _Git(distant_apres=SHA)
    monkeypatch.setattr(P, "_git", git)
    rapport = P.miroirs_publics(["codeberg", "gitlab"], agir=False)
    clones = [a for a in git.appels if "clone" in a]
    assert len(clones) == 1 and P.SOURCE_PUBLIQUE in clones[0]
    assert P.SOURCE_PUBLIQUE.startswith("https://github.com/Nokido-labs/nokido")
    destination = clones[0][-1]
    assert destination.endswith("public.git") and Path(destination).resolve() != ROOT / ".git"
    git_dirs = [a[a.index("--git-dir") + 1] for a in git.appels if "--git-dir" in a]
    assert git_dirs and set(git_dirs) == {destination}, "un appel git vise un autre depot que le clone public"
    assert not any("-C" in a for a in git.appels)
    assert not any("push" in a for a in git.appels), "a blanc, rien ne part"
    assert all(agir is False for _, agir in faux)
    assert {c["verdict"] for c in rapport["cibles"].values()} == {"A_BLANC"}


def test_jeton_dans_l_environnement_jamais_dans_argv(monkeypatch, faux, tmp_path):
    env, args = P._env_et_cred(P.MIROIRS_PUBLICS["codeberg"], tmp_path)
    assert env["NOKIDO_MIROIR_JETON"] == JETON
    assert JETON not in " ".join(args)
    git = _Git(distant_apres=SHA)
    monkeypatch.setattr(P, "_git", git)
    P.miroirs_publics(["codeberg", "gitlab"], agir=True)
    assert git.appels and not any(JETON in " ".join(a) for a in git.appels)
    for nom in ("codeberg", "gitlab"):
        assert "@" not in P.MIROIRS_PUBLICS[nom]["url"], "aucun identifiant dans l'URL"


@pytest.mark.parametrize("push_rc, apres, attendu", [
    (0, "b" * 40, "NON_PUBLIE"),   # rc vert, distant faux : le rc mentait
    (1, SHA, "PUBLIE"),            # rc rouge, distant juste : le distant fait foi
])
def test_verdict_lu_sur_le_distant(monkeypatch, faux, push_rc, apres, attendu):
    monkeypatch.setattr(P, "_git", _Git(distant_apres=apres, push_rc=push_rc))
    rapport = P.miroirs_publics(["gitlab"], agir=True)
    assert rapport["cibles"]["gitlab"]["verdict"] == attendu


def test_refspecs_branches_et_tags_seulement_sans_force():
    assert P._REFSPECS and all(r.startswith(("refs/heads/", "refs/tags/")) for r in P._REFSPECS)
    assert not any(r.startswith("+") for r in P._REFSPECS), "un miroir qui diverge le DIT"


def test_cibles_creees_en_public(monkeypatch):
    monkeypatch.setattr(P, "_secret", lambda nom: JETON)
    requests = pytest.importorskip("requests")
    envois: list = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {}

    monkeypatch.setattr(requests, "get", lambda *a, **k: R(404))
    monkeypatch.setattr(requests, "post", lambda url, **k: envois.append((url, k["json"])) or R(201))
    assert P._creer_cible("codeberg", P.MIROIRS_PUBLICS["codeberg"], agir=True) == "creee:public"
    assert P._creer_cible("gitlab", P.MIROIRS_PUBLICS["gitlab"], agir=True) == "creee:public"
    (u1, cb), (u2, gl) = envois
    assert cb["private"] is False and cb["name"] == "nokido-public", "Codeberg : NOUVEAU depot, public"
    assert gl["visibility"] == "public"
    envois.clear()
    assert P._creer_cible("codeberg", P.MIROIRS_PUBLICS["codeberg"], agir=False).startswith("absente")
    assert not envois, "a blanc, aucune creation"


def test_hugging_face_n_est_plus_une_copie_du_code():
    """Owner 13/10 : un Space statique seul, pas de depot « model » portant le code."""
    assert "huggingface" not in P.MIROIRS_PUBLICS
    assert P.VITRINE_HF["fichiers"] == ("README.md", "index.html")


def test_la_vitrine_reelle_ne_fuit_rien():
    src = P.VITRINE_HF["source"]
    assert sorted(p.name for p in src.iterdir() if p.is_file()) == sorted(P.VITRINE_HF["fichiers"])
    textes = {n: (src / n).read_text(encoding="utf-8").replace("{{SHA_PUBLIC}}", SHA[:12])
              for n in P.VITRINE_HF["fichiers"]}
    assert P.fuites_vitrine(textes) == []
    assert all("{{SHA_PUBLIC}}" in (src / n).read_text(encoding="utf-8") for n in P.VITRINE_HF["fichiers"])
    balise = "<scr" "ipt"   # page statique SANS code : rien a executer chez le visiteur
    assert balise not in textes["index.html"].lower()


@pytest.mark.parametrize("texte", [
    r"voir C:\Users\owner\Nokido", "chemin /home/owner/nokido", "hub sur localhost", "ecrire a qui@exemple.org",
    "depot nokido-private", "https://exemple.org/page", r"journal sandbox\jobs",
])
def test_fuites_et_liens_hors_liste_refuses(texte):
    assert P.fuites_vitrine({"index.html": texte})


def test_la_vitrine_ouvre_ses_liens_externes_hors_du_cadre_hf():
    """Owner 14/10 : « le Space ne marche pas ». HF sert la vitrine dans une IFRAME ; un lien sans target s'y ouvrait,
    GitHub refuse d'etre encadre -> page brisee. Tout lien externe s'ouvre dans un nouvel onglet, sans opener."""
    import re

    page = (ROOT / "vitrine" / "hf_space" / "index.html").read_text(encoding="utf-8")
    externes = re.findall(r'<a\s[^>]*href="https?://[^"]+"[^>]*>', page)
    assert externes, "aucun lien externe lu : le test ne prouve rien"
    fautifs = [a for a in externes if 'target="_blank"' not in a or "noopener" not in a]
    assert not fautifs, fautifs


def test_liens_permis_et_https_ne_sont_pas_des_chemins():
    ok = "https://github.com/Nokido-labs/nokido#-installation https://pypi.org/project/nokido-agent/"
    assert P.fuites_vitrine({"README.md": ok}) == []


def test_fiche_conforme_topics_en_ensemble_insensible_a_la_casse():
    """13/10 : GitLab rend « RAG » pour « rag », dans son ordre -- la comparaison en liste criait FAIL a tort."""
    assert P.fiche_conforme({"topics": ["rag", "mcp"]}, {"topics": ["MCP", "RAG"]}) == []
    assert P.fiche_conforme({"topics": ["rag", "mcp"]}, {"topics": ["rag"]}) == ["topics"]
    assert P.fiche_conforme({"has_issues": False}, {"has_issues": True}) == ["has_issues"]


def test_un_miroir_renvoie_a_la_source_et_ferme_ce_qui_n_y_a_pas_de_sens():
    gl, cb = P.FICHE_GITLAB, P.FICHE_CODEBERG
    assert gl["auto_devops_enabled"] is False, "une pipeline que personne n'a ecrite"
    assert gl["builds_access_level"] == "enabled" and gl["restrict_user_defined_variables"] is True
    assert gl["issues_access_level"] == gl["merge_requests_access_level"] == "disabled"
    # les tickets de chaque miroir RENVOIENT vers GitHub : un seul support, la source
    assert P.TRACKER_GITLAB["project_url"] == P.TICKETS_GITHUB == "https://github.com/Nokido-labs/nokido/issues"
    assert cb["has_issues"] is True and cb["external_tracker"]["external_tracker_url"] == P.TICKETS_GITHUB
    assert cb["has_pull_requests"] is False and cb["has_wiki"] is True
    assert P.fiche_conforme({"t": {"a": 1}}, {"t": {"a": 1, "ajout_serveur": 2}}) == []
    assert P.fiche_conforme({"t": {"a": 1}}, {"t": {"a": 2}}) == ["t"]
    assert "github.com/Nokido-labs/nokido" in P.DESCRIPTION_MIROIR and cb["website"].endswith("Nokido-labs/nokido")


def test_notes_de_release_miroir_liens_github_et_sha256():
    rel = {"body": "Notes", "html_url": "https://github.com/Nokido-labs/nokido/releases/tag/v1",
           "assets": [{"name": "a.whl", "browser_download_url": "https://github.com/Nokido-labs/nokido/releases/download/v1/a.whl",
                       "digest": "sha256:" + "f" * 64}]}
    notes = P._notes_miroir(rel)
    assert notes.startswith("Notes") and rel["html_url"] in notes
    assert "](https://github.com/Nokido-labs/nokido/releases/download/v1/a.whl)" in notes and "sha256 " + "f" * 64 in notes
    assert P.FICHE_CODEBERG["has_releases"] is True


def test_ci_du_miroir_gitlab_verifie_seulement():
    """La CI de reference et toute publication restent sur GitHub : le miroir rejoue le parcours paquet, rien d'autre."""
    ci = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert "forge_install_acceptance.py" in ci and "--paquet=" in ci
    for interdit in ("twine", "upload", "deploy", "environment:", "secrets", "CI_JOB_TOKEN", "TOKEN", "PASSWORD",
                     "release:"):
        assert interdit not in ci, interdit


def test_surface_du_miroir_gitlab_fermee_et_tags_proteges():
    """Owner 13/10 « securise un max » : mesure du jour, tous ces acces etaient ouverts sur le miroir."""
    gl = P.FICHE_GITLAB
    assert gl["request_access_enabled"] is False and gl["packages_enabled"] is False
    for cle in ("container_registry_access_level", "snippets_access_level", "environments_access_level",
                "feature_flags_access_level", "infrastructure_access_level", "monitor_access_level",
                "requirements_access_level"):
        assert gl[cle] == "disabled", cle
    assert P.TAGS_PROTEGES == "v*"


@pytest.mark.parametrize("compte, ancetre, force", [("1", 1, True), ("7", 0, True), ("7", 1, False)])
def test_wiki_jamais_ecrase_hors_amorce_ou_ancetre(monkeypatch, tmp_path, compte, ancetre, force):
    """Force SEULEMENT si le wiki distant ne porte que l'amorce (1 commit) ou un ancetre de notre historique."""
    monkeypatch.setattr(P, "_secret", lambda nom: JETON)
    pousses: list = []

    def faux_git(args, env, timeout=900):
        if "ls-remote" in args:
            return subprocess.CompletedProcess(args, 0, "abc\trefs/heads/main\n", "")
        if "rev-list" in args:
            return subprocess.CompletedProcess(args, 0, compte + "\n", "")
        if "merge-base" in args:
            return subprocess.CompletedProcess(args, ancetre, "", "")
        if "push" in args:
            pousses.append(args[-1])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(P, "_git", faux_git)
    m = {"hote": "https://codeberg.org", "secret": "CODEBERG_TOKEN", "user": "user"}
    P._pousser_wiki(tmp_path / "wiki.git", "https://codeberg.org/x/y.wiki.git", m, tmp_path)
    assert pousses == [("+" if force else "") + "refs/heads/master:refs/heads/main"]


def test_cible_qui_casse_ne_tait_pas_les_autres(monkeypatch, faux):
    monkeypatch.setattr(P, "_git", _Git(distant_apres=SHA))
    rapport = P.miroirs_publics(["sourceforge_inexistant", "gitlab"], agir=True)
    assert rapport["cibles"]["sourceforge_inexistant"]["verdict"] == "CIBLE_INCONNUE"
    assert rapport["cibles"]["gitlab"]["verdict"] == "PUBLIE"


@pytest.mark.parametrize("agir, poses_attendues, gitlab_attendu", [(True, ["gitlab"], True), (False, [], False)])
def test_logo_unique_pose_si_absent_et_verdict_relu(monkeypatch, agir, poses_attendues, gitlab_attendu):
    """Meme logo que l'organisation GitHub ; pose SEULEMENT si absent (un logo deja la n'est jamais ecrase) ;
    le verdict vient d'une RELECTURE du distant, pas du code de retour de l'ecriture."""
    import types
    assert P.LOGO_GITHUB.startswith("https://avatars.githubusercontent.com/")
    etat = {"gitlab": "", "codeberg": "https://codeberg.org/repo-avatars/x"}
    poses: list = []

    class _R:
        def __init__(self, d=None):
            self._d, self.content = d or {}, b"\xff\xd8\xff"

        def json(self):
            return self._d

    def get(url, headers=None, timeout=None):
        if url == P.LOGO_GITHUB:
            return _R()
        return _R({"avatar_url": etat["gitlab" if "gitlab" in url else "codeberg"]})

    def put(url, **_):
        poses.append("gitlab")
        etat["gitlab"] = "https://gitlab.com/uploads/nokido.jpg"
        return _R()

    def post(url, **_):
        poses.append("codeberg")
        return _R()

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get, put=put, post=post))
    out = P.logo_miroirs("https://gitlab.com/api/v4/projects/x", {}, "https://codeberg.org/api/v1/repos/x", {}, agir)
    assert poses == poses_attendues
    assert out == {"gitlab": gitlab_attendu, "codeberg": True}
