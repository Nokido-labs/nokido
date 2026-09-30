#!/usr/bin/env python3
"""
forge_conv_dlp_audit.py — Le corpus conversationnel contient-il des secrets ?

POURQUOI
========
Le 2026-08-12, 25 711 chunks de conversations (56 sessions Claude + 150 AGY) ont ete
inseres dans `rag_chunks` par `forge_conv_indexer`. Or ce module ecrit en SQLite en
DIRECT : il n'appelle `forge_secret_guard` NULLE PART. Le canal n'y change rien --
passer par le hub aurait insere le meme texte brut. Une conversation d'agent contient
des jetons colles, des chemins, des identifiants : le corpus a donc ete verse sans
passer par le foie.

Cet outil repond a une seule question : **est-ce que quelque chose a fuite ?**

REGLE ABSOLUE
=============
Ce script n'imprime JAMAIS le secret, ni le message d'exception qui pourrait le
contenir. Il rend l'EMPLACEMENT (id, source) et rien d'autre. Le 2026-08-11, une
sonde d'inventaire a fuite des jetons de service dans son propre rapport ; un
auditeur de fuite qui fuit est pire qu'aucun auditeur.

USAGE
=====
    LAFORGE_PYTHON tools/forge_conv_dlp_audit.py                 # audit seul
    LAFORGE_PYTHON tools/forge_conv_dlp_audit.py --domains conv
    LAFORGE_PYTHON tools/forge_conv_dlp_audit.py --redact        # caviarde en base

Sortie : 0 = rien trouve, 1 = fuites detectees, 2 = non observable.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RAG_DB = ROOT / "RAG" / "embeddings.db"
DEFAULT_DOMAINS = ("conv", "mcp_result", "curated_skills")


def _log(m: str) -> None:
    print(f"[dlp-audit] {m}", flush=True)


def _famille(source: str) -> str:
    return str(source).split("/", 1)[0] if source else "?"


def _reparer_ids(domaines: list[str]) -> int:
    """Recalcule les `id` incoherents avec leur texte.

    `id = sha256(source + text)[:16]` (forge_conv_indexer._chunk_id). Toute
    reecriture du texte -- typiquement le caviardage -- rend l'id PERIME. La
    deduplication `INSERT OR IGNORE` ne reconnait alors plus la ligne : la
    prochaine reindexation la DUPLIQUE au lieu de l'ignorer. Silencieusement.
    """
    marques = ",".join("?" for _ in domaines)
    con = sqlite3.connect(str(RAG_DB), timeout=60)
    lignes = con.execute(
        f"SELECT id, source, text FROM rag_chunks WHERE domain IN ({marques}) AND text IS NOT NULL",
        domaines,
    ).fetchall()
    incoherents = [
        (cid, hashlib.sha256(f"{src}{txt}".encode()).hexdigest()[:16])
        for cid, src, txt in lignes
        if cid != hashlib.sha256(f"{src}{txt}".encode()).hexdigest()[:16]
    ]
    _log(f"{len(lignes)} chunks verifies, {len(incoherents)} id incoherent(s)")
    n = 0
    for ancien, neuf in incoherents:
        try:
            con.execute("UPDATE rag_chunks SET id=? WHERE id=?", (neuf, ancien))
            n += 1
        except sqlite3.IntegrityError:
            # Un chunk identique existe deja sous le bon id : celui-ci est un doublon.
            con.execute("DELETE FROM rag_chunks WHERE id=?", (ancien,))
            _log(f"    doublon supprime : {ancien}")
    con.commit()
    con.close()
    _log(f"REPARE -- {n} id recalcule(s).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit DLP du corpus conversationnel")
    ap.add_argument("--domains", default=",".join(DEFAULT_DOMAINS))
    ap.add_argument("--redact", action="store_true",
                    help="caviarde en base les chunks fautifs (sinon audit seul)")
    ap.add_argument("--repair-ids", action="store_true",
                    help="recalcule les id devenus perimes apres reecriture du texte")
    a = ap.parse_args()

    if not RAG_DB.exists():
        _log(f"INDETERMINE : base absente ({RAG_DB}) -- V: monte ?")
        return 2

    if a.repair_ids:
        return _reparer_ids([d.strip() for d in a.domains.split(",") if d.strip()])
    try:
        from nokido_agent.app.forge_secret_guard import SecretLeakBlocked, scan_outbound
    except Exception as e:
        _log(f"INDETERMINE : forge_secret_guard indisponible ({type(e).__name__}) "
             f"-- aucune conclusion, ce n'est PAS une absence de fuite")
        return 2
    motifs = []
    if a.redact:
        try:
            from nokido_agent.app.forge_secret_guard import _OUTBOUND_PATTERNS
        except Exception as e:
            _log(f"--redact impossible : motifs indisponibles ({type(e).__name__})")
            return 2
        # Substitution CIBLEE motif par motif, plutot qu'un redacteur generique dont
        # on ne maitrise pas le perimetre. `Hex-64` est exclu : il matche tout SHA git
        # et toute cle de cache (311 declenchements, quasi tous du bruit) ; le
        # caviarder abimerait des references legitimes.
        motifs = [(p, lab) for p, lab in _OUTBOUND_PATTERNS if not lab.startswith("Hex-64")]

    def redacteur(t: str) -> str:
        for p, lab in motifs:
            t = p.sub(f"[REDACTED:{lab}]", t)
        return t

    # MUSELER le garde. `scan_outbound` emet lui-meme un `logger.critical` contenant
    # les 12 premiers caracteres du secret (forge_secret_guard.py:546). Le premier jet
    # de cet audit a donc DEVERSE 397 extraits dans sa propre sortie -- alors que tout
    # le script est concu pour ne rien montrer. Un auditeur de fuite qui fuit est pire
    # qu'aucun auditeur (cf 2026-08-11, sonde d'inventaire).
    logging.getLogger("Nokido.SecretGuard").disabled = True

    domaines = [d.strip() for d in a.domains.split(",") if d.strip()]
    marques = ",".join("?" for _ in domaines)
    t0 = time.time()

    con = sqlite3.connect(str(RAG_DB), timeout=60)
    lignes = con.execute(
        f"SELECT id, source, text FROM rag_chunks WHERE domain IN ({marques}) AND text IS NOT NULL",
        domaines,
    ).fetchall()

    fuites: list[tuple[str, str, str]] = []
    par_famille: Counter = Counter()
    par_label: Counter = Counter()
    scannes = 0
    for cid, source, texte in lignes:
        scannes += 1
        try:
            # local_only=False IMPERATIF. `scan_outbound` commence par
            # `if local_only: return` (forge_secret_guard.py:538) : c'est un BYPASS
            # TOTAL, pense pour les providers locaux ou rien ne quitte la machine.
            # Le premier jet de cet audit passait True et "scannait" 53 947 chunks en
            # 0,3 s sans rien lire, en concluant "aucun secret". Ici on n'envoie rien
            # dehors : on veut le detecteur, pas la politique d'egress.
            scan_outbound(str(texte), provider="rag_audit", local_only=False)
        except SecretLeakBlocked as e:
            # `e.label` est le NOM du motif : sans danger. `e.snippet` porte le secret
            # et `str(e)` aussi -- ni l'un ni l'autre ne doit sortir d'ici.
            label = getattr(e, "label", "?")
            fuites.append((cid, source, label))
            par_famille[_famille(source)] += 1
            par_label[label] += 1
        except Exception:
            pass  # scanner en echec sur ce chunk : ne pas conclure a l'absence

    _log(f"{scannes} chunks scannes sur {len(domaines)} domaine(s) en {time.time() - t0:.1f}s")
    if not fuites:
        _log("OK -- aucun secret detecte par scan_outbound.")
        con.close()
        return 0

    _log(f"DETECTIONS -- {len(fuites)} chunk(s) declenchent le garde.")
    _log("  par MOTIF (c'est ce qui dit si c'est grave) :")
    for label, n in par_label.most_common():
        _log(f"    {label:<38} {n}")
    _log("  par FAMILLE de source :")
    for fam, n in par_famille.most_common(12):
        _log(f"    {fam[:60]:<62} {n}")
    _log("  (aucun contenu affiche, volontairement)")

    if not a.redact:
        _log("Audit seul. Relancer avec --redact pour caviarder en base.")
        con.close()
        return 1

    n = 0
    for cid, _source, _label in fuites:
        if _label.startswith("Hex-64"):
            continue  # bruit : ne pas toucher aux SHA et cles de cache
        rangee = con.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
        if not rangee:
            continue
        propre = redacteur(str(rangee[0]))
        con.execute("UPDATE rag_chunks SET text=? WHERE id=?", (propre, cid))
        try:
            con.execute(
                "UPDATE rag_fts SET text=? WHERE rowid=(SELECT rowid FROM rag_chunks WHERE id=?)",
                (propre, cid),
            )
        except Exception:
            pass  # FTS optionnel : le caviardage de rag_chunks fait foi
        n += 1
    con.commit()
    con.close()
    _log(f"CAVIARDE -- {n} chunk(s) reecrits en base (rag_chunks + rag_fts). "
         f"Les detections Hex-64 ont ete laissees intactes (bruit).")
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
