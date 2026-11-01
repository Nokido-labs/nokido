"""forge_acp_epingler.py -- l'OWNER epingle la cle PUBLIQUE du hub pour le worker ACP.

A lancer sous le compte OWNER (celui du worker, jamais SYSTEM). La cle publique est demandee AU HUB
(port :8766, tenu par le hub). AVANT tout epinglage, l'IDENTITE de l'ecouteur est PROUVEE (prouver_hub) :
  (1) le pid qui ecoute sur 127.0.0.1:8766 (psutil.net_connections, LISTEN) -- unique, lisible ;
  (2) son compte : jamais LaForgeSbx* (bac a sable). NokidoMCP n'a pas de runAs dans proxy_deno/core/services.toml :
      il tourne sous le compte du superviseur, et c'est ce compte qu'on lit (aucun compte n'est suppose) ;
  (3) sa preuve de service : le superviseur le designe lui-meme (preuve « superviseur », identifier_processus).
Identite non prouvee OU illisible (acces refuse, pid recycle, absent) = REFUS, jamais un epinglage « au mieux ».
L'empreinte (sha256 de la cle publique brute) est affichee A COTE du pid, du compte et du service prouves.
L'epingle {kid, x} est ecrite au coffre PERSONNEL (keyring WCM), jamais au coffre machine.
--dry-run PAR DEFAUT : --ecrire pour ecrire reellement.

Le hub n'expose pas encore cette cle : route minimale a ajouter, voir docs/enquetes/acp_worker_20261028.md
(GET /.well-known/acp-jwks.json -> {"keys":[{"kty":"OKP","crv":"Ed25519","x":...,"kid":...,"alg":"EdDSA","use":"sig"}]}).
Aucune cle privee n'est lue ni affichee ici.
"""
from __future__ import annotations

import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
_TOOLS = str(_Path_amorce(__file__).resolve().parent)
if _TOOLS not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _TOOLS)

__FORGE_COLOR__ = "immunitaire/epingle la cle publique du hub pour le worker ACP (coffre personnel)"

import argparse
import json
import urllib.request

import forge_acp_hub as H

URL_DEFAUT = "http://127.0.0.1:8766/.well-known/acp-jwks.json"
PORT_HUB = 8766
SERVICE_HUB = "NokidoMCP"
PREFIXE_BAC_A_SABLE = "laforgesbx"


class IdentiteNonProuvee(Exception):
    """L'ecouteur n'est pas prouve comme le hub (ou sa preuve est illisible) : on n'epingle rien."""


def _http(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 -- loopback uniquement (verifie par epingler)
        return r.read(65536).decode("utf-8")


def _ecrire_coffre_personnel(nom: str, valeur: str) -> bool:
    from nokido_agent.app.forge_env_crypt import _keyring_set
    return bool(_keyring_set(nom, valeur))


def _reseau_default():
    """[(pid, ip, port)] des sockets LISTEN en tcp. Une erreur d'acces remonte (ILLISIBLE)."""
    import psutil
    out = []
    for c in psutil.net_connections(kind="tcp"):
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        out.append((c.pid, c.laddr.ip, c.laddr.port))
    return out


def _proc_default(pid):
    """Compte, date de creation, nom d'un pid. Acces refuse -> PermissionError ; pid absent -> LookupError."""
    import psutil
    try:
        p = psutil.Process(pid)
        return {"user": p.username(), "cree": p.create_time(), "nom": p.name()}
    except psutil.AccessDenied as e:
        raise PermissionError(str(e)) from e
    except psutil.NoSuchProcess as e:
        raise LookupError(str(e)) from e


def _pid_service_superviseur() -> dict:
    """pid -> nom de service, tel que le SUPERVISEUR le declare (forge_process_inventory._declares). Superviseur
    injoignable = RuntimeError (ILLISIBLE, donc refus en amont), jamais {} pris pour « aucun service »."""
    import forge_process_inventory as PI
    d = PI._declares()
    if "__erreur__" in d:
        raise RuntimeError(str(d["__erreur__"].get("status") or "superviseur illisible"))
    return {int(v["pid"]): n for n, v in d.items()
            if isinstance(v, dict) and isinstance(v.get("pid"), int) and not isinstance(v.get("pid"), bool)}


def _inventaire_default(pid):
    """{identite, preuve} pour le pid, via forge_process_inventory.identifier_processus (signature reelle :
    vivants, pid_service, jobs, battements). None si non identifie par le superviseur."""
    import forge_process_inventory as PI
    import psutil
    vivants, anc, vu = {}, pid, 0
    while anc is not None and anc not in vivants and vu < 16:
        try:
            p = psutil.Process(anc)
            vivants[anc] = {"nom": p.name(), "ppid": p.ppid(), "cree": p.create_time(), "user": p.username()}
        except psutil.Error:
            break
        anc, vu = p.ppid(), vu + 1
    ids, _non = PI.identifier_processus(vivants, _pid_service_superviseur(), PI._jobs_par_pid(),
                                        PI._battements_par_pid())
    return ids.get(pid)


def prouver_hub(port: int = PORT_HUB, reseau=None, proc=None, inventaire=None) -> dict:
    """Identite PROUVEE de l'ecouteur 127.0.0.1:port : {pid, compte, service, cree}. Sinon IdentiteNonProuvee."""
    try:
        conns = (reseau or _reseau_default)()
    except Exception as e:  # noqa: BLE001 -- table illisible = ILLISIBLE, pas un oui
        raise IdentiteNonProuvee("table reseau illisible : %s" % e) from e
    pids = {c[0] for c in conns if c[1] == "127.0.0.1" and c[2] == port}
    if None in pids or len(pids) != 1:
        raise IdentiteNonProuvee("ecouteur 127.0.0.1:%d : %d pid(s) (exige : un seul, lisible)" % (port, len(pids)))
    pid = pids.pop()
    try:
        p1 = (proc or _proc_default)(pid)
    except Exception as e:  # noqa: BLE001 -- acces refuse / pid absent = ILLISIBLE
        raise IdentiteNonProuvee("pid %s illisible : %s" % (pid, e)) from e
    user = str(p1.get("user") or "")
    if not user or user.lower().startswith(PREFIXE_BAC_A_SABLE):
        raise IdentiteNonProuvee("pid %s : compte '%s' refuse (vide ou bac a sable)" % (pid, user))
    try:
        ident = (inventaire or _inventaire_default)(pid)
    except Exception as e:  # noqa: BLE001
        raise IdentiteNonProuvee("pid %s : preuve superviseur illisible : %s" % (pid, e)) from e
    if not ident or ident.get("preuve") != "superviseur" or ident.get("identite") != SERVICE_HUB:
        raise IdentiteNonProuvee("pid %s : pas designe par le superviseur comme %s" % (pid, SERVICE_HUB))
    try:
        p2 = (proc or _proc_default)(pid)
    except Exception as e:  # noqa: BLE001
        raise IdentiteNonProuvee("pid %s : relecture illisible : %s" % (pid, e)) from e
    if p2.get("cree") != p1.get("cree"):
        raise IdentiteNonProuvee("pid %s recycle pendant la preuve" % pid)
    return {"pid": pid, "compte": user, "service": SERVICE_HUB, "cree": p1.get("cree")}


def choisir_cle(texte: str):
    """(kid, octets publics) depuis un JWKS ; ValueError si aucune cle Ed25519 exploitable."""
    try:
        for k in json.loads(texte).get("keys", []):
            if k.get("kty") == "OKP" and k.get("crv") == "Ed25519" and isinstance(k.get("kid"), str):
                pub = H.b64url_decode(k["x"])
                if len(pub) == 32:
                    return k["kid"], pub
    except (ValueError, AttributeError, KeyError, TypeError) as e:
        raise ValueError("reponse du hub illisible comme JWKS (%s)" % type(e).__name__) from e
    raise ValueError("aucune cle Ed25519 exploitable dans la reponse du hub")


def epingler(url=URL_DEFAUT, ecrire=False, http=None, coffre=None, prouver=None):
    """Rend (kid, empreinte, ecrit, identite). Identite PROUVEE avant ET apres la lecture ; n'ecrit que si ecrire=True."""
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("le hub se joint en loopback uniquement")
    prouve = prouver or (lambda _u: prouver_hub())
    ident = prouve(url)
    kid, pub = choisir_cle((http or _http)(url))
    if prouve(url) != ident:
        raise IdentiteNonProuvee("ecouteur change entre la preuve et la lecture de la cle : rien n'est epingle")
    emp = H.empreinte(pub)
    ecrit = False
    if ecrire:
        valeur = json.dumps({"kid": kid, "x": H.b64url_encode(pub)}, sort_keys=True)
        ecrit = (coffre or _ecrire_coffre_personnel)(H.EPINGLE_NOM, valeur)
        if not ecrit:
            raise RuntimeError("epingle non ecrite au coffre personnel")
    return kid, emp, ecrit, ident


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=URL_DEFAUT)
    ap.add_argument("--ecrire", action="store_true", help="ecrire l'epingle (sinon --dry-run)")
    a = ap.parse_args(argv)
    try:
        kid, emp, ecrit, ident = epingler(a.url, ecrire=a.ecrire)
    except IdentiteNonProuvee as e:
        print("REFUS (identite non prouvee) : %s" % e)
        return 1
    except Exception as e:  # noqa: BLE001
        print("ECHEC : %s" % e)
        return 1
    print("kid        : %s" % kid)
    print("empreinte  : sha256:%s" % emp)
    print("ecouteur   : pid %s | compte %s | service %s (prouve par le superviseur)"
          % (ident["pid"], ident["compte"], ident["service"]))
    print("epingle ecrite au coffre personnel" if ecrit else "DRY-RUN : rien ecrit (relancer avec --ecrire apres comparaison)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
