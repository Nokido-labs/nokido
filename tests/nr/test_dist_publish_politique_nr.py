"""NR — l'assemblage du dist applique blocked_paths, car son push CONTOURNE le
gate egress.

`forge_dist_publish` pousse vers un dépôt SÉPARÉ (nokido-dist) : ce push n'est
PAS soumis au gate egress du dépôt source. Sans application de la politique à
l'assemblage, `git archive` (export-ignore seul) laisserait partir docs/ip,
.agents, config env-spécifique, etc. Ce NR verrouille l'application, l'épargne du
cœur, la non-descente dans .git, le cap de taille et le fail-closed.

Hermétique : arbre en tmp, aucun réseau, aucun push, aucun git.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_dist_publish as D  # noqa: E402
import forge_git_egress as EG  # noqa: E402


def _arbre(tmp: Path):
    # Owner 2026-09-30 : « pleinement fonctionnel, pas bride » -- la politique ne
    # bloque plus que securite et vie privee. Les trois premiers chemins restent
    # BLOQUES (liste privee d'identites, offensif CH88, etat volatil) ; les trois
    # suivants etaient bloques avant cette date et doivent desormais PARTIR.
    for rel in ("config/identites_privees.txt",
                "tools/ch88_scan.py",
                "sandbox/.ngrok_pid",
                "docs/ip/IP_TRIAGE_CANDIDATS.md",
                ".agents/skills/forge-core/SKILL.md",
                "proxy_deno/core/services.toml",
                "app/forge_core.py",
                "tools/forge_util.py",
                "README.md",
                "docs/skills/nokido/SKILL.md"):
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    (tmp / ".git").mkdir(exist_ok=True)
    (tmp / ".git" / "config").write_text("[core]", encoding="utf-8")


def test_retire_les_bloques_et_epargne_le_coeur(tmp_path):
    _arbre(tmp_path)
    D._appliquer_politique_publique(tmp_path)
    assert not (tmp_path / "config/identites_privees.txt").exists()
    assert not (tmp_path / "tools/ch88_scan.py").exists()
    assert not (tmp_path / "sandbox/.ngrok_pid").exists()
    # Ce qui fait TOURNER Nokido part : superviseur, skills.
    assert (tmp_path / "proxy_deno/core/services.toml").exists()
    assert (tmp_path / ".agents/skills/forge-core/SKILL.md").exists()
    # IP_CLEARANCE (owner 2026-09-30) : un document IP non libere nommement reste en HOLD.
    assert not (tmp_path / "docs/ip/IP_TRIAGE_CANDIDATS.md").exists()
    assert (tmp_path / "app/forge_core.py").exists()
    assert (tmp_path / "tools/forge_util.py").exists()
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "docs/skills/nokido/SKILL.md").exists()


def test_ne_descend_jamais_dans_git(tmp_path):
    _arbre(tmp_path)
    D._appliquer_politique_publique(tmp_path)
    assert (tmp_path / ".git" / "config").exists(), ".git ne doit pas etre touche"


def test_fail_closed_sans_profil_public(tmp_path, monkeypatch):
    _arbre(tmp_path)
    monkeypatch.setattr(EG, "load_manifest", lambda: {"profiles": {}})
    try:
        D._appliquer_politique_publique(tmp_path)
    except RuntimeError as e:
        assert "public" in str(e).lower()
    else:
        raise AssertionError("politique illisible : la publication aurait dû être refusée")


def test_cap_de_taille_leve_une_erreur(tmp_path, monkeypatch):
    _arbre(tmp_path)
    (tmp_path / "gros.bin").write_bytes(b"0" * 2048)
    monkeypatch.setattr(EG, "load_manifest",
                        lambda: {"profiles": {"public": {"blocked_paths": [], "max_file_bytes": 1024}}})
    try:
        D._appliquer_politique_publique(tmp_path)
    except RuntimeError as e:
        assert "cap" in str(e).lower()
    else:
        raise AssertionError("un fichier au-dessus du cap aurait dû être refusé")
