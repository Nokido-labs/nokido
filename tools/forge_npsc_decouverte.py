#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NPSC — DECOUVERTE des surfaces, par mesure et non par liste a priori.

Question de l'owner (2026-09-04) : « ca m'etonne que tu ne trouves pas plus de
surface de mise en conformite ». Elle est juste — le registre v2 en declarait 13,
choisies a la main. Une liste ecrite a la main mesure ce que son auteur avait en
tete, pas ce que le depot expose.

Ce module ne juge rien et ne declare rien. Il RECENSE ce que le code versionne
manipule reellement, pour que l'elargissement du registre soit une consequence
de la mesure :

    imports tiers            -> quelles bibliotheques de protocole sont utilisees
    schemes d'URI            -> ssh:// mysql:// amqp:// ...   (RFC 3986 + IANA)
    types de media           -> application/... text/...      (IANA media types)
    en-tetes HTTP nommes     -> Authorization, Content-Type, ... (RFC 9110)
    ports litteraux          -> surfaces reseau reelles       (IANA ports)
    noms de fichiers normes  -> robots.txt, openapi.json, compose.yaml ...

Reutilise integralement le capteur `forge_npsc_scan` (git ls-files, populations,
AST) : meme frontiere, memes exclusions DATA/VENDOR, meme invariant — un fichier
non versionne ou classe DATA ne temoigne de rien.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/conformite-normative"

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nokido_agent.tools.forge_npsc_scan import (  # noqa: E402
    CONFIG, DATA, MAX_OCTETS, PORTENT_PREUVE, ROOT, VENDOR,
    classer, fichiers_versionnes, signaux_lexicaux, signaux_python,
)

SORTIE = ROOT / "sandbox" / "npsc_decouverte.json"

# Modules de la bibliotheque standard qui portent une surface PROTOCOLAIRE.
# Le reste de la stdlib n'a pas d'autorite normative externe a auditer.
_STDLIB_PROTOCOLAIRE = {
    "ssl", "socket", "http", "http.client", "http.server", "http.cookies",
    "urllib", "urllib.request", "urllib.parse", "email", "smtplib", "imaplib",
    "poplib", "ftplib", "telnetlib", "socketserver", "xmlrpc", "json", "csv",
    "base64", "binascii", "hashlib", "hmac", "secrets", "uuid", "ipaddress",
    "sqlite3", "zlib", "gzip", "bz2", "lzma", "tarfile", "zipfile", "unicodedata",
    "codecs", "mimetypes", "wsgiref", "asyncio", "selectors", "struct",
}
# Prefixes internes : ce ne sont pas des dependances a auditer.
_PREFIXES_INTERNES = ("forge_", "nokido", "app", "tools", "netcfg", "proxy_deno")

_RX_SCHEME = re.compile(r"\b([a-z][a-z0-9+.\-]{1,15})://")
_RX_MEDIA = re.compile(r"\b((?:application|text|image|audio|video|multipart|message|model|font)/[a-z0-9][a-z0-9.+\-]{1,40})")
_RX_ENTETE = re.compile(r"\b(X-[A-Za-z][A-Za-z0-9\-]{1,30}|Authorization|Content-Type|Content-Length|Accept|Accept-Encoding|User-Agent|Cache-Control|ETag|If-None-Match|Set-Cookie|Cookie|Origin|Access-Control-[A-Za-z\-]+|Content-Security-Policy|Strict-Transport-Security|Retry-After|Last-Event-ID|WWW-Authenticate)\b")
_RX_PORT = re.compile(r"(?::|port[\"']?\s*[=:]\s*)(\d{2,5})\b")
_RX_FICHIER_NORME = re.compile(r"\b(robots\.txt|sitemap\.xml|openapi\.json|openapi\.ya?ml|swagger\.json|docker-compose\.ya?ml|compose\.ya?ml|Dockerfile|\.well-known/[a-z0-9\-./]+|CITATION\.cff|SECURITY\.md)\b")

# Ports connus, pour donner un sens aux nombres plutot qu'une liste brute.
_PORTS_CONNUS = {
    "22": "SSH", "25": "SMTP", "53": "DNS", "80": "HTTP", "123": "NTP",
    "143": "IMAP", "389": "LDAP", "443": "HTTPS", "465": "SMTPS", "587": "SMTP submission",
    "993": "IMAPS", "1234": "LM Studio (OpenAI-compat)", "3306": "MySQL",
    "5432": "PostgreSQL", "5557": "brain_worker ZMQ", "6333": "Qdrant HTTP",
    "6334": "Qdrant gRPC", "6379": "Redis", "7400": "Web Portal", "7401": "Deno Web Hub",
    "7474": "Graph Explorer", "7500": "netcfg UI", "8080": "llamacpp natif",
    "8091": "llama-server", "8098": "loopback", "8099": "embedder", "8100": "reranker",
    "8765": "LaForge-Master", "8766": "hub MCP", "8767": "netcfg MCP",
    "9200": "GitHub sidecar / Elasticsearch", "11434": "ollama",
}


def _est_tiers(module):
    """Un import est-il une dependance TIERCE, donc porteuse d'une surface ?"""
    racine = module.split(".")[0]
    if racine in _STDLIB_PROTOCOLAIRE or module in _STDLIB_PROTOCOLAIRE:
        return True
    for prefixe in _PREFIXES_INTERNES:
        if racine.startswith(prefixe):
            return False
    return True


def decouvrir(racine=ROOT, limite=45):
    """Recense ce que le code versionne manipule. Rend (inventaire, diagnostic)."""
    racine = Path(racine)
    fichiers, err = fichiers_versionnes(racine)
    diag = {"source": "git ls-files", "erreur_index": err, "suivis": 0, "lus": 0,
            "illisibles": 0, "ecartes_data_vendor": 0, "ast_echecs": 0}
    if fichiers is None:
        diag["instrument_ok"] = False
        return None, diag

    diag["suivis"] = len(fichiers)
    imports = Counter()
    stdlib = Counter()
    schemes = Counter()
    medias = Counter()
    entetes = Counter()
    ports = Counter()
    normes_fichier = Counter()

    for rel in fichiers:
        pop = classer(rel)
        if pop in (DATA, VENDOR):
            diag["ecartes_data_vendor"] += 1
            continue
        if pop not in PORTENT_PREUVE and pop != CONFIG:
            # DOC et TEST ne temoignent pas d'une surface implementee.
            continue
        chemin = racine / rel
        try:
            if chemin.stat().st_size > MAX_OCTETS:
                continue
            texte = chemin.read_text(encoding="utf-8", errors="replace")
        except Exception:
            diag["illisibles"] += 1
            continue
        diag["lus"] += 1

        if rel.lower().endswith(".py"):
            signaux, _err = signaux_python(texte)
            if signaux is None:
                diag["ast_echecs"] += 1
                signaux = signaux_lexicaux(texte)
        else:
            signaux = signaux_lexicaux(texte)

        vus = set()
        for module in signaux["imports"]:
            racine_mod = module.split(".")[0]
            if racine_mod in vus:
                continue
            vus.add(racine_mod)
            if racine_mod in _STDLIB_PROTOCOLAIRE or module in _STDLIB_PROTOCOLAIRE:
                stdlib[racine_mod] += 1
            elif _est_tiers(module):
                imports[racine_mod] += 1

        blob = "\n".join(signaux["chaines"])
        for scheme in set(_RX_SCHEME.findall(blob.lower())):
            schemes[scheme] += 1
        for media in set(_RX_MEDIA.findall(blob.lower())):
            medias[media] += 1
        for entete in set(_RX_ENTETE.findall(blob)):
            entetes[entete] += 1
        for port in set(_RX_PORT.findall(blob)):
            if 20 <= int(port) <= 65535:
                ports[port] += 1
        for nom in set(_RX_FICHIER_NORME.findall(texte)):
            normes_fichier[nom] += 1

    diag["instrument_ok"] = diag["lus"] > 0
    inventaire = {
        "imports_tiers": imports.most_common(limite),
        "stdlib_protocolaire": stdlib.most_common(limite),
        "schemes_uri": schemes.most_common(limite),
        "types_media": medias.most_common(limite),
        "entetes_http": entetes.most_common(limite),
        "ports": [(p, n, _PORTS_CONNUS.get(p, "?")) for p, n in ports.most_common(limite)],
        "fichiers_normes": normes_fichier.most_common(limite),
    }
    return inventaire, diag


def main(argv=None):
    parseur = argparse.ArgumentParser(description="Recense les surfaces reellement manipulees")
    parseur.add_argument("--racine", default=str(ROOT))
    parseur.add_argument("--limite", type=int, default=45)
    parseur.add_argument("--json", action="store_true")
    args = parseur.parse_args(argv)

    inventaire, diag = decouvrir(Path(args.racine), args.limite)
    if inventaire is None:
        print("NO_VERDICT - index git indisponible : %s" % diag.get("erreur_index"))
        return 2

    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"inventaire": inventaire, "instrument": diag},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print("[decouverte] trace non posee : %s" % exc)

    if args.json:
        print(json.dumps(inventaire, ensure_ascii=False))
        return 0

    print("DECOUVERTE - %d suivis, %d lus, %d ecartes (DATA/VENDOR), %d illisibles"
          % (diag["suivis"], diag["lus"], diag["ecartes_data_vendor"], diag["illisibles"]))
    sections = (
        ("imports tiers", inventaire["imports_tiers"]),
        ("stdlib protocolaire", inventaire["stdlib_protocolaire"]),
        ("schemes d'URI", inventaire["schemes_uri"]),
        ("types de media", inventaire["types_media"]),
        ("en-tetes HTTP", inventaire["entetes_http"]),
        ("fichiers normes", inventaire["fichiers_normes"]),
    )
    for titre, donnees in sections:
        if not donnees:
            continue
        print("\n== %s (%d distincts) ==" % (titre, len(donnees)))
        for nom, compte in donnees:
            print("   %-34s %5d fichiers" % (nom[:34], compte))
    if inventaire["ports"]:
        print("\n== ports litteraux ==")
        for port, compte, sens in inventaire["ports"]:
            print("   %-6s %5d fichiers   %s" % (port, compte, sens))
    print("\ntrace : %s" % SORTIE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
