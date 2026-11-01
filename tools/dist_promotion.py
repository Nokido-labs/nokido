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
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
PY = sys.executable
DIST = r"C:/tmp/nokido-dist"
ESSAI = r"C:/tmp/nokido-dist-essai"
LOT = r"C:/tmp/nokido-release"
PREUVES = _RACINE_DONNEES / "sandbox/workspace/tmp/nokido_proof"
REGLES = ROOT / ".git-publish-rules.json"
RE_PREUVE = re.compile(r"\[preuve\] sha=(\w+) .*echecs=(\d+) .*erreurs=(\d+) .*etat=(\w+)")
MARQUEURS = re.compile(r"desktop-(?=[a-z0-9]{0,6}\d)[a-z0-9]{7}\b|C:[\\/]+Users[\\/]+user|\bNaarob\b", re.I)
MANIFESTES_LIVRES = (
    "requirements.txt",
    "requirements-organisme.txt",
    "requirements-ci.lock",
    "requirements.nokido_py314.lock",
)


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


def certifications_pour(sha: str, herite_de=None, racine: Path = PREUVES, depot: Path = ROOT) -> tuple:
    """(certs, raison, sha_preuve). Sans `herite_de` : la preuve du sha EXACT. Avec : celle de l'ancetre certifie,
    si l'ecart ne touche que version / CHANGELOG / workflows (forge_dist_publish.heritage_de_preuve, decision owner
    21/10) ; sinon aucune, raison DITE. NR test_certification_heritee_diff_restreint_nr."""
    if not herite_de:
        return certifications(sha, racine), "", sha
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_dist_publish_herit", ROOT / "tools" / "forge_dist_publish.py")
    fdp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fdp)
    ok, raison, _fichiers = fdp.heritage_de_preuve(depot, herite_de, sha)
    return (certifications(herite_de, racine), "", herite_de) if ok else ([], raison, herite_de)


def verdict_audit(rapports: dict) -> dict:
    """Verdict de conformite des manifestes livres selon la regle du tag (release.yml)."""
    bloquants, avertis, illisibles = [], [], []
    r = rapports if isinstance(rapports, dict) else {}
    for f in MANIFESTES_LIVRES:
        if f not in r or r[f] is None or not isinstance(r[f], dict):
            illisibles.append(f)
            continue
        rapport = r[f]
        for dep in (rapport.get("dependencies") or []):
            if not isinstance(dep, dict):
                continue
            nom = dep.get("name")
            version = dep.get("version")
            for v in (dep.get("vulns") or []):
                if not isinstance(v, dict):
                    continue
                vid = v.get("id")
                ligne = "%s %s %s (%s)" % (nom, version, vid, f)
                if v.get("fix_versions"):
                    bloquants.append(ligne)
                else:
                    avertis.append(ligne)
    return {
        "ok": not bloquants and not illisibles,
        "bloquants": bloquants,
        "avertis": avertis,
        "illisibles": illisibles,
    }


def auditer_snapshot(snapshot, executer=subprocess.run, rapports_sortie=None) -> dict:
    """Lance pip-audit sur chaque manifeste livre present dans le snapshot."""
    racine = Path(snapshot)
    rapports = {} if rapports_sortie is None else rapports_sortie
    with tempfile.TemporaryDirectory() as td:
        for f in MANIFESTES_LIVRES:
            chemin = racine / f
            if not chemin.is_file():
                rapports[f] = None
                continue
            sortie_json = Path(td) / ("%s.json" % f)
            # 25/10 : le compte des jobs a pour HOME le profil Default -- pip-audit y creait son cache et mourait en
            # PermissionError (WinError 5), les 4 manifestes sortaient ILLISIBLES sans dire pourquoi.
            cmd = [
                sys.executable,
                "-m",
                "pip_audit",
                "--no-deps",
                "--disable-pip",
                "--cache-dir",
                str(Path(td) / "cache"),
                "--progress-spinner",
                "off",
                "-r",
                str(chemin),
                "-f",
                "json",
                "-o",
                str(sortie_json),
            ]
            try:
                res = executer(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                )
            except Exception as e:  # noqa: BLE001 -- dit : un audit qui n'a pas tourne n'est pas un audit vide
                print("audit %s : pip-audit NON lance (%s: %s)" % (f, type(e).__name__, str(e)[:200]), flush=True)
                rapports[f] = None
                continue
            if not sortie_json.is_file():
                # Une source qui se tait ne prouve rien : rc et fin de stderr, pour qu'ILLISIBLE dise POURQUOI.
                _err = (getattr(res, "stderr", "") or "").strip().splitlines()
                print("audit %s : aucun rapport, pip-audit rc=%s : %s"
                      % (f, getattr(res, "returncode", "?"), " | ".join(_err[-3:])[:500]), flush=True)
            if sortie_json.is_file():
                try:
                    with open(sortie_json, encoding="utf-8") as h:
                        rapports[f] = json.load(h)
                except (OSError, ValueError):
                    rapports[f] = None
            else:
                rapports[f] = None
    v = verdict_audit(rapports)
    for b in v["bloquants"]:
        print("audit BLOQUANT (faille corrigeable) : %s" % b, flush=True)
    for a in v["avertis"]:
        print("audit AVERTISSEMENT (faille sans correctif) : %s" % a, flush=True)
    for i in v["illisibles"]:
        print("audit ILLISIBLE ou absent : %s" % i, flush=True)
    return v


# Audit des manifestes livres AVANT la CI de reference (pre-controle : la porte du tag refuserait sinon apres ~3 h de CI).
# Fenetre = _AUDIT_FRAICHEUR_J de tools/ci_local.py (« les avis OSV bougent tous les jours »), date lue dans le NOM
# du fichier (un checkout rajeunit le mtime) ; un NR verrouille l'egalite des deux constantes.
AUDITS = _RACINE_DONNEES / "sandbox" / "audit_manifestes_history"
FRAICHEUR_J = 7


def _contenu_au_sha(sha: str, f: str):
    rc, out = git("show", "%s:%s" % (sha, f), depot=ROOT)
    return out if rc == 0 else None


def _empreinte(texte) -> str:
    import hashlib
    return hashlib.sha256((texte or "").replace("\r\n", "\n").encode("utf-8")).hexdigest()


def commande_audit(sha: str) -> str:
    return "run_job online=true script=tools/dist_promotion.py script_args=\"--sha %s --audit-manifestes\"" % sha


def ecrire_audit_manifestes(sha: str, dossier: Path = AUDITS, executer=subprocess.run, jour=None) -> int:
    """Audite EN LIGNE les manifestes tels qu'ils sont AU sha et ecrit audit_manifestes_<jour>.json (rc 3 si rouge)."""
    import datetime
    jour = jour or datetime.date.today().isoformat()
    textes = dict((f, _contenu_au_sha(sha, f)) for f in MANIFESTES_LIVRES)
    rapports = {}
    with tempfile.TemporaryDirectory() as td:
        for f, t in textes.items():
            if t is not None:
                (Path(td) / f).write_text(t, encoding="utf-8", newline="\n")
        v = auditer_snapshot(td, executer, rapports)
    dossier.mkdir(parents=True, exist_ok=True)
    empreintes = dict((f, _empreinte(t) if t is not None else None) for f, t in textes.items())
    (dossier / ("audit_manifestes_%s.json" % jour)).write_text(
        json.dumps({"sha": sha, "jour": jour, "empreintes": empreintes, "rapports": rapports}), encoding="utf-8")
    return 0 if v["ok"] else 3


def audit_manifestes_frais(sha: str, dossier: Path = AUDITS, maintenant=None, contenu=None) -> tuple:
    """(ok, motif) : le dernier audit des manifestes livres est-il frais, lisible, du MEME contenu qu'au sha, et vert ?
    Illisible = refus motive, jamais ok."""
    import datetime
    contenu = contenu or _contenu_au_sha
    cmd = commande_audit(sha)
    fichiers = sorted(Path(dossier).glob("audit_manifestes_*.json")) if Path(dossier).is_dir() else []
    if not fichiers:
        return False, "aucun audit des manifestes livres dans %s -- lancer : %s" % (dossier, cmd)
    f = fichiers[-1]
    try:
        d = datetime.date.fromisoformat(re.search(r"(\d{4}-\d{2}-\d{2})", f.name).group(1))
        mes = json.loads(f.read_text(encoding="utf-8"))
        if not (isinstance(mes, dict) and isinstance(mes.get("rapports"), dict)
                and isinstance(mes.get("empreintes"), dict)):
            raise ValueError("forme")
    except Exception as e:  # noqa: BLE001
        return False, "audit %s ILLISIBLE (%s) -- relancer : %s" % (f.name, type(e).__name__, cmd)
    age = ((maintenant or datetime.date.today()) - d).days
    if age > FRAICHEUR_J:
        return False, "audit %s PERIME (%d j > %d j) -- relancer : %s" % (f.name, age, FRAICHEUR_J, cmd)
    for fm in MANIFESTES_LIVRES:
        t = contenu(sha, fm)
        if t is None or mes["empreintes"].get(fm) != _empreinte(t):
            return False, "audit %s ne porte pas les manifestes de %s (%s change ou illisible) -- relancer : %s" % (
                f.name, sha, fm, cmd)
    v = verdict_audit(mes["rapports"])
    if not v["ok"]:
        return False, "audit %s ROUGE (regle du tag) : %d bloquant(s), %d illisible(s) %s" % (
            f.name, len(v["bloquants"]), len(v["illisibles"]), (v["bloquants"] + v["illisibles"])[:3])
    return True, "audit %s frais (%d j), regle du tag respectee" % (f.name, age)


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
    if r.returncode == 0:
        a = auditer_snapshot(essai)
        if not a["ok"]:
            print("GARDE : audit des manifestes livres ROUGE (regle du tag) : %d bloquant(s), %d sans correctif, %d illisible(s)"
                  % (len(a["bloquants"]), len(a["avertis"]), len(a["illisibles"])), flush=True)
            return 3
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default="")
    ap.add_argument("--audit-manifestes", action="store_true",
                    help="audit EN LIGNE des manifestes livres au --sha, ecrit sandbox/audit_manifestes_history (avant la CI)")
    ap.add_argument("--sha", required=True, help="sha court certifie")
    ap.add_argument("--job", help="job_id de la CI de reference (promotion)")
    ap.add_argument("--repetition", action="store_true", help="snapshot d'essai seulement, rien pousse")
    ap.add_argument("--herite-de", default=None,
                    help="sha CERTIFIE dont --sha herite de la preuve (ecart : version, CHANGELOG, workflows seulement)")
    a = ap.parse_args(argv)
    if a.audit_manifestes:
        return ecrire_audit_manifestes(git("rev-parse", a.sha, depot=ROOT)[1] or a.sha)
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        print("GARDE : version non SemVer :", a.version, flush=True)
        return 3
    if a.repetition:
        return repetition(a.version, a.sha)
    if not a.job:
        print("GARDE : --job requis pour une promotion", flush=True)
        return 3

    journal = (_RACINE_DONNEES / "sandbox" / "jobs" / ("%s.log" % a.job)).read_text(encoding="utf-8", errors="replace")
    _, sha = git("rev-parse", a.sha, depot=ROOT)
    herite = git("rev-parse", a.herite_de, depot=ROOT)[1] if a.herite_de else None
    certs, raison_h, sha_preuve = certifications_pour(sha, herite)
    if raison_h:
        print("GARDE : heritage de preuve REFUSE :", raison_h, flush=True)
        return 3
    if herite:
        print("heritage de preuve : %s -> %s (diff restreint)" % (herite[:12], sha[:12]), flush=True)
    if len(certs) != 1 or not preuve_verte(journal, sha_preuve[:len(a.herite_de or a.sha)] if herite else a.sha):
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
           "--certification", str(cert), "--with-assets"] + (["--certification-heritee-de", herite] if herite else [])
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
