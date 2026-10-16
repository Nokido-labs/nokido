"""NR -- forge_skill_sync ne ressuscite plus une skill retiree, et rafraichit ses anciens deploiements.

Mesure 2026-09-26 : 9 skills absorbees le 2026-08-11 (arbitrage owner : la version fusionnee fait
autorite) sont revenues dans docs/skills. `--apply` avait pris leurs copies restees dans
~/.claude/skills pour des skills nees cote CLI. Mesure 2026-10-14 : ~/.claude/skills/forge-core
portait encore les 7 identites fantomes retirees le 2026-08-11, classee « conflit » et jamais
rafraichie, faute de savoir qu'elle etait une ancienne version du depot.

Ce NR fixe :
  - une skill du registre `retires.json` n'est jamais rapatriee ; ses copies CLI sont DEPLACEES
    par --apply (jamais supprimees) et --rollback les remet ;
  - registre illisible = on leve, jamais « aucun retrait » en silence ;
  - une copie CLI egale a une version VERSIONNEE de la skill est remplacee sans --overwrite ; une
    edition locale reste un conflit ;
  - --prune deplace au lieu de supprimer ;
  - le drapeau --preview traverse tout cela sans rien deplacer.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sync = importlib.import_module("forge_skill_sync")


def _skill(d: Path, slug: str, corps: str = "corps") -> Path:
    (d / slug).mkdir(parents=True, exist_ok=True)
    f = d / slug / "SKILL.md"
    # En octets : write_text traduirait \n en \r\n sous Windows et fausserait le test des fins de ligne.
    f.write_bytes(("---\nname: %s\ndescription: x\n---\n%s\n" % (slug, corps)).encode("utf-8"))
    return f


@pytest.fixture
def poste(tmp_path, monkeypatch):
    """Canonical, dir CLI claude et registre dans tmp. Gemini et Copilot absents : le test ne
    touche JAMAIS un vrai dir de CLI."""
    canon, claude = tmp_path / "docs" / "skills", tmp_path / "home" / ".claude" / "skills"
    canon.mkdir(parents=True)
    claude.mkdir(parents=True)
    retires = tmp_path / "docs" / "skills_attic" / "retires.json"
    retires.parent.mkdir(parents=True)
    retires.write_text(json.dumps({"_doc": "x", "forge-morte": {"retrait": "2026-10-14"}}), encoding="utf-8")
    monkeypatch.setattr(sync, "CANONICAL_DIR", canon)
    monkeypatch.setattr(sync, "RETIRES", retires)
    monkeypatch.setattr(sync, "MISE_DE_COTE", tmp_path / "mis_de_cote")
    monkeypatch.setattr(sync, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(sync, "_resolve_copilot_dir", lambda: None)
    monkeypatch.setitem(sync.CLI_TARGETS["claude"], "dir", claude)
    # Toutes les AUTRES cibles neutralisees : un test ne doit jamais ecrire dans le vrai
    # ~/.codex/skills ni dans le .agents/skills du depot.
    for autre in ("gemini", "codex", "agents_depot"):
        monkeypatch.setitem(sync.CLI_TARGETS[autre], "dir", None)
    _skill(canon, "forge-vivante")
    _skill(claude, "forge-morte")
    _skill(claude, "forge-nee-cote-cli")
    return {"canon": canon, "claude": claude, "retires": retires, "tmp": tmp_path}


def test_une_skill_retiree_n_est_jamais_rapatriee(poste):
    sources = sync._cli_only_sources()
    assert "forge-morte" not in sources
    assert "forge-nee-cote-cli" in sources  # la consolidation des vraies naissances CLI reste


def test_preview_annonce_la_mise_de_cote_sans_rien_deplacer(poste):
    r = sync.plan_or_apply(apply=False, copy=True, firewall=False)
    assert [(x["cli"], x["slug"]) for x in r["retirees_mises_de_cote"]] == [("claude", "forge-morte")]
    assert (poste["claude"] / "forge-morte" / "SKILL.md").exists()


def test_apply_deplace_la_copie_retiree_et_rollback_la_remet(poste):
    r = sync.plan_or_apply(apply=True, copy=True, firewall=False)
    vers = Path(r["retirees_mises_de_cote"][0]["vers"])
    assert not (poste["claude"] / "forge-morte").exists()
    assert (vers / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: forge-morte")
    assert not (poste["canon"] / "forge-morte").exists()  # ni ressuscitee au canonical
    sync.rollback()
    assert (poste["claude"] / "forge-morte" / "SKILL.md").exists()


def test_un_manifeste_illisible_est_garde_et_dit(poste, capsys):
    (poste["tmp"] / "manifest.json").write_text("{illisible", encoding="utf-8")
    sync.plan_or_apply(apply=True, copy=True, firewall=False)
    assert (poste["tmp"] / "manifest.illisible.json").read_text(encoding="utf-8") == "{illisible"
    assert "manifeste illisible" in capsys.readouterr().err
    assert json.loads((poste["tmp"] / "manifest.json").read_text(encoding="utf-8"))["history"]


def test_un_registre_illisible_leve_au_lieu_de_tout_ressusciter(poste):
    poste["retires"].write_text("{illisible", encoding="utf-8")
    with pytest.raises(ValueError):
        sync._retires()
    with pytest.raises(ValueError):
        sync.plan_or_apply(apply=False, copy=True, firewall=False)


def test_prune_deplace_au_lieu_de_supprimer(poste, monkeypatch):
    monkeypatch.setitem(sync.CLIENT_ONLY, "forge-vivante", ["gemini"])
    _skill(poste["claude"], "forge-vivante")
    r = sync.prune(apply=True)
    assert [x["slug"] for x in r["removed"]] == ["forge-vivante"]
    assert not (poste["claude"] / "forge-vivante").exists()
    assert (Path(r["removed"][0]["vers"]) / "SKILL.md").exists()
    sync.rollback()
    assert (poste["claude"] / "forge-vivante" / "SKILL.md").exists()


def test_prune_ne_touche_jamais_une_skill_externe(poste):
    """Mesure 2026-10-14 : smithery-ai-cli (externe, presente au canonical) sortie par --prune."""
    _skill(poste["canon"], "smithery-ai-cli")
    _skill(poste["claude"], "smithery-ai-cli")
    assert sync.prune(apply=True)["removed"] == []
    assert (poste["claude"] / "smithery-ai-cli" / "SKILL.md").exists()


def test_codex_et_le_depot_recoivent_les_skills_un_cli_absent_rien(poste, monkeypatch):
    """GO owner 14/10 : tous les CLI au meme geste. Un CLI absent du poste : aucun dossier cree."""
    codex = poste["tmp"] / "home" / ".codex" / "skills"
    codex.parent.mkdir(parents=True)
    depot = poste["tmp"] / "depot" / ".agents" / "skills"
    depot.parent.mkdir(parents=True)
    absent = poste["tmp"] / "home" / ".absent" / "skills"
    monkeypatch.setitem(sync.CLI_TARGETS["codex"], "dir", codex)
    monkeypatch.setitem(sync.CLI_TARGETS["agents_depot"], "dir", depot)
    monkeypatch.setitem(sync.CLI_TARGETS["gemini"], "dir", absent)
    r = sync.plan_or_apply(apply=True, copy=True, firewall=False)
    assert (codex / "forge-vivante" / "SKILL.md").exists()
    assert (depot / "forge-vivante" / "SKILL.md").exists()
    assert not absent.parent.exists()
    assert any(s.get("cli") == "gemini" and "introuvable" in s["why"] for s in r["skipped"])


def _git(depot: Path, *args):
    subprocess.run(["git", "-c", "user.name=nr", "-c", "user.email=nr@nr", "-C", str(depot), *args],
                   check=True, capture_output=True, timeout=60)


def test_un_ancien_deploiement_est_rafraichi_une_edition_locale_reste_un_conflit(poste, monkeypatch):
    depot = poste["tmp"] / "depot"
    canon = depot / "docs" / "skills"
    canon.mkdir(parents=True)
    _git(depot, "init", "-q")
    v1 = _skill(canon, "forge-x", "version 1").read_bytes()
    _git(depot, "add", ".")
    _git(depot, "commit", "-q", "-m", "v1")
    _skill(canon, "forge-x", "version 2")
    _git(depot, "commit", "-q", "-am", "v2")
    monkeypatch.setattr(sync, "ROOT", depot)
    monkeypatch.setattr(sync, "CANONICAL_DIR", canon)

    copie = poste["claude"] / "forge-x" / "SKILL.md"
    copie.parent.mkdir(parents=True)
    copie.write_bytes(v1.replace(b"\n", b"\r\n"))  # ancien deploiement, fins de ligne Windows
    assert sync._est_ancien_deploiement("forge-x", copie, {})
    r = sync.plan_or_apply(apply=False, copy=True, firewall=False)
    assert {"cli": "claude", "slug": "forge-x", "action": "REPLACE", "dest": str(copie)} in r["planned"]

    copie.write_bytes(v1 + b"edition locale\n")
    assert not sync._est_ancien_deploiement("forge-x", copie, {})
    r = sync.plan_or_apply(apply=False, copy=True, firewall=False)
    assert not any(p["slug"] == "forge-x" for p in r["planned"])
    assert any(s.get("slug") == "forge-x" and "conflit" in s["why"] for s in r["skipped"])


def test_point_d_entree_preview(poste, monkeypatch):
    # --no-firewall : le firewall ecrit sur stdout quand il est indisponible et casserait le JSON ;
    # il est orthogonal au retrait, le chemin argparse -> plan_or_apply reste celui de l'owner.
    monkeypatch.setattr(sys, "argv", ["forge_skill_sync.py", "--preview", "--no-firewall"])
    tampon = io.StringIO()
    with redirect_stdout(tampon):
        assert sync.main() == 0
    sortie = json.loads(tampon.getvalue())
    assert [x["slug"] for x in sortie["retirees_mises_de_cote"]] == ["forge-morte"]
    assert (poste["claude"] / "forge-morte" / "SKILL.md").exists()


def test_le_registre_reel_ne_retire_aucune_skill_vivante():
    """Une skill retiree qui serait encore au canonical serait deployee ET mise de cote."""
    retirees = set(sync._retires())  # vide depuis l'annulation du 14/10 : la regle tient quand meme
    vivantes = {p.parent.name for p in (ROOT / "docs" / "skills").glob("*/SKILL.md")}
    assert not (retirees & vivantes)


def test_le_registre_reel_se_lit_et_ses_cles_de_doc_ne_retirent_rien():
    """`_doc` et `_historique` sont de la documentation, jamais des skills retirees."""
    assert not any(k.startswith("_") for k in sync._retires())
