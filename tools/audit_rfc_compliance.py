import sys
import os
import json
import time
import logging

# Ensure tools directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from nokido_agent.tools.forge_rfc_ingest import LocalRFCIngestionTool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Liste des RFCs critiques (Socles et Voies futures de Nokido).
# Elargie le 2026-07-31 : le perimetre initial (9 normes) couvrait le hub et
# l'identite, mais AUCUNE des normes reseau sur lesquelles s'appuie netcfg-agent
# (SNMP, SSH, syslog, QoS, routage). Toutes verifiees presentes dans le miroir local.
CRITICAL_RFCS = {
    "Fondations Réseau & Web": [
        "RFC 9110",  # HTTP Semantics
        "RFC 8259",  # JSON Data Interchange Format (base de MCP)
        "RFC 8895",  # ALTO / Server-Sent Events (transport MCP)
        "RFC 3986",  # URI Generic Syntax (cite par ARCHITECTURE_IDENTITE)
        "RFC 5234",  # ABNF (grammaires des protocoles)
        "RFC 8785",  # JSON Canonicalization Scheme (signature de payloads)
    ],
    "Authentification & Délégation (OAuth)": [
        "RFC 6749",  # OAuth 2.0 Authorization Framework
        "RFC 6819",  # OAuth 2.0 Threat Model and Security Considerations
        "RFC 8693",  # OAuth 2.0 Token Exchange (delegation intra-Swarm)
    ],
    "Sécurité Zero-Trust & Identité": [
        "RFC 9449",  # OAuth 2.0 DPoP
        "RFC 7519",  # JSON Web Token (JWT)
        "RFC 8725",  # JWT Best Current Practices
    ],
    "IP, routage et adressage (netcfg-agent)": [
        "RFC 791",   # Internet Protocol (IPv4)
        "RFC 1812",  # Requirements for IP Version 4 Routers
        "RFC 8200",  # IPv6 Specification -- REMPLACE la RFC 2460 (obsolete)
        "RFC 2131",  # DHCP
        "RFC 1918",  # Address Allocation for Private Internets
        "RFC 9568",  # VRRP v3 -- REMPLACE la RFC 5798 (obsolete)
    ],
    "QoS / DiffServ (netcfg-agent)": [
        "RFC 2474",  # Definition of the Differentiated Services Field
        "RFC 2475",  # An Architecture for Differentiated Services
        "RFC 4594",  # Configuration Guidelines for DiffServ Service Classes
    ],
    "Supervision SNMP (netcfg-agent)": [
        "RFC 3411",  # Architecture for SNMP Management Frameworks
        "RFC 3412",  # Message Processing and Dispatching
        "RFC 3413",  # SNMP Applications
        "RFC 3414",  # USM (User-based Security Model, SNMPv3)
        "RFC 3415",  # VACM (View-based Access Control Model)
        "RFC 3418",  # MIB for SNMP
    ],
    "Accès administratif : SSH, AAA, journaux, temps (netcfg-agent)": [
        "RFC 4251",  # SSH Protocol Architecture
        "RFC 4252",  # SSH Authentication Protocol
        "RFC 4253",  # SSH Transport Layer Protocol
        "RFC 4254",  # SSH Connection Protocol
        "RFC 5424",  # The Syslog Protocol
        "RFC 5905",  # NTPv4
        "RFC 2865",  # RADIUS
        "RFC 2866",  # RADIUS Accounting
        "RFC 8907",  # TACACS+
    ],
    # Textes qui METTENT A JOUR une norme deja ciblee. Sortis le 2026-09-03 par
    # `forge_rfc_freshness_gate` (amont : rfc-index.xml de rfc-editor) : 24 des 36
    # normes ingerees etaient mises a jour en amont, 0 obsolete. Le corpus
    # certifiait la PRESENCE sans jamais verifier la FRAICHEUR -- une norme
    # perimee citee comme autorite est pire qu'une norme absente : l'absence se
    # voit. Les 46 textes ci-dessous sont TOUS deja dans le miroir local
    # (9 778 RFC sur disque), donc l'ingestion ne demande aucun reseau.
    "Mises a jour amont (gate de fraicheur 2026-09-03)": [
        "RFC 1349", "RFC 2644", "RFC 2867", "RFC 2868", "RFC 3168",
        "RFC 3260", "RFC 3396", "RFC 3575", "RFC 4361", "RFC 5080",
        "RFC 5343", "RFC 5494", "RFC 5590", "RFC 5865", "RFC 5997",
        "RFC 6633", "RFC 6668", "RFC 6761", "RFC 6842", "RFC 6864",
        "RFC 6929", "RFC 7320", "RFC 7405", "RFC 7797", "RFC 7822",
        "RFC 8044", "RFC 8252", "RFC 8268", "RFC 8308", "RFC 8332",
        "RFC 8436", "RFC 8573", "RFC 8622", "RFC 8709", "RFC 8758",
        "RFC 8820", "RFC 8996", "RFC 9109", "RFC 9141", "RFC 9142",
        "RFC 9673",
        "RFC 9700",  # OAuth 2.0 Security BCP — remplace la guidance de 6749/6819
        "RFC 9748", "RFC 9765", "RFC 9769",
        "RFC 9887",  # TACACS+ mis a jour
    ],
}


def _emit_progres(etape, i, n):
    """Barre d'avancement du job (norme du projet : un job long s'affiche)."""
    try:
        import os
        import sys as _s
        _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from nokido_agent.tools.forge_job_progress import emit
        emit(str(etape), index=i, total=n)
    except Exception:  # noqa: BLE001  # muet-ok : l'observabilite ne casse pas l'audit
        pass


def _rag_db_path():
    """Chemin de la base RAG, demande a forge_db_path (jamais code en dur)."""
    try:
        from nokido_agent.app import forge_db_path as fdp
        for name in dir(fdp):
            if name.startswith("_"):
                continue
            val = getattr(fdp, name)
            if isinstance(val, (str, os.PathLike)) and str(val).endswith(".db"):
                return str(val)
    except Exception as exc:
        logging.warning("forge_db_path illisible (%s) : verification base desactivee.", exc)
    return None


def _count_in_rag(db_path, source):
    """Compte INDEPENDANT en base. Rend None si la base est ILLISIBLE.

    Trois etats, jamais deux : un entier (mesure), 0 (mesure : rien), None
    (on n'a pas pu regarder). Confondre les deux derniers est exactement ce qui
    a produit le faux rapport du 2026-06-16.
    """
    if not db_path:
        return None
    try:
        import sqlite3
        uri = "file:%s?mode=ro" % str(db_path).replace("\\", "/")
        con = sqlite3.connect(uri, uri=True)
        try:
            return con.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE source = ?", (source,)
            ).fetchone()[0]
        finally:
            con.close()
    except Exception as exc:
        logging.warning("Verification base impossible pour %s : %s", source, exc)
        return None

def _rfc_source(rfc_query):
    """'RFC 5424' -> 'rfc:rfc5424' (la source posee par forge_rfc_ingest)."""
    digits = "".join(ch for ch in rfc_query if ch.isdigit())
    return f"rfc:rfc{digits}" if digits else None


def run_audit(categories=None, limit=None, force=False, workers=4):
    """Ingere les normes manquantes, puis REDIGE le rapport depuis la BASE.

    Rejouable par tranches (--category / --limit) : l'appel MCP est cape, une
    passe complete des 36 normes le depasse. Le rapport reste COMPLET a chaque
    run parce qu'il decrit l'etat mesure de la base, et non le journal du run.
    """
    mirror = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rfc_mirror"
    )
    tool = LocalRFCIngestionTool(mirror_dir=mirror)
    logging.info("miroir=%s", mirror)
    db_path = _rag_db_path()
    logging.info("db_path=%s", db_path)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    errors = {}
    treated = 0
    vus = 0
    total_rfc = sum(len(v) for v in CRITICAL_RFCS.values())

    report_lines = [
        "# Audit de Conformité et d'Ingestion des Normes (RFC)",
        "",
        f"**Date:** {stamp}",
        "**Cible:** Base de connaissances Air-Gapped Nokido (World Model)",
        f"**Miroir local:** `{mirror}`",
        f"**Base vérifiée:** `{db_path or 'ILLISIBLE — aucune vérification indépendante'}`",
        "",
        "Chaque norme est ingérée depuis le miroir local (zéro réseau) puis **recomptée",
        "en base** : la colonne « en base » est une mesure indépendante du retour de",
        "l'outil, et non sa paraphrase. `n/d` = la base n'a pas pu être lue (état",
        "ILLISIBLE), ce qui n'est PAS un zéro.",
        "",
    ]

    # --- Phase 1 : ingestion des normes manquantes -------------------------
    # PARALLELE depuis le 2026-09-03. Deux verrous levés d'abord, dans cet ordre :
    #   1. la dedup de `store_chunks` balayait 22,8 Go PAR DOCUMENT (expression
    #      `json_extract` non indexable) — N threads auraient fait N balayages
    #      concurrents sur le meme disque, soit PIRE que le sequentiel ;
    #   2. `_open_db` ouvrait une connexion NUE, donc une transaction implicite
    #      tenant le verrou d'ecriture pendant toute la boucle. Il passe
    #      desormais par `forge_db_path.open_writer` (autocommit + WAL +
    #      busy_timeout, bench « 0 contention / 0 echec » sous N workers).
    # Chaque tache appelle `store_chunks`, qui ouvre SA connexion dans SON thread :
    # une connexion sqlite3 ne se partage pas entre threads.
    a_traiter = []
    for category, rfcs in CRITICAL_RFCS.items():
        if categories and not any(c.lower() in category.lower() for c in categories):
            continue
        for rfc_query in rfcs:
            if limit is not None and len(a_traiter) >= limit:
                break
            source = _rfc_source(rfc_query)
            vus += 1
            _emit_progres(rfc_query, vus, total_rfc)
            already = _count_in_rag(db_path, source)
            if already and not force:
                continue  # idempotent : deja en base, on ne re-vectorise pas
            a_traiter.append(rfc_query)

    logging.info("phase 1 : %d norme(s) a ingerer sur %d ciblees, %d worker(s)",
                 len(a_traiter), total_rfc, workers)

    def _une(rfc_query):
        logging.info("[%s] ingestion...", rfc_query)
        try:
            return rfc_query, tool.process_and_ingest(rfc_query)
        except Exception as exc:  # noqa: BLE001
            # Un thread qui leve doit rendre un ETAT, pas disparaitre : sans ca
            # l'echec d'une norme serait invisible dans le rapport.
            return rfc_query, {"status": "error",
                               "message": "%s: %s" % (type(exc).__name__, exc)}

    if workers > 1 and a_traiter:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_une, q) for q in a_traiter]
            for fini, fut in enumerate(as_completed(futures), 1):
                rfc_query, result = fut.result()
                logging.info("[%s] resultat = %s", rfc_query, result.get("status"))
                _emit_progres("ingestion %s" % rfc_query, fini, len(a_traiter))
                treated += 1
                if result.get("status") != "success":
                    errors[rfc_query] = result.get("message", "Erreur inconnue")
    else:
        for fini, rfc_query in enumerate(a_traiter, 1):
            rfc_query, result = _une(rfc_query)
            logging.info("[%s] resultat = %s", rfc_query, result.get("status"))
            _emit_progres("ingestion %s" % rfc_query, fini, len(a_traiter))
            treated += 1
            if result.get("status") != "success":
                errors[rfc_query] = result.get("message", "Erreur inconnue")

    # --- Phase 2 : rapport construit depuis la BASE, pas depuis le run -----
    total_rfcs = 0
    present_rfcs = 0
    total_chunks = 0
    unverified = 0

    for category, rfcs in CRITICAL_RFCS.items():
        report_lines.append(f"## {category}")
        report_lines.append("")

        for rfc_query in rfcs:
            total_rfcs += 1
            source = _rfc_source(rfc_query)
            in_db = _count_in_rag(db_path, source)

            if in_db is None:
                unverified += 1
                report_lines.append(
                    f"- ❔ **{rfc_query}** : état inconnu — la base n'a pas pu être lue "
                    "(ce n'est PAS un zéro)."
                )
            elif in_db > 0:
                present_rfcs += 1
                total_chunks += in_db
                report_lines.append(f"- ✅ **{rfc_query}** : {in_db} chunk(s) en base (`source={source}`).")
            elif rfc_query in errors:
                report_lines.append(f"- ❌ **{rfc_query}** : absente de la base.")
                report_lines.append(f"  - *Raison :* {errors[rfc_query]}")
            else:
                report_lines.append(
                    f"- ⬜ **{rfc_query}** : absente de la base, non traitée par ce run "
                    "(relancer avec `--category` / `--limit`)."
                )

        report_lines.append("")

    report_lines.append("## Synthèse de l'Audit")
    report_lines.append(f"- **Normes ciblées :** {total_rfcs}")
    report_lines.append(f"- **Normes présentes en base :** {present_rfcs}")
    report_lines.append(f"- **Chunks RFC en base :** {total_chunks}")
    report_lines.append(f"- **Normes traitées par ce run :** {treated}")
    if errors:
        report_lines.append(f"- **Échecs de ce run :** {len(errors)}")
    if unverified:
        report_lines.append(
            f"- **⚠️ Non vérifiables :** {unverified} — base illisible, état inconnu."
        )
    report_lines.append("")
    report_lines.append(
        "> Les chunks sont stockés TEXT-ONLY ; les vecteurs sont remplis en asynchrone "
        "par `forge_embed_auto_trigger`. « En base » ne veut donc pas encore dire « vectorisé »."
    )

    report_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs", "AUDIT_RFC_COMPLIANCE.md"))
    # `docs/` n'est pas ecrivable par le compte sandbox : le run du 2026-09-03 a
    # ingere 31 normes en 4 s puis est sorti en rc=1 sur CETTE ligne. Un travail
    # reussi ne doit pas etre rapporte comme un echec a cause d'un artefact
    # secondaire — on se replie, et on le DIT.
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
    except OSError as exc:
        repli = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "sandbox", "AUDIT_RFC_COMPLIANCE.md"))
        os.makedirs(os.path.dirname(repli), exist_ok=True)
        with open(repli, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        logging.warning("%s non ecrivable (%s) — rapport ecrit dans %s",
                        report_path, type(exc).__name__, repli)
        report_path = repli

    logging.info("Audit terminé. Rapport généré dans : %s", report_path)
    return {
        "targeted": total_rfcs,
        "present": present_rfcs,
        "chunks": total_chunks,
        "treated": treated,
        "errors": errors,
        "unverified": unverified,
    }

def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Audit de conformité RFC (miroir local air-gapped).")
    ap.add_argument("--category", action="append", default=None,
                    help="Filtre par sous-chaîne de catégorie (répétable). Défaut : toutes.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Nombre max de normes ingérées dans ce run (l'appel MCP est capé).")
    ap.add_argument("--force", action="store_true",
                    help="Ré-ingère même les normes déjà présentes en base.")
    ap.add_argument("--log", default=None,
                    help="Fichier de trace (defaut C:/tmp/audit_rfc_compliance.log).")
    ap.add_argument("--workers", type=int, default=4,
                    help="Ingestions simultanees (defaut 4 ; 1 = sequentiel). "
                         "Sur ce chemin le travail est I/O (lecture du miroir, "
                         "ecriture SQLite), donc les threads relachent le GIL.")
    args = ap.parse_args(argv)

    # Trace FICHIER avec flush : un run prive tue au timeout perd sa sortie stdout.
    # Sans elle, un blocage est indiscernable d'un run qui n'a jamais demarre.
    log_path = args.log or os.environ.get("NOKIDO_AUDIT_LOG") or r"C:\tmp\audit_rfc_compliance.log"
    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(handler)
    except Exception as exc:
        logging.warning("Trace fichier indisponible (%s) : %s", log_path, exc)
    logging.info(
        "=== run categories=%s limit=%s force=%s user=%s ===",
        args.category, args.limit, args.force, os.environ.get("USERNAME"),
    )

    summary = run_audit(categories=args.category, limit=args.limit,
                        force=args.force, workers=args.workers)
    logging.info("=== fin run : %s ===", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())