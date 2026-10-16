#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_lean_provision -- Nokido installe LUI-MEME sa chaine Lean, dans son arborescence, a la version epinglee.

Owner 15/10 : « personnaliser l'install de Lean pour le mettre dans notre repertoire de travail -- comment vas-tu
pouvoir l'inclure dans Nokido private et public sinon ? ». Installee dans le profil de l'owner (~/.elan), la chaine
etait illisible par les comptes du hub et de la CI (« Acces refuse », mesure du 15/10) et absente de toute
distribution. Ici :

  - le DEPOT porte la version (`formel/lean-toolchain`), jamais les binaires (~600 Mo, retelechargeables) ;
  - ELAN_HOME = `runtime/elan/` : la convention des builds tierces EPINGLEES de Nokido (runtime/llama,
    runtime/ollama, runtime/qdrant), deja ignoree par git, deja sondee par forge_install_prerequis, lisible par
    les comptes du hub par heritage ; l'installeur de l'organisme complet (prive et public) appelle cet outil ;
  - elan est EPINGLE (v4.2.4, depuis les publications officielles leanprover/elan), lance sans toucher au PATH
    (`--no-modify-path`), avec la chaine du depot comme chaine par defaut ; Windows, Linux, macOS ;
  - idempotent : une chaine deja presente et conforme n'est pas retelechargee ; le resultat est VERIFIE
    (`lean --version` == version epinglee), jamais suppose.

Usage : run action=run_job script=tools/forge_lean_provision.py online=true   (rc 0 si la chaine est conforme)
"""
# nokido-compte: owner  -- telechargement + ecriture dans runtime/elan : aucun compte du hub n'a les deux (15/10)
from __future__ import annotations

__FORGE_COLOR__ = "infra/runtime_tiers : chaine Lean epinglee dans runtime/elan, installee et verifiee par Nokido"

import io
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELAN_HOME = ROOT / "runtime" / "elan"
ELAN_VERSION = "v4.2.4"
_URL = "https://github.com/leanprover/elan/releases/download/%s/%s"


def chaine_epinglee(projet: Path = ROOT / "formel") -> str:
    """La chaine que le depot exige (`leanprover/lean4:v4.35.0`)."""
    return (projet / "lean-toolchain").read_text(encoding="utf-8").strip()


def archive_elan(systeme: str | None = None, machine: str | None = None) -> str:
    """Nom de l'archive officielle d'elan pour cette machine. Plateforme inconnue -> leve, jamais une devinette."""
    systeme = (systeme or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(machine)
    if arch is None:
        raise RuntimeError("architecture non prise en charge : %s" % machine)
    if systeme == "windows":
        return "elan-%s-pc-windows-msvc.zip" % arch
    if systeme == "linux":
        return "elan-%s-unknown-linux-gnu.tar.gz" % arch
    if systeme == "darwin":
        return "elan-%s-apple-darwin.tar.gz" % arch
    raise RuntimeError("systeme non pris en charge : %s" % systeme)


def _bin(nom: str, home: Path = ELAN_HOME) -> Path:
    return home / "bin" / (nom + (".exe" if os.name == "nt" else ""))


def env_lean(home: Path = ELAN_HOME) -> dict:
    """Environnement d'un sous-processus Lean : les raccourcis d'elan trouvent leurs chaines par ELAN_HOME."""
    env = dict(os.environ)
    env["ELAN_HOME"] = str(home)
    env["PATH"] = str(home / "bin") + os.pathsep + env.get("PATH", "")
    return env


def version_installee(home: Path = ELAN_HOME, lancer=None) -> str | None:
    """`lean --version` de la chaine installee ici, ou None (absente, inexecutable)."""
    lancer = lancer or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                                   timeout=300, env=env_lean(home)))
    if not _bin("lean", home).exists():
        return None
    try:
        r = lancer([str(_bin("lean", home)), "--version"])
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout or "").strip() if r.returncode == 0 else None


def conforme(version: str | None, chaine: str) -> bool:
    """`leanprover/lean4:v4.35.0` est conforme a « Lean (version 4.35.0, ...) »."""
    return bool(version) and ("version %s," % chaine.rsplit(":v", 1)[-1]) in version


def installer(home: Path = ELAN_HOME, telecharger=None, executer=None) -> dict:
    """Installe elan epingle puis la chaine du depot, sans toucher au PATH. Idempotent ; resultat verifie."""
    chaine = chaine_epinglee()
    deja = version_installee(home)
    if conforme(deja, chaine):
        return {"etat": "CONFORME", "deja_installee": True, "version": deja, "elan_home": str(home)}
    archive = archive_elan()
    telecharger = telecharger or (lambda url: urllib.request.urlopen(url, timeout=600).read())
    executer = executer or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                                       timeout=3600, env=env_lean(home)))
    donnees = telecharger(_URL % (ELAN_VERSION, archive))
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="elan_init_") as tmp:
        if archive.endswith(".zip"):
            zipfile.ZipFile(io.BytesIO(donnees)).extractall(tmp)
        else:
            with tarfile.open(fileobj=io.BytesIO(donnees), mode="r:gz") as t:
                t.extractall(tmp, filter="data")
        init = next((p for p in Path(tmp).rglob("elan-init*") if p.is_file()), None)
        if init is None:
            return {"etat": "ECHEC", "raison": "elan-init absent de l'archive %s" % archive}
        if os.name != "nt":
            init.chmod(0o755)
        r = executer([str(init), "-y", "--no-modify-path", "--default-toolchain", chaine])
    apres = version_installee(home)
    if not conforme(apres, chaine):
        return {"etat": "ECHEC", "raison": "chaine non conforme apres installation (%r)" % apres,
                "sortie": ((r.stdout or "") + (r.stderr or ""))[-800:]}
    return {"etat": "CONFORME", "deja_installee": False, "version": apres, "elan_home": str(home)}


def main() -> int:
    r = installer()
    print("[lean-provision] %s -- %s" % (r["etat"], r.get("version") or r.get("raison")))
    print("[lean-provision] ELAN_HOME = %s" % ELAN_HOME)
    return 0 if r["etat"] == "CONFORME" else 1


if __name__ == "__main__":
    raise SystemExit(main())
