"""NR -- le keeper demarre LE conteneur crawl4ai de Nokido, pas un homonyme d'image (mesure 2026-11-10).

Apres la MAJ 0.9.4, `ps -a --filter ancestor=unclecode/crawl4ai` (= :latest) ne voyait plus laforge-crawl4ai-1 et
rendait `sweb_dood13` (0.8.6, cree le 22/05, aucun port publie) : demarre a 13:49:26Z, la seconde du reveil par
forge_crawl_tool. Contrat : selection par les LABELS compose (projet + service), jamais par l'image.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_docker_keeper as K  # noqa: E402


def test_selection_par_labels_compose(monkeypatch, tmp_path):
    vus = []

    def _cli(args):
        vus.append(args)
        if args[:2] == ["ps", "-a"]:
            return 0, "laforge-crawl4ai-1\n"
        if args[:1] == ["inspect"]:
            return 0, "sha256:neuf"
        return 0, ""

    monkeypatch.setattr(K, "_docker_cli", _cli)
    monkeypatch.setattr(K, "_crawl4ai_voulu", lambda: True)
    monkeypatch.setattr(K, "CRAWL4AI_EPINGLE", tmp_path / "epingle.json")
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    K._STATE["last_crawl4ai_start_ts"] = 0.0
    d = K._demarrer_crawl4ai(10_000.0)
    ps = next(a for a in vus if a[:2] == ["ps", "-a"])
    assert "label=com.docker.compose.service=crawl4ai" in ps
    assert "label=com.docker.compose.project=%s" % K.CRAWL4AI_PROJET in ps
    assert not any(str(x).startswith("ancestor=") for x in ps)
    assert ["start", "laforge-crawl4ai-1"] in vus and d["conteneur"] == "laforge-crawl4ai-1"
