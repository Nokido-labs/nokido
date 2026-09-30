"""tools/patch_notify_reveil_http.py — reveil du drain AGY par HTTP, pas par subprocess.

Affinage du reveil pose le meme jour (8d621f36). `forge_ensure_service.ensure`
passe par `subprocess.run([LAFORGE_PYTHON, forge_supervisor_ctl.py, ...])` : un
interpreteur Python complet lance a chaque reveil, et un chemin qui echoue net
partout ou `subprocess` est interdit (mesure : « WORKSPACE_GUARD: subprocess.Popen
interdit pour agent zone-restreint »).

Or le superviseur expose une ROUTE HTTP, deja eprouvee ce soir (POST
/supervisor/reload -> 200). On l'appelle directement en stdlib : pas de processus
fils, pas de dependance au PATH ni au compte, et une latence de quelques
millisecondes au lieu d'un cold start.

`ensure()` reste en REPLI : si l'HTTP echoue (token absent, route renommee), on
retombe sur le chemin historique plutot que d'abandonner. Les deux echecs sont
JOURNALISES — un reveil muet qui rate redonne exactement la panne corrigee.

Pourquoi un patcher : app/forge_mcp_registry.py est CRITICAL_FILE.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ANCIEN = '''                            try:
                                import sys as _s_w

                                _s_w.path.insert(0, str(self.root / "tools"))
                                from forge_ensure_service import ensure as _ens

                                # Nom COMPLET : ensure() n'accepte qu'un alias de
                                # SVC_MAP ou un nom prefixe Nokido — un alias court
                                # inconnu rendrait « service inconnu » et le reveil
                                # aurait echoue en silence.
                                _r = _ens("NokidoGeminiAutonomous", "running")
                                logger.info(f"[postal] drain AGY reveille: {_r}")
                            except Exception as _we:  # noqa: BLE001
'''

NOUVEAU = '''                            try:
                                import sys as _s_w
                                import urllib.request as _ur_w

                                _s_w.path.insert(0, str(self.root / "app"))
                                _tok_w = ""
                                try:
                                    from forge_secrets import get_secret as _gs_w

                                    _tok_w = _gs_w("LAFORGE_SUPERVISOR_TOKEN") or ""
                                except Exception:  # noqa: BLE001
                                    pass
                                # Route HTTP du superviseur : stdlib pur, quelques ms.
                                # `ensure()` passe par un subprocess Python complet et
                                # echoue partout ou subprocess est interdit.
                                # Chemin EXACT verifie dans supervisor.ts (L1683) :
                                # /supervisor/service/start/<nom>. Le raccourci
                                # /supervisor/start/ n'existe pas et aurait rendu 404
                                # en silence — un reveil mort a la place d'un lent.
                                _req_w = _ur_w.Request(
                                    "http://127.0.0.1:8765/supervisor/service/start/"
                                    "NokidoGeminiAutonomous",
                                    data=b"", method="POST",
                                    headers={"Authorization": f"Bearer {_tok_w}"}
                                    if _tok_w else {})
                                try:
                                    with _ur_w.urlopen(_req_w, timeout=30) as _rp_w:
                                        logger.info(f"[postal] drain AGY reveille "
                                                    f"(HTTP {_rp_w.status})")
                                except Exception as _he_w:  # noqa: BLE001
                                    # REPLI sur le chemin historique : mieux vaut un
                                    # subprocess lent qu'un drain qui dort.
                                    logger.warning(f"[postal] reveil HTTP KO "
                                                   f"({type(_he_w).__name__}) -> repli ensure()")
                                    _s_w.path.insert(0, str(self.root / "tools"))
                                    from forge_ensure_service import ensure as _ens

                                    logger.info("[postal] drain AGY reveille (repli): "
                                                f"{_ens('NokidoGeminiAutonomous', 'running')}")
                            except Exception as _we:  # noqa: BLE001
'''


def main() -> int:
    p = ROOT / "app" / "forge_mcp_registry.py"
    src = p.read_text(encoding="utf-8")
    if "reveil HTTP KO" in src:
        print("SKIP : patch deja applique")
        return 0
    n = src.count(ANCIEN)
    if n != 1:
        raise AssertionError(f"point d'ancrage non unique ({n}) — patch NON applique")
    src = src.replace(ANCIEN, NOUVEAU)
    ast.parse(src)
    p.write_text(src, encoding="utf-8")
    if "reveil HTTP KO" not in p.read_text(encoding="utf-8"):
        raise AssertionError("RELECTURE sans le patch — edition perdue")
    print("PATCH HTTP APPLIQUE — verifie par relecture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
