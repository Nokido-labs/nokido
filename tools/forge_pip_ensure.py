"""forge_pip_ensure.py — installe un paquet manquant dans un env Python cible.

Contexte : les runs DÉTACHÉS (sandbox) strippent le user-site (PYTHONNOUSERSITE),
donc un dep présent seulement en user-site (ex: greenlet pour playwright) manque.
Fix durable = l'installer dans le site-packages de l'ENV. subprocess.Popen est
bloqué en sandbox (WORKSPACE_GUARD) -> lancer PRIVILÉGIÉ :
  hub run action=trusted_script path=tools/forge_pip_ensure.py script_args="greenlet"
"""

__FORGE_COLOR__ = "infra/bootstrap : installe un paquet manquant dans un env Python cible"  # organe declare le 2026-09-06 (audit de raccordement)
import subprocess
import sys

DEFAULT_PY = r"%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe"


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("usage: forge_pip_ensure.py <package> [env_python]")
        return 2
    pkg = sys.argv[1].strip()
    py = sys.argv[2].strip() if len(sys.argv) > 2 else DEFAULT_PY
    r = subprocess.run(
        [py, "-m", "pip", "install", pkg],
        capture_output=True, text=True, errors="replace", timeout=180,
    )
    print("RC", r.returncode)
    print(r.stdout[-1500:])
    print("ERR", r.stderr[-800:])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
