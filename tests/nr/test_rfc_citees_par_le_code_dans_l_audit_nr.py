"""NR -- toute RFC citee par le CODE de Nokido est dans la liste de l'audit RFC (owner 2026-10-20).

Demande owner : « profites-en, avec l'outil deja developpe, [verifier] qu'aucune autre RFC ne doit etre respectee, et
donc [l']ajouter ». Mesure du 20/10 : `tools/audit_rfc_compliance.py` ingere 82 RFC (CRITICAL_RFCS, miroir local
data/rfc_mirror de 9 778 RFC, zero reseau) ; le code et la doc en citent 117, dont 35 hors de la liste -- et parmi
elles des normes que le code IMPLEMENTE (JWK 7517/7638, JWS 7515, JWA 7518, Bearer 6750, mTLS 8705, 8707, 9068,
9207, 8414, 9728, robots.txt 9309...). Une RFC qu'on implemente sans l'avoir dans le RAG ne peut pas etre consultee
au moment de l'ecrire.

Ce qui est garde (cliquet) : chaque RFC citee dans app/, tools/ ou proxy_deno/ (hors app/_attic et hors l'outil
d'audit lui-meme, qui ne lit pas son propre vocabulaire) est dans CRITICAL_RFCS, OU declaree obsolete dans
RFC_OBSOLETES avec un successeur qui, lui, est dans la liste. Limite DITE : une norme utilisee sans etre citee
(WebSocket, PKCE...) n'est pas vue par ce scan.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
AUDIT = RACINE / "tools" / "audit_rfc_compliance.py"


def _liste():
    numeros, obsoletes = set(), {}
    for n in ast.walk(ast.parse(AUDIT.read_text(encoding="utf-8"))):
        if not isinstance(n, ast.Assign):
            continue
        noms = {getattr(t, "id", "") for t in n.targets}
        if "CRITICAL_RFCS" in noms:
            numeros = {int(x) for v in ast.literal_eval(n.value).values() for q in v for x in re.findall(r"\d{3,5}", q)}
        if "RFC_OBSOLETES" in noms:
            obsoletes = ast.literal_eval(n.value)
    return numeros, obsoletes


def _citations_du_code():
    cites = defaultdict(set)
    for dossier, motif in (("app", "*.py"), ("tools", "*.py"), ("proxy_deno", "*.ts")):
        for f in (RACINE / dossier).rglob(motif):
            rel = f.relative_to(RACINE).as_posix()
            if "_attic" in rel or f == AUDIT or "node_modules" in rel:
                continue
            texte = f.read_text(encoding="utf-8", errors="replace")
            for m in re.findall(r"(?i)\bRFC[\s_-]?(\d{3,5})\b", texte):
                cites[int(m)].add(rel)
    return cites


def test_toute_rfc_citee_par_le_code_est_dans_l_audit_ou_declaree_obsolete():
    numeros, obsoletes = _liste()
    assert len(numeros) >= 82, "la liste de l'audit ne retrecit pas"
    manquantes = {n: sorted(f)[:3] for n, f in _citations_du_code().items() if n not in numeros and n not in obsoletes}
    assert not manquantes, "RFC citees par le code, absentes de CRITICAL_RFCS : %s" % dict(sorted(manquantes.items()))


def test_le_successeur_d_une_rfc_obsolete_est_dans_la_liste():
    numeros, obsoletes = _liste()
    assert obsoletes, "RFC_OBSOLETES doit exister (obsolete -> successeur)"
    sans = {o: s for o, s in obsoletes.items() if s not in numeros}
    assert not sans, "successeur absent de CRITICAL_RFCS : %s" % sans
