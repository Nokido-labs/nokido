"""Promotion du dist public sur un sha CERTIFIE par la CI de reference.

Usage : dist_promotion.py --version X.Y.Z --sha <sha court certifie> --job <job_id de la CI de reference>
        dist_promotion.py --version X.Y.Z --sha <sha pousse> --repetition
          -> repetition generale (ex C:/tmp/corrections/repetition_installation_2026-10-07.py) : snapshot
             du depot public dans un clone d'essai NEUF, rien pousse ; seule une branche essai/** part
             ensuite, hors de cet outil. Lancee APRES la CI (aucune charge pendant une CI).

Porte en outil versionne le 20/10 (regle owner du 18/10 : rien de reutilisable dans C:/tmp) depuis
C:/tmp/corrections/promotion_dist_0212.py, gardes inchangees :
- certification LUE sur ses artefacts (l'unique ci_proof.json SUITE_COMPLETE dont target_sha ==
  observed_head == sha) ET dans le journal du job (echecs=0, erreurs=0) -- jamais recopiee ;
- fetch + fast-forward STRICT du dist, HEAD == github/main (rien de non publie), tag absent ;
- Knowledge Pack et packs par source construits ici (--with-assets) : :8099 doit repondre.
Apres la promotion : liste des assets, scan du tarball (profil public + marqueurs machine,
comptes seuls, jamais une valeur), version et README du dist.
Cet outil NE POUSSE RIEN. rc=3 = garde, rc=2 = tarball non conforme, sinon rc de forge_dist_publish.
"""
# nokido-compte: en_ligne
# (git fetch vers GitHub ; :8099 reste joignable en boucle locale)
import argparse
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DIST = r"C:/tmp/nokido-dist"
ESSAI = r"C:/tmp/nokido-dist-essai"
LOT = r"C:/tmp/nokido-release"
PREUVES = ROOT / "sandbox/workspace/tmp/nokido_proof"
REGLES = ROOT / ".git-publish-rules.json"
RE_PREUVE = re.compile(r"\[preuve\] sha=(\w+) .*echecs=(\d+) .*erreurs=(\d+) .*etat=(\w+)")
MARQUEURS = re.compile(r"desktop-(?=[a-z0-9]{0,6}\d)[a-z0-9]{7}\b|C:[\\/]+Users[\\/]+user|\bNaarob\b", re.I)


def git(*a, depot=DIST):
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(depot)] + list(a), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def certifications(sha: str, racine: Path = PREUVES) -> list:
    """Dossiers de certification VERTS pour ce sha. Une preuve illisible est ecartee ET dite."""
    certs = []
    for p in sorted(racine.glob("ci-reference-*/artefacts/ci_proof.json")):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print("preuve ILLISIBLE (ecartee, dite) :", p.parent.parent.name, e, flush=True)
            continue
        # 20/10 mesure : target_sha est le sha DEMANDE (court si --sha court) ; la preuve forte est
        # observed_head == sha complet, la cible n'en est qu'un prefixe (>= 7 caracteres).
        cible = str(j.get("target_sha") or "")
        if len(cible) >= 7 and sha.startswith(cible) and j.get("observed_head") == sha \
                and j.get("certification_state") == "SUITE_COMPLETE" and j.get("process_state") == "CAPTURED" \
                and not j.get("incoherences") and not j.get("non_couvert"):
            certs.append(p.parent)
    return certs


def preuve_verte(journal: str, court: str) -> bool:
    """La ligne [preuve] du job dit-elle 0 echec, 0 erreur, SUITE_COMPLETE, pour CE sha ?"""
    m = RE_PREUVE.search(journal)
    return bool(m) and m.group(1).startswith(court) and m.group(2) == "0" and m.group(3) == "0" \
        and m.group(4) == "SUITE_COMPLETE"


def scan_tarball(tgz: str, regles: Path = REGLES) -> dict:
    """Comptes seuls : fichiers sous blocked_paths du profil public, fichiers portant un marqueur machine."""
    bloques = json.loads(regles.read_text(encoding="utf-8"))["profiles"]["public"]["blocked_paths"]
    n, par_motif, marques = 0, {}, []
    with tarfile.open(tgz) as t:
        for m in t:
            if not m.isfile():
                continue
            n += 1
            nom = m.name.split("/", 1)[1] if "/" in m.name else m.name
            motifs = [b for b in bloques
                      if fnmatch.fnmatch(nom, b) or fnmatch.fnmatch(nom, b.rstrip("*").rstrip("/") + "/*")]
            if motifs:
                par_motif[motifs[0]] = par_motif.get(motifs[0], 0) + 1
            if m.size < 5_000_000 and not nom.endswith((".png", ".jpg", ".gz", ".zip", ".woff2", ".db", ".npz")):
                mm = MARQUEURS.search(t.extractfile(m).read().decode("utf-8", "replace"))
                if mm:
                    # chemin + NATURE du marqueur, jamais sa valeur
                    marques.append((nom, "hostname" if mm.group(0).lower().startswith("desktop") else "owner"))
    return {"fichiers": n, "sous_blocked_paths": sum(par_motif.values()), "par_motif": par_motif,
            "marques": marques}


def _forcer(fonction, chemin, _exc):
    # objets git en LECTURE SEULE sous Windows : rmtree laissait un dossier sans .git (07/10)
    os.chmod(chemin, stat.S_IWRITE)
    fonction(chemin)


def repetition(version: str, source: str, essai: str = ESSAI) -> int:
    """Snapshot du depot public dans un clone d'essai NEUF (un main local en avance ferait refuser le ff-only)."""
    if os.path.exists(essai):
        shutil.rmtree(essai, onexc=_forcer)
    if os.path.exists(essai):
        print("GARDE : clone d'essai %s NON supprime, repetition annulee" % essai, flush=True)
        return 3
    r = subprocess.run([PY, "tools/forge_dist_publish.py", "--version", version, "--source", source,
                        "--dist-path", essai], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3000, env=dict(os.environ, PYTHONNOUSERSITE="1"))
    print("promoteur rc=%s (source %s)" % (r.returncode, source), flush=True)
    sortie = [ligne for ligne in ((r.stdout or "") + (r.stderr or "")).splitlines() if "CRLF" not in ligne]
    print("\n".join(ligne for ligne in sortie if ligne.startswith("["))[-6000:], flush=True)
    # ET toute ligne d'erreur : un filtre qui ecarte l'erreur rend l'echec muet
    print("--- erreurs et fin de sortie ---", flush=True)
    print("\n".join([ligne for ligne in sortie
                     if any(k in ligne for k in ("Error", "Traceback", "fatal", "refus", "REFUS", "Exit"))]
                    + sortie[-25:])[-5000:], flush=True)
    print("clone essai :\n" + git("log", "-2", "--format=%h %s", depot=essai)[1], flush=True)
    for f in (".github/workflows/installation-complete.yml", "tools/forge_install_acceptance.py",
              "tools/forge_knowledge_pack_import.py", "distribution/packs/local-llm.toml"):
        print("present dans le snapshot : %-50s %s" % (f, os.path.exists(os.path.join(essai, f))), flush=True)
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--sha", required=True, help="sha court certifie")
    ap.add_argument("--job", help="job_id de la CI de reference (promotion)")
    ap.add_argument("--repetition", action="store_true", help="snapshot d'essai seulement, rien pousse")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        print("GARDE : version non SemVer :", a.version, flush=True)
        return 3
    if a.repetition:
        return repetition(a.version, a.sha)
    if not a.job:
        print("GARDE : --job requis pour une promotion", flush=True)
        return 3

    journal = (ROOT / "sandbox" / "jobs" / ("%s.log" % a.job)).read_text(encoding="utf-8", errors="replace")
    _, sha = git("rev-parse", a.sha, depot=ROOT)
    certs = certifications(sha)
    if len(certs) != 1 or not preuve_verte(journal, a.sha):
        print("GARDE : certification introuvable, ambigue ou non verte :", [c.parent.name for c in certs],
              bool(RE_PREUVE.search(journal)), flush=True)
        return 3
    cert = certs[0]
    print("certification", cert.parent.name, "| sha", sha, flush=True)

    print("fetch :", git("fetch", "github", "+refs/heads/main:refs/remotes/github/main", "--tags")[0], flush=True)
    rc_ff, sortie_ff = git("merge", "--ff-only", "refs/remotes/github/main")
    print("avance fast-forward rc=%s : %s" % (rc_ff, sortie_ff[-200:]), flush=True)
    _, head = git("rev-parse", "HEAD")
    _, distant = git("rev-parse", "refs/remotes/github/main")
    rc_tag, _ = git("rev-parse", "-q", "--verify", "refs/tags/v%s" % a.version)
    print("HEAD", head[:12], "| github/main", distant[:12], "| tag existe :", rc_tag == 0, flush=True)
    if rc_ff or not head or head != distant or rc_tag == 0 or not cert.is_dir():
        print("GARDE : etat inattendu, promotion NON lancee", flush=True)
        return 3

    cmd = [PY, "-u", "tools/forge_dist_publish.py", "--version", a.version, "--branch", sha,
           "--certification", str(cert), "--with-assets"]
    print("CMD", " ".join(cmd[2:]), flush=True)
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace")
    for ligne in p.stdout:
        if "CRLF" not in ligne:
            print(ligne.rstrip(), flush=True)
    rc = p.wait()
    print("PROMOTION rc=%s" % rc, flush=True)
    if rc:
        return rc

    _, d = git("rev-parse", "HEAD")
    _, tag = git("rev-parse", "v%s^{commit}" % a.version)
    print("D", d[:12], "| tag ->", tag[:12], flush=True)
    lot = Path(LOT) / ("v%s" % a.version)
    for f in sorted(lot.glob("*")):
        print("asset %-48s %12d" % (f.name, f.stat().st_size), flush=True)
    s = scan_tarball(str(lot / ("nokido-%s-src.tar.gz" % a.version)))
    for nom, nature in s["marques"]:
        print("  marque :", nom, "|", nature, flush=True)
    print("SCAN fichiers:", s["fichiers"], "| sous blocked_paths:", s["sous_blocked_paths"],
          "| par motif:", sorted(s["par_motif"].items(), key=lambda x: -x[1]),
          "| marques:", len(s["marques"]), flush=True)
    _, pyproj = git("show", "HEAD:pyproject.toml")
    print("version du dist :", [ligne for ligne in pyproj.splitlines() if ligne.startswith("version")][:1], flush=True)
    for chemin in ("README.md", "docs/i18n/README.fr.md"):
        _, t = git("show", "HEAD:%s" % chemin)
        print(chemin, "fuites (prive, ci-selfhosted, ancien) :",
              ("nokido-private" in t, "ci-selfhosted" in t, "user/Nokido" in t), flush=True)
    return 2 if s["sous_blocked_paths"] or s["marques"] else 0


if __name__ == "__main__":
    sys.exit(main())
