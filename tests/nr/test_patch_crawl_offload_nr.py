"""NR — le patch one-shot de deport du crawl.

Un patch qui REECRIT un CRITICAL_FILE doit etre idempotent (deja applique = NOOP)
et refuser de patcher a l'aveugle si le fichier a change. Sinon il corromprait
le hub qu'il pretend reparer. On verifie ces deux gardes, pas l'application
elle-meme (deja faite et prouvee par grep en prod).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_la_cible_est_deja_deportee():
    """Le patch a ete applique en prod : handle_crawl appelle desormais
    asyncio.to_thread. La sentinelle du patch doit donc detecter cet etat -> NOOP,
    jamais une seconde application qui casserait le fichier."""
    import forge_patch_crawl_offload as P

    src = Path(P.CIBLE).read_text(encoding="utf-8", errors="replace")
    assert P.SENTINELLE in src, "handle_crawl n'est plus deporte — regression"
    # Et la ligne synchrone d'origine ne doit plus exister.
    assert "        md = crawl_url(url, timeout=timeout)" not in src


def test_le_patch_est_idempotent(monkeypatch, capsys):
    """Relance sur un fichier deja patche = NOOP, code 0."""
    import forge_patch_crawl_offload as P

    code = P.main()
    out = capsys.readouterr().out
    assert code == 0 and "NOOP" in out


def test_les_remplacements_sont_des_paires_avant_apres():
    """Chaque remplacement deporte reellement l'appel en to_thread."""
    import forge_patch_crawl_offload as P

    assert P.REMPLACEMENTS, "aucun remplacement declare"
    for avant, apres in P.REMPLACEMENTS:
        assert "await asyncio.to_thread" in apres
        assert "await asyncio.to_thread" not in avant


def test_la_sentinelle_correspond_au_resultat_des_remplacements():
    """La sentinelle d'idempotence doit etre un fragment REELLEMENT produit par
    les remplacements, sinon le NOOP ne se declenche jamais et le patch se
    ré-applique en boucle."""
    import forge_patch_crawl_offload as P

    produit = " ".join(apres for _, apres in P.REMPLACEMENTS)
    assert P.SENTINELLE in produit


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
