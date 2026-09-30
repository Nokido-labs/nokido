"""
test_nokido_headless_nr.py — Test headless de Nokido sans Textual
====================================================================
Lance Nokido en mode --test-boot qui :
1. Exécute on_mount() sans ouvrir la fenêtre
2. Vérifie le retour de fonctions clés
3. Écrit les résultats dans sandbox/boot_test_result.json
4. Exit 0 si OK, 1 si erreur

Usage :
  python app/LaForge.py --test-boot
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (boot complet) (l.35)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT_P  = Path(__file__).resolve().parent.parent.parent
APP_DIR = ROOT_P / "app"


class TestNokidoHeadless:
    """Lance Nokido en mode headless et vérifie les retours."""

    def test_boot_headless(self):
        """
        Lance Nokido --test-boot dans un subprocess.
        Vérifie que le boot complet se passe sans erreur.
        """
        result_path = ROOT_P / "sandbox" / "boot_test_result.json"
        result_path.unlink(missing_ok=True)

        r = subprocess.run(
            [sys.executable, str(APP_DIR / "Nokido.py"), "--test-boot"],
            capture_output=True, text=True,
            timeout=30,
            cwd=str(ROOT_P),
        )

        # Vérifier pas de crash
        assert r.returncode == 0, (
            f"Nokido --test-boot a crashé (rc={r.returncode}):\n"
            f"STDOUT: {r.stdout[-500:]}\n"
            f"STDERR: {r.stderr[-500:]}"
        )

        # Lire le résultat JSON
        assert result_path.exists(), "boot_test_result.json non généré"
        result = json.loads(result_path.read_text(encoding="utf-8"))

        # Vérifier les checks canari
        canary = result.get("canary", {})
        assert canary.get("ok"), (
            f"Canari échoué:\n" + "\n".join(canary.get("errors", []))
        )

        # Vérifier les fonctions testées
        fn_results = result.get("function_tests", {})
        failed = [k for k, v in fn_results.items() if not v.get("ok")]
        assert not failed, (
            f"Fonctions en échec: {failed}\n"
            + "\n".join(f"{k}: {fn_results[k]}" for k in failed)
        )
