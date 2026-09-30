#!/usr/bin/env python
"""forge_mtls_probe.py -- preuve REELLE du handshake mTLS, sur un port ISOLE.

Ne touche ni :8443, ni le hub, ni la configuration Caddy de production. Ce module
monte son PROPRE serveur TLS ephemere sur 127.0.0.1:8444, avec un upstream echo
inoffensif, et rend un verdict par cas.

Ce qui est prouve ici -- et ce qui ne l'est PAS :

  - Un handshake reussi ne prouve rien TOUT SEUL. Ce sont les REFUS qui prouvent :
    sans certificat, mauvaise CA, mauvaise cle privee. Les trois sont obligatoires.
  - Un code HTTP n'est JAMAIS une preuve de mTLS. RFC 8705 place l'authentification
    du client PENDANT le handshake ; un 403 applicatif prouverait meme le contraire
    (la connexion aurait ete etablie). Le verdict se lit sur l'exception TLS et sur
    le certificat effectivement RECU cote serveur.
  - Trois etats, jamais deux : PASS / REFUSED / ILLISIBLE. Un essai qui n'a pas pu
    etre mene (dependance absente, fichier illisible) ne vaut pas un refus, sinon on
    lit une panne d'outil comme une securite.

Usage :  LAFORGE_PYTHON tools/forge_mtls_probe.py [--port 8444] [--json]
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/preuve-handshake-mtls"

import argparse
import json
import os
import ssl
import sys
import threading
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TLS = ROOT / "sandbox" / "tls"
SRV_CERT = TLS / "cert.pem"
SRV_KEY = TLS / "key.pem"
CA_CERT = TLS / "clients_ca.pem"
CLIENTS = TLS / "clients"

# Borne de l'essai CLIENT. Nommee, pas enfouie : une borne doit dire COMBIEN.
# Mesure du 2026-09-19 : en suite complete (10 823 tests, ~18 min), deux essais
# ont depasse 10 s et sont sortis en `TimeoutError` -> `ILLISIBLE`, alors que les
# memes passent 24/24 en isolation. Ce n'est PAS un refus : un ILLISIBLE dit
# « je n'ai pas pu regarder », jamais « le serveur a accepte ».
TIMEOUT_CLIENT_S = float(os.environ.get("LAFORGE_MTLS_TIMEOUT_S", "10"))

# Le serveur de test ne parle QUE au loopback : aucune surface LAN n'est ouverte.
BIND = "127.0.0.1"

# JAMAIS sous pytest : reconfigurer le flux de CAPTURE le referme pour les tests
# suivants du meme worker xdist (mesure 2026-09-04).
if "pytest" not in sys.modules:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001  # muet-ok : confort console, jamais un verdict
            pass


def _log(m: str) -> None:
    print(m, flush=True)


# --------------------------------------------------------------------------- #
# Serveur de test
# --------------------------------------------------------------------------- #

def _san_uri(peercert: dict | None) -> str:
    """Rend l'URI SAN du certificat client, ou "" si le certificat n'en porte pas.

    C'est l'identite de TRANSPORT (urn:nokido:agent:<AGENT>). Elle ne vaut que si
    le handshake l'a verifiee : un SAN lu sur un certificat non valide ne serait
    qu'une chaine fournie par le pair.
    """
    if not peercert:
        return ""
    for typ, val in peercert.get("subjectAltName", ()):
        if typ == "URI":
            return val
    return ""


def _serveur(port: int, journal: list, srv_cert: Path | None = None,
             srv_key: Path | None = None, ca: Path | None = None):
    """Monte le serveur mTLS. `journal` recoit un evenement par connexion.

    Les chemins sont PARAMETRABLES pour que le test puisse fabriquer sa propre CA
    en `tmp_path` : un test qui dependrait du materiel TLS reel de la machine ne
    serait pas hermetique, et il passerait au vert sur une machine sans mTLS.
    `port=0` laisse l'OS choisir -- lire ensuite `srv.server_address[1]`.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(srv_cert or SRV_CERT), str(srv_key or SRV_KEY))
    # LE POINT CENTRAL : le serveur EXIGE un certificat client, et il le verifie
    # contre la CA Nokido. CERT_OPTIONAL accepterait une absence en silence.
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(str(ca or CA_CERT))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802
            peer = self.connection.getpeercert()
            san = _san_uri(peer)
            entete = self.headers.get("X-Agent-Name") or ""
            journal.append({"evenement": "connexion", "san": san, "entete": entete,
                            "sujet": str(peer.get("subject", "")) if peer else ""})
            corps = json.dumps({"san": san, "x_agent_name": entete}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def log_message(self, *a):  # silence : le journal, c'est `journal`
            pass

    class Serveur(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # Un handshake refuse remonte ICI. C'est la preuve cote SERVEUR du
            # refus, complementaire de l'exception vue par le client.
            exc = sys.exc_info()[1]
            journal.append({"evenement": "refus_serveur", "erreur": type(exc).__name__,
                            "detail": str(exc)[:200]})

    srv = Serveur((BIND, port), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --------------------------------------------------------------------------- #
# Essais client
# --------------------------------------------------------------------------- #

def _essai(port: int, cert: Path | None, cle: Path | None, entete: str | None = None,
           verifier_serveur: bool = True, ancre_serveur: Path | None = None) -> tuple[str, str]:
    """Un essai client. Rend (verdict, detail) avec verdict PASS / REFUSED / ILLISIBLE."""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if verifier_serveur:
            # Identite du SERVEUR (RFC 9525). Le certificat est auto-signe : il est
            # sa propre ancre. Si le nom ne correspond pas, on veut le SAVOIR.
            ctx.load_verify_locations(str(ancre_serveur or SRV_CERT))
            ctx.check_hostname = True
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if cert is not None:
            # Une paire cert/cle incoherente echoue ICI, AVANT tout handshake :
            # on ne peut pas presenter un certificat dont on n'a pas la cle. C'est
            # la preuve de possession de RFC 8705, et elle est STRUCTURELLE.
            ctx.load_cert_chain(str(cert), str(cle))
    except ssl.SSLError as e:
        return "REFUSED", "paire cert/cle rejetee au chargement : %s" % str(e)[:160]
    except OSError as e:
        return "ILLISIBLE", "fichier inaccessible : %s" % str(e)[:160]

    conn = None
    try:
        conn = http.client.HTTPSConnection(BIND, port, context=ctx,
                                           timeout=TIMEOUT_CLIENT_S)
        entetes = {"X-Agent-Name": entete} if entete else {}
        conn.request("GET", "/", headers=entetes)
        rep = conn.getresponse()
        corps = rep.read().decode("utf-8", "replace")
        # Le code HTTP n'est PAS le verdict : il n'est atteint que parce que le
        # handshake a deja reussi. On le rapporte comme detail, jamais comme preuve.
        return "PASS", corps
    except ssl.SSLError as e:
        return "REFUSED", "%s: %s" % (type(e).__name__, str(e)[:160])
    except ConnectionResetError as e:
        # Windows coupe souvent la connexion au lieu d'emettre une alerte lisible :
        # c'est bien un refus TLS, il faut juste ne pas le lire comme une panne.
        return "REFUSED", "reset au handshake (refus cote serveur) : %s" % str(e)[:120]
    except OSError as e:
        return "ILLISIBLE", "%s: %s" % (type(e).__name__, str(e)[:160])
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001  # muet-ok : fermeture best-effort
                pass


def _ca_etrangere(dossier: Path) -> tuple[Path, Path] | None:
    """Fabrique une CA + un certificat client SIGNE PAR ELLE (l'attaquant).

    Rend None si `cryptography` manque : ce cas doit alors sortir ILLISIBLE, jamais
    REFUSED -- une dependance absente n'est pas une securite.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        return None
    import datetime as _dt

    dossier.mkdir(parents=True, exist_ok=True)
    maintenant = _dt.datetime.now(_dt.timezone.utc)

    ca_cle = ec.generate_private_key(ec.SECP256R1())
    ca_nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA Etrangere (test)")])
    ca = (x509.CertificateBuilder().subject_name(ca_nom).issuer_name(ca_nom)
          .public_key(ca_cle.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(maintenant - _dt.timedelta(minutes=5))
          .not_valid_after(maintenant + _dt.timedelta(hours=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_cle, hashes.SHA256()))

    cl_cle = ec.generate_private_key(ec.SECP256R1())
    cl_nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "VIBE")])
    cl = (x509.CertificateBuilder().subject_name(cl_nom).issuer_name(ca_nom)
          .public_key(cl_cle.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(maintenant - _dt.timedelta(minutes=5))
          .not_valid_after(maintenant + _dt.timedelta(hours=1))
          .add_extension(x509.SubjectAlternativeName(
              [x509.UniformResourceIdentifier("urn:nokido:agent:VIBE")]), critical=False)
          .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]),
                         critical=False)
          .sign(ca_cle, hashes.SHA256()))

    p_cert = dossier / "pirate.pem"
    p_cle = dossier / "pirate.key.pem"
    p_cert.write_bytes(cl.public_bytes(serialization.Encoding.PEM))
    p_cle.write_bytes(cl_cle.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    return p_cert, p_cle


# --------------------------------------------------------------------------- #

def run(port: int = 8444) -> dict:
    resultats: dict[str, str] = {}
    details: dict[str, str] = {}
    journal: list = []

    for chemin in (SRV_CERT, SRV_KEY, CA_CERT):
        if not chemin.exists():
            return {"erreur": "materiel TLS absent : %s" % chemin}

    srv = _serveur(port, journal)
    try:
        # --- identite du serveur (RFC 9525) : mesuree, pas supposee -------------
        v, d = _essai(port, CLIENTS / "vibe.pem", CLIENTS / "vibe.key.pem")
        resultats["server_tls"] = "PASS" if v == "PASS" else "FAIL"
        details["server_tls"] = d
        resultats["client_ca_validation"] = "PASS" if v == "PASS" else "FAIL"
        resultats["VIBE"] = v if v != "PASS" else "PASS"
        details["VIBE"] = d

        # --- cas positifs -------------------------------------------------------
        for agent in ("MAMMOUTH", "ANTIGRAVITY"):
            base = agent.lower()
            v, d = _essai(port, CLIENTS / ("%s.pem" % base), CLIENTS / ("%s.key.pem" % base))
            resultats[agent] = v
            details[agent] = d

        # --- cas negatifs : CE SONT EUX QUI PROUVENT ----------------------------
        v, d = _essai(port, None, None)
        resultats["no_client_cert"] = "REFUSED" if v == "REFUSED" else "FAIL(%s)" % v
        details["no_client_cert"] = d

        pirate = _ca_etrangere(ROOT / "sandbox" / "tls" / "_probe_tmp")
        if pirate is None:
            resultats["wrong_ca"] = "ILLISIBLE"
            details["wrong_ca"] = "cryptography absent : essai NON MENE, pas un refus"
        else:
            v, d = _essai(port, pirate[0], pirate[1])
            resultats["wrong_ca"] = "REFUSED" if v == "REFUSED" else "FAIL(%s)" % v
            details["wrong_ca"] = d

        v, d = _essai(port, CLIENTS / "vibe.pem", CLIENTS / "mammouth.key.pem")
        resultats["wrong_private_key"] = "REFUSED" if v == "REFUSED" else "FAIL(%s)" % v
        details["wrong_private_key"] = d

        # --- liaison d'identite : le SAN est-il LISIBLE et COMPARABLE ? ---------
        avant = len(journal)
        v, d = _essai(port, CLIENTS / "vibe.pem", CLIENTS / "vibe.key.pem",
                      entete="CLAUDE")
        vus = [e for e in journal[avant:] if e.get("evenement") == "connexion"]
        if v == "PASS" and vus:
            san = vus[-1]["san"]
            entete = vus[-1]["entete"]
            coherent = san.endswith(":VIBE") and entete == "CLAUDE"
            resultats["identity_available"] = "PASS" if coherent else "FAIL"
            details["identity_available"] = "SAN=%s vs X-Agent-Name=%s -> incoherence %s" % (
                san, entete, "DETECTABLE" if coherent else "NON detectable")
        else:
            resultats["identity_available"] = "ILLISIBLE"
            details["identity_available"] = d
    finally:
        srv.shutdown()
        srv.server_close()

    resultats["_journal_serveur"] = "%d evenement(s)" % len(journal)
    return {"resultats": resultats, "details": details, "journal": journal}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8444)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    out = run(a.port)
    if "erreur" in out:
        _log("ILLISIBLE : %s" % out["erreur"])
        return 2
    if a.json:
        _log(json.dumps(out, indent=1, ensure_ascii=False))
        return 0

    for cle, val in out["resultats"].items():
        if cle.startswith("_"):
            continue
        _log("%-22s = %s" % (cle, val))
    _log("")
    _log("--- detail (un code HTTP n'est PAS une preuve de mTLS) ---")
    for cle, val in out["details"].items():
        _log("  %-22s %s" % (cle, str(val)[:150]))
    for e in out["journal"]:
        _log("  [serveur] %s" % json.dumps(e, ensure_ascii=False)[:170])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
