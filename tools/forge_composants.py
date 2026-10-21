"""forge_composants -- pose sur CETTE machine les composants natifs EPINGLES (distribution/packs/local-llm.toml).

Pourquoi un outil du produit (2026-10-09) : jusqu'ici seul le banc de mesure (tools/forge_install_acceptance.py)
savait telecharger, verifier et poser llama.cpp, Qdrant, Caddy et Ollama ; nokido-doctor ne faisait que les nommer
(« build epinglee a extraire dans runtime/ »). Une installation en une commande ne peut pas reposer sur un banc de
test : le banc appelle desormais CET outil, et mesure donc le produit. Rien n'est invente : chaque archive est
refusee si sa somme sha256 ou sa taille differe du manifeste.

Emplacements standard (ceux que nokido-doctor --ecrire-vars et services.toml attendent) :
  llama.cpp -> runtime/llama          Qdrant -> runtime/qdrant         Ollama -> runtime/ollama
  Caddy     -> sandbox/caddy[.exe] (+ certificat local et Caddyfile par les outils du produit)
  dispatcher Go -> go_services/forge_dispatcher/forge_dispatcher[.exe], construit avec le Go du PATH s'il existe,
                   sinon le toolchain epingle (runtime/go) ; module sans dependance, construction reproductible.

GARDE CHIFFREMENT AT-REST (decision owner du 2026-10-20). Avant TOUT poseur, l'outil verifie que VeraCrypt ou
cryptsetup est installe OU qu'un refus a deja ete consigne. Sans les deux : rc 2, rien de pose, et le message nomme
`--sans-chiffrement`. Avec ce drapeau, le refus est ECRIT (date, compte, motif via --motif-refus) puis l'installation
continue — c'est une decision de l'utilisateur, pas un silence. `--desinstaller` n'est jamais bloque : on ne refuse
pas de rendre ce qui existe deja.

   LAFORGE_PYTHON tools/forge_composants.py --tout
   LAFORGE_PYTHON tools/forge_composants.py --composant caddy --composant dispatcher
   LAFORGE_PYTHON tools/forge_composants.py --tout --sans-chiffrement --motif-refus "disque chiffre par le BIOS"
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/config : pose les composants natifs epingles (llama.cpp, Qdrant, Caddy, Ollama, dispatcher Go)"

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIN = os.name == "nt"
EXE = ".exe" if WIN else ""
DL = ROOT / "runtime" / "dl"
COMPOSANTS = ("deno", "llama", "qdrant", "caddy", "ollama", "dispatcher", "modeles", "connaissances", "jetons")

_PREREQUIS = None


def prerequis():
    """Registre des prerequis externes (app/forge_install_prerequis.py), charge une fois par son chemin.

    C'est LUI qui sonde VeraCrypt/cryptsetup (mesure a trois etats) et qui range la fiche de refus : un seul endroit
    connait ces deux etats — ni copie ici, ni second fichier.
    """
    global _PREREQUIS
    if _PREREQUIS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("forge_install_prerequis",
                                                      ROOT / "app" / "forge_install_prerequis.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _PREREQUIS = m
    return _PREREQUIS


def chiffrement_present() -> bool:
    """VeraCrypt / cryptsetup INSTALLES ici ? Seul PRESENT prouve ; un refus consigne compte pour le passeur."""
    m = prerequis()
    entree = next(e for e in m.PREREQUIS if e["cle"] == "chiffrement_at_rest")
    etat, _ = m._sonde_binaire(tuple(entree["binaires"]), tuple(entree.get("chemins_usuels", ())))
    return etat == m.PRESENT


def refus_chiffrement() -> dict | None:
    """Le refus du chiffrement at-rest deja consigne (fiche date/compte/motif), ou None."""
    return prerequis().refus_chiffrement()


def consigner_refus_chiffrement(motif: str):
    """Ecrit la fiche du refus explicite — appele UNIQUEMENT derriere `--sans-chiffrement`."""
    return prerequis().consigner_refus_chiffrement(motif)


def plateforme() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    return ("windows" if WIN else "linux") + "-x64"


def composant(cid: str, pack: str = "local-llm") -> dict:
    with open(ROOT / "distribution" / "packs" / ("%s.toml" % pack), "rb") as fh:
        for c in tomllib.load(fh).get("composant", []):
            if c.get("id") == cid:
                return c
    raise LookupError("%s absent de %s.toml (non epingle)" % (cid, pack))


def telecharger(c: dict, dossier: Path = DL) -> Path:
    """Telecharge (en flux, sur disque) puis REFUSE toute somme ou taille differente du manifeste."""
    dest = dossier / Path(c["url"]).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest.is_file() and dest.stat().st_size == c["taille"]):
        urllib.request.urlretrieve(c["url"], dest)
    h = hashlib.sha256()
    with open(dest, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    if h.hexdigest() != c["sha256"] or dest.stat().st_size != c["taille"]:
        dest.unlink(missing_ok=True)
        raise ValueError("somme ou taille FAUSSE pour %s (refus, archive effacee)" % c["id"])
    return dest


def sh(cmd: list, timeout: int = 600, cwd=None, env=None) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, cwd=cwd,
                           env=None if env is None else dict(os.environ, **env))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "%s: %s" % (type(e).__name__, e)


def extraire(arch: Path, cible: Path) -> None:
    """zip ; tar.gz/tgz (tarfile, filtre `data`) ; tar.zst (tar du systeme : Python 3.12 n'a pas zstd)."""
    cible.mkdir(parents=True, exist_ok=True)
    if arch.suffix == ".zip":
        zipfile.ZipFile(arch).extractall(cible)
    elif arch.name.endswith(".tar.zst"):
        rc, out = sh(["tar", "--zstd", "-xf", str(arch), "-C", str(cible)], timeout=1800)
        if rc:
            raise RuntimeError("tar --zstd : %s" % out[-400:])
    else:
        with tarfile.open(arch) as t:
            t.extractall(cible, filter="data")


def _executable(p: Path) -> None:
    if not WIN:
        p.chmod(0o755)


def poser_llama(dl: Path = DL) -> tuple:
    c = composant("llama-server-%s-cpu" % plateforme())
    extrait = dl / "llama_extrait"
    extraire(telecharger(c, dl), extrait)
    trouve = next(extrait.rglob("llama-server" + EXE), None)
    if not trouve:
        return False, "llama-server absent de l'archive"
    cible = ROOT / "runtime" / "llama"
    shutil.copytree(trouve.parent, cible, dirs_exist_ok=True)
    if not WIN:
        for p in cible.iterdir():
            p.chmod(0o755)
    exe = cible / trouve.name
    rc, out = sh([str(exe), "--version"], timeout=60, cwd=exe.parent)
    return rc == 0, {"binaire": str(exe), "version": out.strip()[-300:]}


def poser_qdrant(dl: Path = DL) -> tuple:
    cible = ROOT / "runtime" / "qdrant"
    extraire(telecharger(composant("qdrant-%s" % plateforme()), dl), cible)
    exe = cible / ("qdrant" + EXE)
    if not exe.is_file():
        return False, "binaire absent de l'archive : %s" % sorted(p.name for p in cible.iterdir())[:20]
    _executable(exe)
    rc, out = sh([str(exe), "--version"], timeout=60, cwd=cible)
    return rc == 0, out.strip()[-300:]


def poser_caddy(dl: Path = DL) -> tuple:
    """Binaire dans sandbox/ (ou l'attendent services.toml et forge_tls_caddy), puis les OUTILS du produit :
    certificat local (forge_gen_tls_cert) et Caddyfile en loopback (forge_tls_caddy --write-config)."""
    extrait = dl / "caddy_extrait"
    extraire(telecharger(composant("caddy-%s" % plateforme()), dl), extrait)
    trouve = next(extrait.rglob("caddy" + EXE), None)
    if not trouve:
        return False, "caddy%s absent de l'archive" % EXE
    exe = ROOT / "sandbox" / ("caddy" + EXE)
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(trouve, exe)
    _executable(exe)
    rc_c, out_c = sh([sys.executable, "tools/forge_gen_tls_cert.py"], timeout=120, cwd=ROOT)
    rc_w, out_w = sh([sys.executable, "tools/forge_tls_caddy.py", "--write-config"], timeout=60, cwd=ROOT)
    rc_v, out_v = sh([str(exe), "version"], timeout=60)
    ok = rc_c == 0 and rc_w == 0 and rc_v == 0
    return ok, {"version": out_v.strip()[-120:], "certificat_rc": rc_c, "caddyfile_rc": rc_w,
                "detail": (out_c + out_w)[-400:] if not ok else ""}


def poser_ollama(dl: Path = DL) -> tuple:
    cible = ROOT / "runtime" / "ollama"
    extraire(telecharger(composant("ollama-%s" % plateforme()), dl), cible)
    nom = "ollama" + EXE
    exe = next((p for p in (cible / nom, cible / "bin" / nom) if p.is_file()), None) or next(cible.rglob(nom), None)
    if not exe:
        return False, "%s absent de l'archive" % nom
    _executable(exe)
    rc, out = sh([str(exe), "--version"], timeout=60)
    return rc == 0, {"binaire": str(exe.relative_to(ROOT)), "version": out.strip()[-160:]}


def _go(dl: Path = DL) -> tuple:
    """Le Go du PATH s'il existe, sinon le toolchain epingle extrait dans runtime/go. Rend (chemin, provenance)."""
    trouve = shutil.which("go")
    if trouve:
        return trouve, "PATH"
    exe = ROOT / "runtime" / "go" / "bin" / ("go" + EXE)
    if not exe.is_file():
        extraire(telecharger(composant("go-toolchain-%s" % plateforme()), dl), ROOT / "runtime")
    return str(exe), "toolchain epingle (runtime/go)"


def construire_dispatcher(dl: Path = DL) -> tuple:
    """Construit go_services/forge_dispatcher (module SANS dependance) : -trimpath et -buildvcs=false rendent la
    construction reproductible et independante du proprietaire du depot (git « dubious ownership », 2026-09-18)."""
    src = ROOT / "go_services" / "forge_dispatcher"
    sortie = src / ("forge_dispatcher" + EXE)
    go, provenance = _go(dl)
    env = {"GOCACHE": str(ROOT / "sandbox" / "gocache"), "CGO_ENABLED": "0"}
    rc, out = sh([go, "build", "-trimpath", "-buildvcs=false", "-o", str(sortie), "."], timeout=900, cwd=src, env=env)
    ok = rc == 0 and sortie.is_file()
    return ok, {"go": provenance, "binaire": str(sortie.relative_to(ROOT)) if ok else None,
                "detail": "" if ok else out[-600:]}


def poser_deno(dl: Path = DL) -> tuple:
    """Deno epingle (superviseur de l'organisme) a son emplacement STANDARD, ~/.deno/bin -- celui de l'installeur
    officiel, ou nokido-doctor et --ecrire-vars le cherchent deja. Un deno deja present n'est pas remplace."""
    present = shutil.which("deno")
    cible = Path.home() / ".deno" / "bin"
    exe = Path(present) if present else cible / ("deno" + EXE)
    if not exe.is_file():
        extraire(telecharger(composant("deno-%s" % plateforme()), dl), cible)
    if not exe.is_file():
        return False, "binaire absent de l'archive : %s" % sorted(p.name for p in cible.iterdir())[:20]
    _executable(exe)
    rc, out = sh([str(exe), "--version"], timeout=60)
    return rc == 0, "%s%s" % ("deja present, " if present else "", out.strip()[-200:])


MODELES = ("bge-m3-Q8_0.gguf", "bge-reranker-v2-m3-Q8_0.gguf")


def poser_modeles(dl: Path = DL) -> tuple:
    """Les modeles de poids EPINGLES (embedder :8099, reranking), la ou nokido-doctor et services.toml les
    attendent. Jusqu'au 13/10 seul le banc de mesure savait les poser : un utilisateur pip n'avait aucune commande."""
    cible = ROOT / "data" / "llm_models"
    poses = []
    for cid in MODELES:
        c = composant(cid)
        if Path(c["url"].split("?", 1)[0]).name != cid:
            return False, "l'URL de %s ne finit pas par son nom : %s" % (cid, c["url"][-90:])
        telecharger(c, cible)
        poses.append(cid)
    return True, "sommes verifiees, poses dans %s : %s" % (cible, poses)


def poser_connaissances(dl: Path = DL) -> tuple:
    """Le Knowledge Pack (fragments PROUVES publics, vecteurs bge-m3 precalcules) dans la base RAG. Owner 13/10 :
    « certains elements du RAG doivent etre presents via l'installeur ». Schema d'abord (forge_db_bootstrap),
    puis import depuis la release publique (la derniere, ou NOKIDO_PACK_VERSION). Juge sur « inserted », pas sur rc."""
    rc, out = sh([sys.executable, str(ROOT / "tools" / "forge_db_bootstrap.py")], timeout=900, cwd=ROOT)
    if rc:
        return False, "schema de la base : %s" % out[-500:]
    # Pack CANDIDAT (owner 16/10 : livrables 3 OS fonctionnels E2E) : la repetition importe le fichier de la release
    # BROUILLON, recupere par le workflow, et non une release publiee -- 0.20.12 a ete essayee avec le pack 0.20.9.
    fichier = os.environ.get("NOKIDO_PACK_FICHIER", "")
    imp = [sys.executable, str(ROOT / "tools" / "forge_knowledge_pack_import.py")]
    if fichier:
        if not Path(fichier).is_file():
            return False, "pack candidat ABSENT : NOKIDO_PACK_FICHIER=%s" % fichier
        sha = os.environ.get("NOKIDO_PACK_SHA256", "")
        rc, out = sh(imp + ["--from", fichier] + (["--expect-sha256", sha] if sha else []), timeout=1800, cwd=ROOT)
        return rc == 0 and '"inserted"' in out, "pack CANDIDAT %s : %s" % (Path(fichier).name, out[-560:])
    version = os.environ.get("NOKIDO_PACK_VERSION", "")
    rc, out = sh(imp + ["--download"] + (["--version", version] if version else []), timeout=1800, cwd=ROOT)
    return rc == 0 and '"inserted"' in out, out[-600:]


# Decision owner 13/10 : l'humain d'une installation neuve recoit une identite EXISTANTE de rang 2 (ask exige 2 ; un
# appelant anonyme local est au rang 3). Rien ne s'ouvre aux anonymes.
AGENT_LOCAL = "EDITOR"


def poser_jetons(dl: Path = DL) -> tuple:
    """Le jeton DERIVE du premier client humain (FORGE_TOKEN_EDITOR) seme au coffre s'il manque : jamais ecrase,
    jamais affiche, relu sans sortir du processus. Le CLI `nokido` le presente lui-meme : l'utilisateur n'a aucun
    jeton a copier. Le hub lit les jetons a son DEMARRAGE : semer avant de le lancer."""
    # --from-registre : EDITOR vit dans config/agent_identities.json, PAS dans la liste figee du generateur. Sans lui,
    # le semis rendait rc 0 en ne posant RIEN (« AGENT(S) NON TROUVE(S) ») -- parcours paquet 3 OS du 13/10.
    seme = [sys.executable, str(ROOT / "tools" / "forge_vault_seed_agent_tokens.py"),
            "--generate-missing", "--from-registre", "--agents", AGENT_LOCAL]
    rc, out = sh(seme, timeout=180, cwd=ROOT)
    relu = "from nokido_agent.app.forge_secrets import get_secret as g; import sys; sys.exit(0 if g(%r) else 3)" % (
        "FORGE_TOKEN_" + AGENT_LOCAL)
    rc2, _ = sh([sys.executable, "-c", relu], timeout=120, cwd=ROOT)
    etat = {0: "PRESENT", 3: "ABSENT"}.get(rc2, "ILLISIBLE (rc %s)" % rc2)
    return rc == 0 and rc2 == 0, "semis rc %s ; jeton %s %s ; %s" % (rc, AGENT_LOCAL, etat, out[-240:])


POSEURS = {"llama": poser_llama, "qdrant": poser_qdrant, "caddy": poser_caddy, "ollama": poser_ollama,
           "dispatcher": construire_dispatcher, "modeles": poser_modeles, "connaissances": poser_connaissances,
           "deno": poser_deno, "jetons": poser_jetons}


def desinstaller(purger: bool = False) -> int:
    """Avant `pip uninstall` (README) : retire les liens de donnees du paquet et ce que l'installeur a CONSTRUIT dans
    son dossier (binaire du dispatcher) ; `purger` efface aussi les donnees de l'utilisateur. Refuse dans un clone :
    le poste de developpement n'a rien a desinstaller."""
    from nokido_agent.app.forge_db_path import _installe, retirer_donnees

    if not _installe(ROOT):
        print("clone de developpement (%s) : rien a desinstaller" % ROOT)
        return 2
    construit = ROOT / "go_services" / "forge_dispatcher" / ("forge_dispatcher" + EXE)
    if construit.is_file():
        construit.unlink()
        print("  dispatcher  binaire construit retire")
    fait = retirer_donnees(ROOT, purger=purger)
    for cle, valeur in fait.items():
        print("  %-11s %s" % (cle, valeur))
    rate = [v for v in fait.values() if str(v).startswith(("ECHEC", "REFUSEE", "PARTIELLE"))]
    return 1 if rate else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tout", action="store_true", help="tous les composants de cette plateforme")
    ap.add_argument("--composant", action="append", choices=COMPOSANTS, default=[])
    ap.add_argument("--desinstaller", action="store_true",
                    help="avant `pip uninstall` : retire les liens de donnees et les binaires construits dans le paquet")
    ap.add_argument("--purger", action="store_true", help="avec --desinstaller : efface aussi les donnees de l'utilisateur")
    ap.add_argument("--sans-chiffrement", action="store_true",
                    help="refus EXPLICITE du chiffrement at-rest : la decision est consignee (date, compte, motif) "
                         "puis l'installation continue")
    ap.add_argument("--motif-refus", default="",
                    help="motif du refus, ecrit avec --sans-chiffrement : un refus sans raison ecrite n'est pas une "
                         "decision")
    a = ap.parse_args(argv)
    if a.desinstaller:
        return desinstaller(a.purger)
    if a.purger:
        ap.error("--purger s'emploie avec --desinstaller")
    noms = list(COMPOSANTS) if a.tout else a.composant
    if not noms:
        ap.error("--tout ou --composant")
    print("plateforme : %s" % plateforme())
    # Garde chiffrement at-rest (decision owner 20/10) : TOUJOURS avant le premier poseur — un composant pose en
    # clair apres un autre n'est deja plus corrigeable proprement. La desinstallation n'est jamais soumise a la garde.
    fiche_refus = refus_chiffrement()
    if not chiffrement_present() and not fiche_refus:
        if not a.sans_chiffrement:
            print("chiffrement at-rest ABSENT (VeraCrypt ou cryptsetup) et aucun refus consigne : installation "
                  "ARRETEE avant tout poseur. Installez VeraCrypt (windows/macos) ou cryptsetup (linux), ou "
                  "prononcez un refus explicite avec --sans-chiffrement (il sera consigne : date, compte, motif).",
                  file=sys.stderr)
            return 2
        consigner_refus_chiffrement(a.motif_refus or "refus explicite (--sans-chiffrement)")
    elif fiche_refus:
        print("refus du chiffrement at-rest DEJA CONSIGNE (motif : %s, le %s) : il reste visible dans le bilan, "
              "ici on pose." % (fiche_refus.get("motif"), fiche_refus.get("date")))
    rc = 0
    for nom in noms:
        try:
            ok, detail = POSEURS[nom]()
        except Exception as e:  # noqa: BLE001 -- un composant en echec est DIT, les autres continuent
            ok, detail = False, "%s: %s" % (type(e).__name__, str(e)[:300])
        print("  %-11s %s  %s" % (nom, "OK" if ok else "ECHEC", str(detail)[:300]))
        rc = rc or (0 if ok else 1)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
