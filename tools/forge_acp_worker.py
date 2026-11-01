"""
forge_acp_worker.py -- le hub ouvre/pilote des sessions ACP sous le compte OWNER.

Service NokidoAcpWorker (runAs=interactive) : seul contexte qui voit les CLI npm et leur login.
Patron de tools/forge_harness_worker.py : file sandbox/acp_jobs/<id>.json -> .started -> .result.json + .done,
pouls beat_daemon, veto de sommeil. Differences voulues :
  - UN ACPRouter vivant, garde entre les jobs (une session ACP survit au job qui l'a ouverte) ;
  - chaque job dans SON thread : un tour long ne bloque ni les autres sessions ni la file ;
  - AUTHENTIFICATION de chaque job (JWS compact EdDSA, cle PUBLIQUE epinglee au coffre personnel, horodatage,
    nonce, cf. forge_acp_hub) AVANT toute execution : sandbox/acp_jobs est ecrivable par des comptes bac a sable,
    un job non signe ne s'execute jamais ; sans epingle, tout est refuse ;
  - cwd TOUJOURS celui de _route_worktree (acp_<cli>) ; mode = MODES_SURS ; permissions = politique_owner
    (decision de l'owner via /acp, jamais d'auto-accept) ; resultat caviarde (non signe : le worker n'a aucun secret).
Job : JWS compact, charge utile {"id","op","params","ts","nonce"} ; ops : ouvrir | envoyer | fermer | lister.
ouvrir accepte `profil` (projet | nu | complet, cf. forge_acp_router) ; le profil est journal dans la session.
"""
from __future__ import annotations

import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "locomoteur/worker ACP owner, ouvre et pilote les sessions ACP du hub"

import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

try:
    import forge_acp_hub as H
    import forge_acp_router as R
except ImportError:
    _tools = str(Path(__file__).resolve().parent)
    if _tools not in sys.path:
        sys.path.insert(0, _tools)
    import forge_acp_hub as H
    import forge_acp_router as R

ROOT = Path(__file__).resolve().parent.parent
JOBS = H.JOBS
NONCES = ROOT / "sandbox" / "acp_worker.nonces"
HEARTBEAT = ROOT / "sandbox" / "acp_worker.heartbeat"
_SERVICE = "NokidoAcpWorker"
_VETO_S = 600.0
_TIMEOUT_MAX_S = 3600.0
_ID = re.compile(r"^[0-9a-f]{32}$")
_log = logging.getLogger("acp_worker")


_POINTEUR = re.compile(r"^tasks\.db:([A-Za-z0-9_.\-]{1,80})$")


def _consigne_pointeur(texte: str) -> str:
    """Convention de prompt par POINTEUR : `tasks.db:<task_id>` -> consigne courte (lecture seule), la description
    de la tache n'est jamais recopiee dans le prompt. Tout autre texte passe tel quel."""
    m = _POINTEUR.match(texte.strip())
    if not m:
        return texte
    # chemin ABSOLU : l'agent tourne dans le worktree acp_<cli>, qui n'a pas de sandbox/tasks.db
    return "Lis la tâche %s dans %s (lecture seule) et exécute-la." % (m.group(1), (ROOT / "sandbox" / "tasks.db").as_posix())


class _Refus(Exception):
    """Refus de politique : le job est authentique mais sa demande sort du cadre."""


def _bootstrap():
    app = str(ROOT / "app")
    if os.path.isdir(app) and app not in sys.path:
        sys.path.append(app)


def _heartbeat(**extra):
    _bootstrap()
    from nokido_agent.app.forge_heartbeat import beat_daemon
    beat_daemon("acp_worker", **extra)


def _poser_veto(nom, duree_s=_VETO_S):
    _bootstrap()
    from nokido_agent.app.forge_resource_manager import poser_veto_sommeil
    poser_veto_sommeil(_SERVICE, "session ACP en vol : %s" % nom, duree_s)


def _lever_veto():
    _bootstrap()
    from nokido_agent.app.forge_resource_manager import lever_veto_sommeil
    lever_veto_sommeil(_SERVICE)


def _lire_coffre_personnel(nom):
    """Keyring du COMPTE COURANT (WCM), le meme que le worker ecrit-lit sous l'owner. Jamais le guichet.
    28/10 : `_keyring_get` avale l'ImportError -- on importe d'abord, pour qu'un keyring ABSENT de l'interpreteur
    (env nokido_services, mesure) remonte en ILLISIBLE au lieu d'une epingle « absente »."""
    try:
        import keyring  # noqa: F401
    except ImportError as e:
        raise RuntimeError("module keyring absent de cet interpreteur (%s)" % sys.executable) from e
    _bootstrap()
    from nokido_agent.app.forge_env_crypt import _keyring_get
    return _keyring_get(nom)


_VARIABLES_DE_PROFIL = ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "HOME", "PATH",
                        "USERNAME", "USERDOMAIN", "TEMP", "TMP", "SystemRoot", "ComSpec", "PATHEXT")


def diag_environnement() -> dict:
    """Diagnostic de demarrage (28/10, recette : CLI claude rc=1 muet sous le lanceur runas) : NOMS des variables
    d'environnement, jamais leurs valeurs ; variables de profil presentes/absentes ; commande resolue du CLI."""
    import getpass
    noms = sorted(os.environ)
    absentes = [v for v in _VARIABLES_DE_PROFIL if v not in os.environ]
    try:
        cmd = R._client._resolve_cmd("claude")
    except Exception as e:  # noqa: BLE001 -- resolution impossible : la dire
        cmd = "ILLISIBLE (%s)" % type(e).__name__
    try:
        compte = getpass.getuser()
    except Exception as e:  # noqa: BLE001
        compte = "ILLISIBLE (%s)" % type(e).__name__
    return {"noms": noms, "exe": sys.executable, "compte": compte, "cmd_claude": cmd,
            "profil": {"absentes": absentes, "presentes": [v for v in _VARIABLES_DE_PROFIL if v in os.environ]}}


_RAISON_EPINGLE = [""]


def raison_epingle() -> str:
    """Pourquoi la derniere lecture d'epingle n'a rien rendu (ABSENTE, ILLISIBLE...), vide si elle a reussi."""
    return _RAISON_EPINGLE[0]


def epingle_coffre():
    """{kid: octets de la cle publique} depuis l'epingle du coffre personnel, ou None (-> tout refuse)."""
    _RAISON_EPINGLE[0] = ""
    try:
        brut = _lire_coffre_personnel(H.EPINGLE_NOM)
    except Exception as e:  # noqa: BLE001 -- coffre illisible : UNKNOWN, pas NO
        _RAISON_EPINGLE[0] = "epingle ILLISIBLE : %s" % str(e)[:200]
        return None
    if not brut:
        _RAISON_EPINGLE[0] = "epingle ABSENTE du coffre personnel (%s)" % H.EPINGLE_NOM
        return None
    try:
        d = json.loads(brut)
        pub = H.b64url_decode(d["x"])
    except Exception as e:  # noqa: BLE001
        _RAISON_EPINGLE[0] = "epingle ILLISIBLE (forme : %s)" % type(e).__name__
        return None
    if not isinstance(d.get("kid"), str) or len(pub) != 32:
        _RAISON_EPINGLE[0] = "epingle ILLISIBLE (kid ou cle de taille invalide)"
        return None
    return {d["kid"]: pub}


def _ecrire_atomique(chemin: Path, texte: str):
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(texte, encoding="utf-8")
    os.replace(tmp, chemin)


class AcpWorker:
    def __init__(self, router=None, jobs_dir=None, epingle_fn=None, now=time.time, ttl_s=H.TTL_S, nonce_path=None,
                 battre=None, veto=None, lever=None):
        self.router = router or R.ACPRouter(permission_policy=R.politique_owner())
        self.jobs = Path(jobs_dir) if jobs_dir is not None else JOBS
        self._epingle_fn = epingle_fn or epingle_coffre
        self._now = now
        self.ttl_s = ttl_s
        self._nonce_path = Path(nonce_path) if nonce_path is not None else NONCES
        self._battre = battre or _heartbeat
        self._veto = veto or _poser_veto
        self._lever = lever or _lever_veto
        self._lock = threading.Lock()
        self._threads = {}
        self._nonces = self._charger_nonces()
        self._veto_pose = False

    # ---- anti-rejeu : registre persiste, relu au redemarrage ----
    def _charger_nonces(self):
        vus = {}
        try:
            for ligne in self._nonce_path.read_text(encoding="utf-8").splitlines():
                n, _, ts = ligne.partition(" ")
                if n and ts:
                    vus[n] = float(ts)
        except FileNotFoundError:  # muet-ok : premier job, aucun nonce encore vu
            pass
        except (OSError, ValueError) as e:
            # 28/10 : registre illisible ou corrompu = anti-rejeu PERDU ; le dire (la fenetre TTL reste la borne)
            _log.warning("[acp_worker] registre des nonces ILLISIBLE (%s) : anti-rejeu reduit a la fenetre TTL",
                         type(e).__name__)
        return vus

    def _consommer_nonce(self, nonce, ts) -> bool:
        """True si neuf (et note). Appele APRES la verification de signature : un inconnu ne peut pas empoisonner le registre."""
        with self._lock:
            now = self._now()
            for n in [n for n, t in self._nonces.items() if abs(now - t) > 2 * self.ttl_s]:
                del self._nonces[n]
            if nonce in self._nonces:
                return False
            self._nonces[nonce] = float(ts)
            try:
                self._nonce_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._nonce_path, "a", encoding="utf-8") as f:
                    f.write("%s %s\n" % (nonce, ts))
            except OSError:
                _log.warning("registre de nonces non ecrit", exc_info=True)
        return True

    def authentifier(self, jws, stem):
        """(ok, raison, corps). Verification EdDSA avec la cle publique EPINGLEE ; sans epingle, tout est refuse."""
        try:
            epingle = self._epingle_fn()
        except Exception:  # noqa: BLE001
            epingle = None
        ok, raison, corps = H.verifier(jws, epingle, self._now(), self.ttl_s)
        if not ok:
            if not epingle and raison_epingle():
                raison = "%s -- %s" % (raison, raison_epingle())
                _log.warning("[acp_worker] %s", raison)
            return False, raison, None
        if corps["id"] != stem or not _ID.match(stem):
            return False, "identifiant du job different du nom de fichier", None
        if not self._consommer_nonce(corps["nonce"], corps["ts"]):
            return False, "rejeu : nonce deja vu", None
        return True, "", corps

    # ---- file ----
    def _finir(self, stem, res):
        res = R._caviarder(res) if isinstance(res, dict) else {"ok": False}
        res = {k: v for k, v in res.items() if k != "sig"}  # plus de HMAC : le worker n'a aucun secret
        _ecrire_atomique(self.jobs / (stem + ".result.json"), json.dumps(res, ensure_ascii=False))
        (self.jobs / (stem + ".done")).write_text("1", encoding="utf-8")

    def scan(self) -> int:
        """Prend les jobs en attente (non bloquant). Authentifie dans le fil de scan, execute dans un fil dedie."""
        self.jobs.mkdir(parents=True, exist_ok=True)
        pris = 0
        for jf in sorted(self.jobs.glob("*.json")):
            if jf.name.endswith(".result.json"):
                continue
            stem = jf.name[:-len(".json")]
            started, done = jf.with_suffix(".started"), jf.with_suffix(".done")
            if done.exists():
                continue
            try:
                with open(started, "x", encoding="utf-8") as f:  # prise exclusive : un seul fil par job
                    f.write("1")
            except FileExistsError:  # muet-ok : un autre fil a deja pris ce job (prise exclusive)
                continue
            pris += 1
            try:
                jws = jf.read_text(encoding="utf-8")
            except (OSError, ValueError):
                jws = None
            ok, raison, job = self.authentifier(jws, stem)
            if not ok:
                _log.warning("job %s REFUSE : %s", stem, raison)
                self._finir(stem, {"ok": False, "refus": raison})
                continue
            th = threading.Thread(target=self._fil, args=(stem, job), name="acp-job-" + stem[:8], daemon=True)
            with self._lock:
                self._threads[stem] = th
            th.start()
        return pris

    def _fil(self, stem, job):
        try:
            res = self.executer(job["op"], job["params"])
        except (_Refus, PermissionError) as e:  # PermissionError : session d'un autre appelant (routeur)
            _log.warning("job %s REFUSE : %s", stem, e)
            res = {"ok": False, "refus": str(e)}
        except Exception as e:  # noqa: BLE001
            _log.warning("job %s en echec", stem, exc_info=True)
            res = {"ok": False, "error": repr(e)[:300]}
        try:
            self._finir(stem, res)
        finally:
            with self._lock:
                self._threads.pop(stem, None)

    def en_vol(self) -> int:
        with self._lock:
            return sum(1 for t in self._threads.values() if t.is_alive())

    # ---- ops ----
    def executer(self, op, p: dict) -> dict:
        rt = self.router
        # 28/10 (recette reelle) : l'outil hub `acp` expose sid/prompt (schema du registre) ; le worker parlait
        # session/texte. Les deux vocabulaires sont admis, le nom historique l'emporte s'il est present.
        p = dict(p or {})
        # 29/10 (audit AGY ACP (a)) : l'appelant scelle par le hub devient le proprietaire de la session ; transmis au
        # routeur SEULEMENT s'il est present (un job d'ancien hub garde le comportement d'avant).
        moi = {"proprietaire": p["appelant"]} if p.get("appelant") is not None else {}
        if "session" not in p and "sid" in p:
            p["session"] = p["sid"]
        if "texte" not in p and "prompt" in p:
            p["texte"] = p["prompt"]
        if op == "ouvrir":
            agent = p.get("agent")
            if not isinstance(agent, str) or not agent:
                raise _Refus("agent manquant")
            attendu = Path(rt._route(agent)).resolve()
            cwd = p.get("cwd")
            if cwd is not None and os.path.normcase(str(Path(str(cwd)).resolve())) != os.path.normcase(str(attendu)):
                raise _Refus("cwd hors du worktree acp_%s" % agent)
            mode = p.get("mode")
            if mode is not None and mode != R.MODES_SURS.get(agent):
                raise _Refus("mode non sur pour %s (seul MODES_SURS est admis)" % agent)
            profil = p.get("profil")
            if profil is not None and (not isinstance(profil, str) or profil not in R.PROFILS):
                raise _Refus("profil inconnu : %s (admis : %s)" % (str(profil)[:40], ", ".join(R.PROFILS)))
            # 29/10 (audit AGY ACP (a)) : l'appelant authentifie, scelle par le hub dans le job signe, devient le
            # proprietaire de la session ; envoyer/fermer/lister d'un autre sont refuses par le routeur.
            extra = dict(moi)
            if "isolee" in p:
                if not isinstance(p["isolee"], bool):
                    raise _Refus("isolee doit etre un booleen")
                extra["isolee"] = p["isolee"]
            texte = p.get("texte")
            if texte is None:
                sid = rt.ouvrir(agent, cwd=None, mode=None, modele=p.get("modele"), profil=profil, **extra)
                return {"ok": True, "session": sid}
            if not isinstance(texte, str):
                raise _Refus("prompt invalide")
            texte = _consigne_pointeur(texte)
            try:
                tmo = min(max(float(p.get("timeout", R._client.DEFAULT_TIMEOUT)), 1.0), _TIMEOUT_MAX_S)
            except (TypeError, ValueError):
                raise _Refus("timeout invalide")
            res = rt.ouvrir(agent, cwd=None, mode=None, modele=p.get("modele"), prompt_initial=texte, timeout=tmo,
                            profil=profil, **extra)
            return {"ok": True, "session": res["session"], "reponse": res["reponse"],
                    "reutilisee": bool(res.get("reutilisee", False))}
        if op == "envoyer":
            sid, texte = p.get("session"), p.get("texte")
            if not isinstance(sid, str) or not isinstance(texte, str):
                raise _Refus("session/texte manquants")
            texte = _consigne_pointeur(texte)
            try:
                tmo = min(max(float(p.get("timeout", R._client.DEFAULT_TIMEOUT)), 1.0), _TIMEOUT_MAX_S)
            except (TypeError, ValueError):
                raise _Refus("timeout invalide")
            return {"ok": True, "reponse": rt.envoyer(sid, texte, timeout=tmo, **moi)}
        if op == "fermer":
            sid = p.get("session")
            if not isinstance(sid, str):
                raise _Refus("session manquante")
            rt.fermer(sid, **moi)
            return {"ok": True}
        if op == "lister":
            return {"ok": True, "sessions": rt.lister(**moi)}
        raise _Refus("op inconnue : %s" % str(op)[:40])

    # ---- boucle ----
    def tick(self):
        try:
            self.scan()
        except Exception:  # noqa: BLE001
            _log.warning("tour de surveillance en echec", exc_info=True)
        n = self.en_vol()
        try:
            if n and not self._veto_pose:
                self._veto("%d job(s)" % n)
                self._veto_pose = True
            elif n:
                self._veto("%d job(s)" % n)
            elif self._veto_pose:
                self._lever()
                self._veto_pose = False
        except Exception:  # noqa: BLE001
            _log.warning("veto de sommeil non gere", exc_info=True)
        try:
            purger = getattr(self.router, "purger", None)
            if purger is not None:
                purger()
        except Exception:  # noqa: BLE001
            _log.warning("purge du pool en echec (la boucle continue)", exc_info=True)
        try:
            self._battre(jobs_en_vol=n, sessions=len(self.router.lister()))
        except Exception:  # noqa: BLE001
            _log.warning("pouls en echec (la boucle continue)", exc_info=True)

    def boucle(self, interval=3.0, stop=None):
        stop = stop or threading.Event()
        while not stop.is_set():
            self.tick()
            stop.wait(interval)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s acp_worker %(message)s")
    arg = sys.argv[1] if len(sys.argv) > 1 else "--watch"
    iv = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    try:
        print("[acp_worker] diag " + json.dumps(diag_environnement(), ensure_ascii=False, default=str),
              file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001 -- un diagnostic ne doit jamais empecher le service de demarrer
        print("[acp_worker] diag ILLISIBLE : %s" % type(e).__name__, file=sys.stderr, flush=True)
    w = AcpWorker()
    if arg == "--once":
        print(json.dumps({"pris": w.scan()}))
        return
    w.boucle(iv)


if __name__ == "__main__":
    main()
