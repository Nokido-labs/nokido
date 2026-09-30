"""NR -- la vue « Memoire du persona » ne promet pas une revocation qu'elle ne fait pas.

Mesure du 2026-09-24 (chantier UI) : le bouton « Oublier » appelait `revoke(i)`, soit
`setMem(mem.filter(...))` -- un masquage LOCAL, sans aucun appel serveur ; l'entree revenait au
rechargement. La vue se disait « visible · editable · revocable ». Decision owner du 25/09 :
renommer en « Masquer » (plutot que brancher une revocation).

Garde, tant que `revoke` reste local : ni les sources (vue, app, constructeur) ni le BUNDLE SERVI
(hub-compiled.js, ce que le navigateur execute) ne promettent « Oublier » ou « revocable ». Le jour
ou `revoke` appelle le serveur, ce test se relache de lui-meme.
"""
from __future__ import annotations

import re
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "design_handoff_nokido" / "ui_kits" / "hub"
FICHIERS = ("hub-views.ref.jsx", "hub-app.jsx", "build-hub.js", "hub-compiled.js")


def _revoke_est_local() -> bool:
    src = (HUB / "hub-views.ref.jsx").read_text(encoding="utf-8")
    m = re.search(r"const revoke\s*=\s*\(i\)\s*=>\s*([^;]+);", src)
    assert m, "definition de revoke introuvable : le lecteur ne voit plus la vue persona"
    return "fetch" not in m.group(1)


def test_le_bouton_dit_ce_qu_il_fait():
    if not _revoke_est_local():
        return  # revocation branchee : la promesse redevient vraie
    for nom in FICHIERS:
        txt = (HUB / nom).read_text(encoding="utf-8", errors="replace")
        for promesse in ("Oublier", "révocable"):
            assert promesse not in txt, "%s promet « %s » alors que revoke ne fait que masquer localement" % (nom, promesse)
    assert "Masquer" in (HUB / "hub-compiled.js").read_text(encoding="utf-8", errors="replace"), \
        "le bundle servi n'a pas ete recompile (tools/forge_ui_hub_rebuild.py --apply)"
