#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_history_secret_audit.py -- ce que l'HISTOIRE exposerait si on ouvrait.

POURQUOI
========
Un HEAD propre ne dit RIEN de l'historique : un secret retire du code courant
reste lisible dans le commit qui l'a introduit. C'est la condition n.1 de
`docs/public_transition_checklist.md`, mesuree le 2026-08-21 puis jamais
rejouee -- donc invisible depuis.

MESURE 2026-08-29 qui a motive ce module : le blob `1e437b11be` de
`sandbox/live_bridge.map` porte une cle `google_api` NON factice, et il est
atteignable depuis `origin/alpha` ET `origin/beta`. L'alternative que la
checklist proposait -- « ne pas publier les branches d'archive, mirror =
alpha + beta seules » -- NE PROTEGE DONC RIEN : le secret est dans l'histoire
des branches publiables elles-memes. Seul un snapshot SANS historique (ou un
scrub) l'ecarte.

CE QU'IL FAIT / NE FAIT PAS
===========================
Il repond a « ce chemin sensible a-t-il porte un secret reel, et depuis quelles
refs ce blob est-il atteignable ». Il ne remplace pas un scan exhaustif de tous
les blobs (gitleaks `full_history`, qui exige un PAT `actions:write` absent
aujourd'hui) : il couvre les chemins CONNUS pour avoir porte des findings, et
la liste s'etend au fur et a mesure qu'on en decouvre.

Il ne fait qu'AFFICHER un COMPTE : la valeur trouvee n'est jamais imprimee,
sinon l'audit fuiterait ce qu'il surveille.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/audit-secrets-historique"

import argparse
import collections
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Chemins ayant DEJA porte un finding (checklist 2026-08-21). A etendre.
CHEMINS_SENSIBLES = [
    "sandbox/live_bridge.map",
    "app/forge_sovereign_membrane.py",
]
# Refs qu'un miroir publierait. Tout secret atteignable depuis elles PARTIRAIT.
REFS_PUBLIABLES = ("refs/heads/alpha", "refs/heads/beta",
                   "refs/remotes/origin/alpha", "refs/remotes/origin/beta")

# Les motifs couvrent l'ecart avec `gitleaks full_history`, qu'un PAT manquant
# empeche de lancer. Ils restent moins nombreux que ses ~150 regles : c'est une
# COUVERTURE, pas une equivalence, et le rapport ne pretend pas le contraire.
MOTIFS = {
    "google_api": rb"AIza[0-9A-Za-z_\-]{35}",
    "github_pat": rb"gh[pousr]_[0-9A-Za-z]{36,}",
    "aws_akid": rb"AKIA[0-9A-Z]{16}",
    "slack": rb"xox[baprs]-[0-9A-Za-z\-]{10,}",
    "openai": rb"sk-[A-Za-z0-9]{20,}",
    "anthropic": rb"sk-ant-[A-Za-z0-9_\-]{20,}",
    "huggingface": rb"hf_[A-Za-z0-9]{30,}",
    "groq": rb"gsk_[A-Za-z0-9]{40,}",
    # PAS de motif « 32 caracteres alphanumeriques » : mesure 2026-08-29, il a
    # rendu 6 findings dont 5 FAUX -- des fichiers de signature et des dumps de
    # conversation, ou tout hash MD5/sha tronque matche. Un motif qui ne peut pas
    # distinguer un hash d'une cle fait crier le garde a faux, et un garde qui
    # crie a faux se fait desarmer. Les cles Mistral seront couvertes quand elles
    # auront un prefixe distinctif, pas avant.
    "stripe": rb"[sr]k_(?:live|test)_[A-Za-z0-9]{20,}",
    "jwt": rb"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "url_avec_mdp": rb"[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s:@]{8,}@",
    # Groupe NON capturant : `re.findall` rend les GROUPES quand il y en a, donc
    # un groupe capturant ici renverrait "RSA " au lieu du match -- et le
    # classificateur d'entropie aurait pris une vraie cle privee pour un
    # placeholder. Rate silencieux, du cote le plus cher.
    "cle_privee": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
}
# Un placeholder n'est pas un secret : sans ce filtre, l'audit crie a faux et
# se fait desarmer (mesure : `ghp_DEMO_FACTICE_...` dans la membrane).
FACTICE = re.compile(rb"(?i)demo|factice|placeholder|redacted|example|fake|dummy|non_reel|xxx")
# Le filtre LEXICAL ne suffit pas : 6 blobs de la membrane portaient une chaine
# d'exemple qu'aucun mot-cle ne trahissait. Mesure 2026-08-29 -- les 6 avaient des
# statistiques IDENTIQUES (36 car., 19 distincts, entropie 3.08) la ou le vrai
# jeton de live_bridge.map sort a 27 distincts / 4.65. Un secret genere est
# proche de l'aleatoire ; un exemple ecrit a la main ne l'est pas.
_ENTROPIE_MIN = 3.2
_DISTINCTS_MIN = 9


def _entropie(corps: bytes) -> float:
    if not corps:
        return 0.0
    n = len(corps)
    return -sum((c / n) * math.log2(c / n) for c in collections.Counter(corps).values())


# Fichiers dont le ROLE est de porter des echantillons de fuite : les priver de
# leur charge utile viderait le test de sa substance. L'exception est NOMMEE,
# etroite, et RAPPORTEE a chaque execution -- une exception muette est un trou.
EXCEPTIONS = {
    "app/stress_test_firewall.py":
        "banc de stress du SemanticFirewall : les echantillons « Secret Leak "
        "(Fake API) » SONT le test. Verifie 2026-08-29 : contexte explicite, "
        "16 car. d'entropie 4,00, jamais un jeton emis.",
}


# Un MASQUE d'exemple (`......`, `xxxxxx`, `******`) n'est pas un secret. Mesure
# 2026-08-29 : `docs/SECURITY_AUDIT.md` sortait en finding parce que l'entropie
# etait calculee sur l'URL ENTIERE, pas sur le mot de passe -- le scheme et le
# nom d'utilisateur suffisaient a la faire monter.
_MASQUE = re.compile(rb"(.)\1{3,}")
# Un secret ne se TERMINE pas par des points de suspension : c'est une citation
# tronquee. Mesure 2026-08-29, `docs/SECURITY_AUDIT.md` -- mot de passe de forme
# `########...`, soit 8 caracteres montres puis coupes. Le detecteur de masque ne
# le voyait pas (il exige 4 caracteres identiques, « ... » n'en a que 3).
_TRONQUE = re.compile(rb"(?:\.{3}|\xe2\x80\xa6)$")


def _est_factice(brut: bytes) -> bool:
    """True = placeholder. Sur le doute on repond False : rater un vrai secret
    coute infiniment plus cher qu'un finding a instruire."""
    if FACTICE.search(brut):
        return True
    if b"://" in brut and b":" in brut.split(b"://", 1)[1]:
        # URL avec identifiants : seul le MOT DE PASSE est le secret.
        mdp = brut.split(b"://", 1)[1].split(b":", 1)[1].rstrip(b"@")
        return (bool(_MASQUE.search(mdp)) or bool(_TRONQUE.search(mdp))
                or len(set(mdp)) < 5)
    if _MASQUE.search(brut) or _TRONQUE.search(brut):
        return True
    corps = brut.split(b"_", 1)[-1] if brut[:2] in (b"gh",) else brut[4:]
    return len(set(corps)) < _DISTINCTS_MIN or _entropie(corps) < _ENTROPIE_MIN


def _git(*args, binaire=False):
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
                       capture_output=True, timeout=600)
    return r.stdout if binaire else r.stdout.decode("utf-8", "replace")


def _blobs(chemin):
    vus = {}
    for ligne in _git("rev-list", "--all", "--objects", "--", chemin).splitlines():
        p = ligne.split(" ", 1)
        if len(p) == 2 and p[1].strip() == chemin:
            vus[p[0]] = True
    return list(vus)


def _refs_porteuses(sha, chemin):
    out = []
    for ref in [l.strip() for l in _git("for-each-ref", "--format=%(refname)").splitlines() if l.strip()]:
        if any(li.startswith(sha) for li in
               _git("rev-list", ref, "--objects", "--", chemin).splitlines()):
            out.append(ref)
    return out


def audit(chemins=None):
    resultats, exposes = [], 0
    for chemin in (chemins or CHEMINS_SENSIBLES):
        for sha in _blobs(chemin):
            data = _git("cat-file", "blob", sha, binaire=True)
            for nom, motif in MOTIFS.items():
                hits = re.findall(motif, data)
                reels = [h for h in hits if not _est_factice(h)]
                if not reels:
                    continue
                refs = _refs_porteuses(sha, chemin)
                publiables = [r for r in refs if r in REFS_PUBLIABLES]
                if publiables:
                    exposes += len(reels)
                resultats.append({
                    "chemin": chemin, "blob": sha[:12], "type": nom,
                    "occurrences_reelles": len(reels), "factices_ignorees": len(hits) - len(reels),
                    "refs_porteuses": len(refs),
                    "atteignable_depuis_publiable": publiables,
                })
    return {"findings": resultats, "exposes_si_publication": exposes,
            "verdict": "EXPOSE" if exposes else ("PROPRE" if not resultats else "CONTENU")}


def lire_blobs(shas, max_octets=4_000_000):
    """Rend (sha, contenu|None, taille) pour chaque blob, via UN SEUL process git.

    Un aller-retour par objet dans le meme `cat-file --batch` : ecrire TOUS les
    sha puis lire ensuite remplit le tuyau et bloque les deux cotes -- deadlock
    mesure le 2026-08-29, deux jobs figes qu'il a fallu tuer. Un process par blob
    serait correct mais 100x plus lent (mesure : audit tue au bout de 115 s).

    `contenu is None` = blob volontairement NON lu (trop gros) : l'appelant doit
    le compter comme non inspecte, jamais comme propre.
    """
    proc = subprocess.Popen(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha in shas:
            proc.stdin.write((sha + "\n").encode())
            proc.stdin.flush()
            entete = proc.stdout.readline().decode("utf-8", "replace").split()
            if len(entete) < 3:
                break
            vrai_sha, typ, taille = entete[0], entete[1], int(entete[2])
            brut = proc.stdout.read(taille + 1)[:taille]
            if typ != "blob":
                continue
            yield vrai_sha, (None if taille > max_octets else brut), taille
    finally:
        try:
            proc.stdin.close()
        except OSError:  # muet-ok : tuyau deja ferme
            pass
        proc.stdout.close()
        proc.wait(timeout=60)


def audit_exhaustif(refs=REFS_PUBLIABLES, max_octets=4_000_000):
    """Balaye TOUS les blobs atteignables depuis les refs publiables.

    La checklist demandait `gitleaks full_history`, qui exige un PAT
    `actions:write` absent aujourd'hui (403). Rien n'empeche de le faire en
    LOCAL : c'est le « second filet » qu'elle mentionne. On lit les blobs par
    FLUX (`cat-file --batch`) et non un process par objet -- sur un depot de
    cette taille, la difference est entre quelques minutes et plusieurs heures.

    Les blobs au-dela de `max_octets` sont COMPTES et rapportes comme non
    inspectes : un objet qu'on n'a pas lu n'est pas un objet propre.
    """
    refs_reelles = [r for r in refs
                    if subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                                       "rev-parse", "--verify", "--quiet", r],
                                      capture_output=True).returncode == 0]
    if not refs_reelles:
        return {"verdict": "INDETERMINE", "raison": "aucune ref publiable resolvable",
                "findings": [], "exposes_si_publication": 0}

    inventaire = {}
    for ligne in _git("rev-list", *refs_reelles, "--objects").splitlines():
        p = ligne.split(" ", 1)
        if len(p) == 2 and p[1].strip():
            inventaire.setdefault(p[0], p[1].strip())

    findings, lus, sautes, exceptions = [], 0, 0, []
    for sha, data, taille in lire_blobs(list(inventaire), max_octets):
        if data is None:
            sautes += 1
            continue
        lus += 1
        chemin = inventaire.get(sha, "?")
        if chemin in EXCEPTIONS:
            exceptions.append(chemin)
            continue
        for nom, motif in MOTIFS.items():
            reels = [h for h in re.findall(motif, data) if not _est_factice(h)]
            if reels:
                findings.append({"chemin": inventaire.get(sha, "?"), "blob": sha[:12],
                                 "type": nom, "occurrences_reelles": len(reels),
                                 "atteignable_depuis_publiable": refs_reelles})
    total = sum(f["occurrences_reelles"] for f in findings)
    return {"verdict": "EXPOSE" if total else "PROPRE", "findings": findings,
            "exposes_si_publication": total, "blobs_lus": lus,
            "blobs_non_inspectes": sautes, "refs": refs_reelles,
            "exceptions_appliquees": sorted(set(exceptions))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--exhaustif", action="store_true",
                    help="balaye TOUS les blobs des refs publiables (long)")
    ap.add_argument("--chemin", action="append", default=[],
                    help="chemin supplementaire a auditer")
    args = ap.parse_args(argv)
    if args.exhaustif:
        r = audit_exhaustif()
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print("  blobs lus : %s | non inspectes (trop gros) : %s"
                  % (r.get("blobs_lus"), r.get("blobs_non_inspectes")))
            for f in r["findings"][:40]:
                print("  %-52s %-11s %d reel(s)"
                      % (f["chemin"][:52], f["type"], f["occurrences_reelles"]))
            print("\n  VERDICT : %s (%d secret(s))"
                  % (r["verdict"], r["exposes_si_publication"]))
        return 1 if r["verdict"] == "EXPOSE" else 0
    r = audit((CHEMINS_SENSIBLES + args.chemin) if args.chemin else None)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        for f in r["findings"]:
            print("  %-34s blob %s  %-11s %d reel(s), publiable depuis %s"
                  % (f["chemin"], f["blob"], f["type"], f["occurrences_reelles"],
                     f["atteignable_depuis_publiable"] or "aucune"))
        print("\n  VERDICT : %s (%d secret(s) partiraient a la publication)"
              % (r["verdict"], r["exposes_si_publication"]))
        if r["verdict"] == "EXPOSE":
            print("  La cle est a considerer COMPROMISE (rotation), et un miroir de")
            print("  branches ne suffit pas : il faut un snapshot SANS historique.")
    return 1 if r["verdict"] == "EXPOSE" else 0


if __name__ == "__main__":
    sys.exit(main())
