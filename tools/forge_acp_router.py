#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_acp_router.py -- routeur ACP multi-sessions (T2).

Une session = un ACPClient (le SEUL client ACP) = un processus agent, cwd = worktree de l'agent.
Chaque evenement session/update, chaque decision de permission est journalise en JSONL
logs/acp_router/<id>.jsonl {ts, session, agent, kind, payload}, payload caviarde (redacteur existant).
Politique de permission : fonction injectable, defaut = cancelled. Aucun branchement tray/owner ici.
`agy` ne parle pas ACP : refus HORS_ACP.

Profil allege (claude uniquement, 28/10 : meme prompt BONJOUR, claude-agent-acp 0.99.0 -- profil complet 53 071
tokens, projet 35 478 (-33 %), nu 26 757 (-50 %)). Transmis par `_meta.claudeCode.options` de session/new ET de
session/load (reprise) :
  - "projet" (DEFAUT) : settingSources project+local, sans skills ni plugins, MCP strict. Garde le CLAUDE.md du projet.
  - "nu" : settingSources vide, sans skills ni plugins, MCP strict.
  - "complet" : aucune option (profil d'avant 28/10).
Profil inconnu : ProfilInconnuError (refus dit, rien lance). Autres agents : profil ignore, dit dans le journal
(evenement `profil_ignore`).

Convention de prompt par POINTEUR (worker, `forge_acp_worker.py`) : un prompt `tasks.db:<task_id>` est remplace par
une consigne courte (lecture seule de sandbox/tasks.db) ; la description de la tache n'est jamais recopiee.

Livraison CLAUDE_HEADLESS f9505b478 (ROUGE 177a1e7ab), integree par governed_edit (le merge gate ne peut pas
creer de fichier dans tools/ : Permission denied).
"""
from __future__ import annotations

import itertools
import json
import logging
import re
import sys
import os
import threading
import time
import uuid
from pathlib import Path

try:
    import forge_acp_client as _client
except ImportError:
    _tools = Path(__file__).resolve().parent
    if str(_tools) not in sys.path:
        sys.path.insert(0, str(_tools))
    import forge_acp_client as _client

__FORGE_COLOR__ = "systeme_nerveux/routeur ACP multi-sessions"

SessionBusyError = _client.SessionBusyError
_log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "acp_router"
HORS_ACP = ("agy",)


class HorsACPError(RuntimeError):
    """HORS_ACP : l'agent ne parle pas ACP."""


class CwdIndisponibleError(RuntimeError):
    """Aucun cwd fourni et aucun worktree d'agent disponible : refus explicite."""


def politique_refus(params) -> dict:
    """Politique par defaut : toute permission est refusee."""
    return {"outcome": "cancelled"}


MODES_SURS = {"claude": "default", "codex": "read-only"}


def _modele_prefere(agent: str):
    """Modele que le CLI de l'owner utilise deja (recette Codex 28/10 : le defaut de codex-acp, gpt-5.5, est refuse
    pour un compte ChatGPT ; le CLI tourne sur le `model` de ~/.codex/config.toml). Seule la cle `model` est lue
    (le fichier porte aussi des serveurs MCP). Absent ou illisible -> None : aucun modele impose."""
    if agent != "codex":
        return None
    chemin = Path(os.environ.get("LAFORGE_CODEX_CONFIG") or (Path.home() / ".codex" / "config.toml"))
    try:
        import tomllib

        with open(chemin, "rb") as f:
            modele = tomllib.load(f).get("model")
    except (OSError, ValueError):
        return None
    return modele if isinstance(modele, str) and modele.strip() else None


def _choisir_modele(voulu: str, annonces: list):
    """Le modeleId annonce qui correspond a `voulu` (exact, ou `voulu[niveau]` -- [medium] de preference)."""
    if voulu in annonces:
        return voulu
    niveaux = [a for a in annonces if isinstance(a, str) and a.startswith(voulu + "[")]
    return f"{voulu}[medium]" if f"{voulu}[medium]" in niveaux else (niveaux[0] if niveaux else None)


PROFIL_DEFAUT = "projet"
PROFILS = {
    "projet": {"settingSources": ["project", "local"], "skills": [], "strictMcpConfig": True, "plugins": []},
    "nu": {"settingSources": [], "skills": [], "strictMcpConfig": True, "plugins": []},
    "complet": None,  # aucune option : profil d'avant 28/10
}


class ProfilInconnuError(RuntimeError):
    """Profil de session inconnu : refus dit, aucun agent lance."""


def _profil_resolu(agent: str, profil):
    """Profil applique a `agent` : None -> PROFIL_DEFAUT. Inconnu -> ProfilInconnuError. Non-claude -> None."""
    voulu = PROFIL_DEFAUT if profil is None else profil
    if not isinstance(voulu, str) or voulu not in PROFILS:
        raise ProfilInconnuError(f"profil inconnu : {voulu!r} (admis : {', '.join(PROFILS)})")
    return voulu if agent == "claude" else None


def _meta_profil(profil):
    """`_meta` de session/new et session/load ; None = aucun (profil complet, ou agent sans profil)."""
    options = PROFILS.get(profil)
    if not options:
        return None
    return {"claudeCode": {"options": dict(options)}}


PERMISSIONS_DIR = ROOT / "sandbox" / "acp_permissions"
SONDAGE_S = 0.2
_PID_RE = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex : seul identifiant que la file produit


def _caviarder(obj):
    """Meme redacteur que les journaux de session : la demande deposee ne garde pas un secret en clair."""
    red = _client._journal_caviarde(lambda m: m)
    brut = json.dumps(obj, ensure_ascii=False, default=str)
    try:
        return json.loads(red(brut))
    except ValueError:
        return red(brut)


def _ecrire_atomique(chemin, obj):
    """Fichier temporaire dans le meme dossier puis os.replace : jamais de JSON a moitie ecrit."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(f".{chemin.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, chemin)


def _lire(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # fichier absent ou en cours de remplacement : nouvelle tentative au sondage


_KINDS_PONCTUELS = ("allow_once", "reject_once")


def options_ponctuelles(options):
    """LISTE BLANCHE des options transmises a l'owner : decisions ponctuelles seules. Decision owner 28/10 :
    « Always Allow » avait inscrit une autorisation PERMANENTE (settings.local.json) qui contournait /acp."""
    return [o for o in (options or []) if isinstance(o, dict) and o.get("kind") in _KINDS_PONCTUELS]


def _decision_valide(decision, options):
    """'selected' valide seulement si optionId annonce par l'agent ; tout le reste = cancelled."""
    annule = {"outcome": "cancelled"}
    if not isinstance(decision, dict) or decision.get("outcome") != "selected":
        return annule
    ids = {o.get("optionId") for o in options if isinstance(o, dict)}
    if decision.get("optionId") in ids:
        return {"outcome": "selected", "optionId": decision["optionId"]}
    return annule


_NONCES_VUS: set = set()
_OP_DECISION = "acp_decision"


def _importer_hub():
    try:
        import forge_acp_hub as H
    except ImportError:
        from tools import forge_acp_hub as H
    return H


def _epingle_defaut():
    """Cle publique epinglee (meme source que forge_acp_worker) ; None -> tout refuse."""
    try:
        try:
            import forge_acp_worker as W
        except ImportError:
            from tools import forge_acp_worker as W
        return W.epingle_coffre()
    except Exception:  # noqa: BLE001
        return None


def signer_hub(payload):
    """Signature par la cle PRIVEE du hub (lisible sous SYSTEM seulement) ; leve RuntimeError sinon."""
    H = _importer_hub()
    cle = H.cle_signature()
    if not cle:
        raise RuntimeError("cle de signature du hub illisible depuis ce compte")
    return H.sceller(_OP_DECISION, payload, cle)


URL_SIGNATURE_HUB = "http://127.0.0.1:8766/acp/sign"


def _post_hub(url, jeton, payload):
    import urllib.request

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + jeton})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 -- loopback verifie par signer_par_hub
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 -- ne jamais citer l'en-tete (jeton) dans l'erreur
        raise RuntimeError(f"hub de signature injoignable ou refus ({type(exc).__name__})") from None


def signer_par_hub(jeton, url=URL_SIGNATURE_HUB, _post=None):
    """signer(payload)->JWS : delegue au hub (SYSTEM, seul lecteur de la cle) qui reverifie le JWT owner.
    Loopback seulement (ValueError sinon). Leve RuntimeError si le hub refuse ou ne repond pas."""
    from urllib.parse import urlsplit

    if urlsplit(url).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("signature : hub loopback uniquement")
    post = _post or _post_hub

    def signer(payload):
        rep = post(url, jeton, payload)
        jws = rep.get("jws") if isinstance(rep, dict) else None
        if not isinstance(jws, str) or jws.count(".") != 2:
            raise RuntimeError("reponse du hub sans JWS")
        return jws

    return signer


def verifier_decision(jws, pid, epingle, ts_demande, now, delai_s, vus):
    """(ok, raison). Signature EdDSA epinglee, op, pid, fenetre [ts_demande, now], nonce jamais vu."""
    H = _importer_hub()
    ok, raison, corps = H.verifier(jws, epingle, now, delai_s + 5)
    if not ok:
        return False, raison, None
    p = corps["params"]
    if corps["op"] != _OP_DECISION or p.get("pid") != pid:
        return False, "decision d'une autre demande", None
    if corps["ts"] < ts_demande - 1 or corps["ts"] > now + 1:
        return False, "decision hors du delai de la demande", None
    if corps["nonce"] in vus:
        return False, "decision rejouee", None
    vus.add(corps["nonce"])
    return True, "", p


def politique_owner(dossier=None, delai_s=300, epingle_fn=None, now=time.time):
    """permission_policy : depose la demande en fichier, attend la decision SIGNEE de l'owner (CLI --decider)."""
    dossier = Path(dossier) if dossier is not None else PERMISSIONS_DIR
    epingle_fn = epingle_fn or _epingle_defaut

    def _decision_signee(j, pid, opts, ts_demande):
        """Decision du fichier si son JWS est valide, sinon cancelled (journalise)."""
        ok, raison, p = verifier_decision(j.get("jws"), pid, epingle_fn(), ts_demande, now(), delai_s, _NONCES_VUS)
        if not ok:
            _log.warning("decision ACP %s refusee : %s", pid, raison)
            return {"outcome": "cancelled"}
        # seule la charge SIGNEE fait foi : le champ `decision` du fichier est ignore
        if p.get("refuser") or p.get("option") is None:
            return {"outcome": "cancelled"}
        return _decision_valide({"outcome": "selected", "optionId": p["option"]}, opts)

    def _pol(params, session=None, agent=None):
        req = params if isinstance(params, dict) else {}
        opts = options_ponctuelles(req.get("options") if isinstance(req.get("options"), list) else [])
        pid = uuid.uuid4().hex
        chemin = dossier / f"{pid}.json"
        ts_demande = now()
        _ecrire_atomique(chemin, {"id": pid, "session": session or req.get("sessionId"), "agent": agent,
                                  "ts": ts_demande, "request": _caviarder(params), "options": opts,
                                  "etat": "EN_ATTENTE", "decision": None})
        limite = time.monotonic() + delai_s
        while time.monotonic() < limite:
            j = _lire(chemin)
            if j and j.get("etat") == "DECIDE":
                return _decision_signee(j, pid, opts, ts_demande)
            time.sleep(min(SONDAGE_S, 1.0))
        j = _lire(chemin)
        if j and j.get("etat") == "DECIDE":
            return _decision_signee(j, pid, opts, ts_demande)
        if j is None:
            j = {"id": pid, "request": _caviarder(params), "options": opts}
        j["etat"] = "EXPIRE"
        j["decision"] = {"outcome": "cancelled"}
        _ecrire_atomique(chemin, j)
        return {"outcome": "cancelled"}

    _pol.accepte_contexte = True
    _pol.delai_s = delai_s
    return _pol


def lister_en_attente(dossier=None):
    dossier = Path(dossier) if dossier is not None else PERMISSIONS_DIR
    out = []
    for p in sorted(dossier.glob("*.json")) if dossier.is_dir() else []:
        j = _lire(p)
        if j and j.get("etat") == "EN_ATTENTE":
            out.append(j)
    return out


def decider(pid, option=None, refuser=False, dossier=None, signer=None, sub="owner"):
    """Tranche une demande EN_ATTENTE. Leve ValueError si introuvable, deja tranchee ou option non annoncee.
    `signer(payload)->JWS` : sans signature la decision est ecrite mais REFUSEE par politique_owner."""
    if not isinstance(pid, str) or not _PID_RE.match(pid):
        # revue 28/10 : « ../x » tranchait un fichier HORS du dossier (traversee prouvee par NR)
        raise ValueError(f"identifiant de demande invalide : {pid!r}")
    dossier = Path(dossier) if dossier is not None else PERMISSIONS_DIR
    chemin = dossier / f"{pid}.json"
    j = _lire(chemin)
    if not j:
        raise ValueError(f"demande introuvable : {pid}")
    if j.get("etat") != "EN_ATTENTE":
        raise ValueError(f"demande {pid} deja {j.get('etat')}")
    if refuser or option is None:
        decision = {"outcome": "cancelled"}
    else:
        ids = {o.get("optionId") for o in j.get("options", []) if isinstance(o, dict)}
        if option not in ids:
            raise ValueError(f"option {option!r} non annoncee ; options : {sorted(map(str, ids))}")
        decision = {"outcome": "selected", "optionId": option}
    if signer is not None:
        j["jws"] = signer({"pid": pid, "option": None if refuser else option, "refuser": bool(refuser or option is None),
                           "sub": sub})
    j["etat"] = "DECIDE"
    j["decision"] = decision
    _ecrire_atomique(chemin, j)
    return decision


def _route_worktree(agent: str) -> str:
    """Worktree PAR ECRIVAIN (decision owner 28/10) : une session ACP interactive est une surface d'ecriture a part,
    nokido_worktrees/acp_<cli>, jamais celui de l'executeur du meme CLI (codex partageait l'arbre de l'executeur
    Codex : une session /acp et une tache deleguee pouvaient s'ecraser)."""
    try:
        import forge_worktree as W
    except ImportError:
        from tools import forge_worktree as W
    return W.route("acp_" + agent)


POOL_TTL_S = 240          # cache API mort apres 5 min ; reutilisation sous 240 s
POOL_MAX_TACHES = 5
POOL_MAX_USED = 120000


class ACPRouter:
    def __init__(self, log_dir=None, route=None, cmd_factory=None, permission_policy=None, horloge=time.time):
        self._horloge = horloge
        self._used = {}
        self.log_dir = Path(log_dir) if log_dir is not None else LOG_DIR
        self._route = route or _route_worktree
        self._cmd_factory = cmd_factory
        self.permission_policy = permission_policy or politique_refus
        delai = getattr(self.permission_policy, "delai_s", None)
        self.permission_timeout = (max(_client.PERMISSION_POLICY_TIMEOUT, delai + 5)
                                   if isinstance(delai, (int, float)) else _client.PERMISSION_POLICY_TIMEOUT)
        self._sessions = {}
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._redact = _client._journal_caviarde(lambda m: m)  # meme redacteur que les journaux du client

    # ---- journal ----
    def _ecrire(self, sid, agent, kind, payload):
        try:
            brut = json.dumps(payload, ensure_ascii=False, default=str)
            propre = self._redact(brut)
            try:
                payload_c = json.loads(propre)
            except ValueError:
                payload_c = propre
            ligne = json.dumps({"ts": time.time(), "session": sid, "agent": agent, "kind": kind,
                                "payload": payload_c}, ensure_ascii=False)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with open(self.log_dir / f"{sid}.jsonl", "a", encoding="utf-8") as f:
                    f.write(ligne + "\n")
        except Exception:  # noqa: BLE001
            _log.warning("journal ACP routeur illisible (%s)", sid, exc_info=True)

    # ---- API ----
    def ouvrir(self, agent, cwd=None, mode=None, modele=None, prompt_initial=None, timeout=_client.DEFAULT_TIMEOUT,
               profil=None, isolee=False, proprietaire=None):
        """Identifiant de session ; avec `prompt_initial` : {session, reponse, reutilisee} (le prompt part aussitot
        apres session/new, dans le meme appel -- l'agent claude sort apres ~10 s d'inactivite).
        `profil` : voir la docstring du module (defaut PROFIL_DEFAUT, claude seul).
        Pool : une session libre (meme agent, meme profil, < POOL_TTL_S, < POOL_MAX_TACHES taches,
        used <= POOL_MAX_USED) est reutilisee ; `isolee=True` ne passe jamais par le pool."""
        if agent in HORS_ACP:
            raise HorsACPError(f"HORS_ACP : {agent} ne parle pas ACP")
        profil_voulu = PROFIL_DEFAUT if profil is None else profil
        profil_applique = _profil_resolu(agent, profil)  # refus dit avant tout lancement
        isolee = bool(isolee)
        if not isolee:
            reprise = self._prendre_du_pool(agent, profil_applique, cwd, modele, proprietaire=proprietaire)
            if reprise is not None:
                psid, ps = reprise
                self._ecrire(psid, agent, "pool_reutilisee", {"taches": ps["taches"], "used": self._used.get(psid, 0)})
                if prompt_initial is None:
                    return psid
                try:
                    reponse = self.envoyer(psid, prompt_initial, timeout=timeout, proprietaire=proprietaire)
                except Exception:
                    self._fermer_reel(psid, "echec")  # une session dont l'usage echoue sort du pool
                    raise
                return {"session": psid, "reponse": reponse, "reutilisee": True}
        if cwd is None:
            try:
                cwd = self._route(agent)
            except Exception as exc:  # noqa: BLE001
                raise CwdIndisponibleError(f"pas de worktree pour {agent} : {exc!r}") from exc
            if not cwd:
                raise CwdIndisponibleError(f"pas de worktree pour {agent}")
            if Path(cwd).resolve() == ROOT.resolve():
                # recette 28/10 : forge_worktree.route() retombe sur la racine PARTAGEE quand l'agent n'a pas de
                # worktree ; la session y ecrivait dans l'arbre de tous les agents. Refus explicite.
                raise CwdIndisponibleError(f"pas de worktree dedie pour {agent} (repli sur la racine partagee refuse)")
        with self._lock:
            sid = f"{agent}-{next(self._seq)}-{int(time.time() * 1000) % 10_000_000}"

        cli = self._creer_client(sid, agent, cwd)
        mode_applique = modele_applique = None
        try:
            init = cli.initialize()
            params_new = {"cwd": str(cwd), "mcpServers": []}
            meta = _meta_profil(profil_applique)
            if meta:
                params_new["_meta"] = meta
            res_new = cli.request("session/new", params_new, timeout=30)
            if isinstance(res_new, dict):
                cli.derniere_session = res_new  # models.availableModels sert au choix du modele
            acp_sid = (res_new or {}).get("sessionId") or (res_new or {}).get("session_id")
            if not acp_sid:
                raise RuntimeError(f"session/new sans sessionId: {res_new}")
            if profil_applique is None and profil is not None:
                self._ecrire(sid, agent, "profil_ignore", {"voulu": profil_voulu, "motif": "agent non claude"})
            voulu = mode or MODES_SURS.get(agent)
            if voulu:
                modes = (cli.derniere_session.get("modes") or {}) if isinstance(cli.derniere_session, dict) else {}
                annonces = [m.get("id") if isinstance(m, dict) else m for m in (modes.get("availableModes") or [])]
                if voulu in annonces:
                    cli.set_mode(acp_sid, voulu)
                    mode_applique = voulu
                    self._ecrire(sid, agent, "mode_applique", {"mode": voulu})
                else:
                    self._ecrire(sid, agent, "mode_inchange",
                                 {"voulu": voulu, "annonces": annonces,
                                  "courant": modes.get("currentModeId")})
            voulu_m = modele or _modele_prefere(agent)
            if voulu_m:
                mods = (cli.derniere_session.get("models") or {}) if isinstance(cli.derniere_session, dict) else {}
                annonces_m = [m.get("modelId") if isinstance(m, dict) else m for m in (mods.get("availableModels") or [])]
                choisi = _choisir_modele(voulu_m, annonces_m)
                if choisi:
                    cli.request("session/set_model", {"sessionId": acp_sid, "modelId": choisi}, timeout=30)
                    modele_applique = choisi
                    self._ecrire(sid, agent, "modele_applique", {"modele": choisi})
                else:
                    # jamais deviner : le modele voulu n'est pas annonce (adaptateur en retard sur le CLI ?)
                    self._ecrire(sid, agent, "modele_inchange",
                                 {"voulu": voulu_m, "annonces": annonces_m, "courant": mods.get("currentModelId")})
        except Exception:
            cli.close()
            raise
        with self._lock:
            self._sessions[sid] = {"cli": cli, "agent": agent, "cwd": str(cwd), "acp": acp_sid,
                                   "mode": mode_applique, "modele": modele_applique, "profil": profil_applique,
                                   "init": init if isinstance(init, dict) else {},
                                   "reprise": threading.Lock(), "isolee": isolee, "libre": False, "taches": 1,
                                   "dernier": self._horloge(), "proprietaire": proprietaire}
        self._ecrire(sid, agent, "ouverte", {"cwd": str(cwd), "profil": profil_applique})
        if prompt_initial is None:
            return sid
        try:
            reponse = self.envoyer(sid, prompt_initial, timeout=timeout, proprietaire=proprietaire)
        except Exception:
            try:
                self._fermer_reel(sid, "echec")
            except KeyError:
                pass
            raise
        return {"session": sid, "reponse": reponse, "reutilisee": False}

    def _prendre_du_pool(self, agent, profil, cwd, modele=None, proprietaire=None):
        """Reserve (libre=False) une session libre eligible ; (sid, session) ou None. Atomique sous le verrou.
        29/10 (audit ACP (a)) : une session libre n'est reprise que par SON proprietaire -- elle porte l'historique
        de la conversation d'avant."""
        now = self._horloge()
        with self._lock:
            for sid, s in self._sessions.items():
                if (s.get("isolee") or not s.get("libre") or s["agent"] != agent or s.get("profil") != profil
                        or s.get("proprietaire") != proprietaire
                        or (modele and s.get("modele") != modele)  # modele explicite : il fait partie de la cle
                        or (cwd is not None and os.path.normcase(str(Path(str(cwd)).resolve()))
                            != os.path.normcase(str(Path(s["cwd"]).resolve())))
                        or now - s["dernier"] >= POOL_TTL_S or s["taches"] >= POOL_MAX_TACHES
                        or self._used.get(sid, 0) > POOL_MAX_USED):
                    continue
                s["libre"] = False
                s["taches"] += 1
                return sid, s
        return None

    def _fermer_reel(self, sid, motif):
        with self._lock:
            s = self._sessions.pop(sid, None)
        if s is None:
            raise KeyError(f"session inconnue : {sid}")
        try:
            s["cli"].close()
        finally:
            self._used.pop(sid, None)
        if motif in ("taches", "used"):
            self._ecrire(sid, s["agent"], "pool_recyclee", {"motif": motif})
        self._ecrire(sid, s["agent"], "fermee", {"motif": motif} if motif else {})

    def purger(self, maintenant=None):
        """Ferme reellement les sessions libres inactives depuis plus de POOL_TTL_S ; rend les sid fermes."""
        now = self._horloge() if maintenant is None else maintenant
        with self._lock:
            perimees = [sid for sid, s in self._sessions.items()
                        if s.get("libre") and now - s["dernier"] > POOL_TTL_S]
        out = []
        for sid in perimees:
            try:
                self._fermer_reel(sid, "purge")
                out.append(sid)
            except KeyError:
                pass
        return out

    def _creer_client(self, sid, agent, cwd):
        """Client demarre (processus lance) pour la session `sid` ; meme crochets que l'ouverture."""
        def _evt(params):
            upd = params.get("update") if isinstance(params, dict) else None
            kind = (upd or {}).get("sessionUpdate") or (upd or {}).get("type") or "update"
            if kind == "usage_update" and isinstance((upd or {}).get("used"), (int, float)):
                self._used[sid] = upd["used"]
            self._ecrire(sid, agent, kind, params)

        def _perm(params):
            if getattr(self.permission_policy, "accepte_contexte", False):
                res = self.permission_policy(params, session=sid, agent=agent)
            else:
                res = self.permission_policy(params)
            self._ecrire(sid, agent, "permission", {"request": params, "decision": res})
            return res

        cmd = self._cmd_factory(agent) if self._cmd_factory else None
        cli = _client.ACPClient(cmd=cmd, cwd=str(cwd), agent=agent,
                                on_log=lambda m: self._ecrire(sid, agent, "log", {"msg": m}),
                                on_event=_evt, permission_policy=_perm,
                                permission_timeout=self.permission_timeout)
        cli.start()
        return cli

    def _get(self, sid):
        with self._lock:
            s = self._sessions.get(sid)
        if s is None:
            raise KeyError(f"session inconnue : {sid}")
        return s

    @staticmethod
    def _verifier_proprietaire(s, sid, proprietaire):
        """29/10 (audit AGY ACP (a)) : la session d'un AUTRE appelant est refusee, AVANT tout contact avec le client.
        Sans appelant (ancien hub, appel interne) : comportement d'avant. NR test_acp_session_proprietaire_nr."""
        if proprietaire is not None and s.get("proprietaire") != proprietaire:
            raise PermissionError(f"session {sid} : ouverte par un autre appelant")

    @staticmethod
    def _client_mort(cli) -> bool:
        proc = getattr(cli, "proc", None)
        return (proc is not None and proc.poll() is not None) or not getattr(cli, "_alive", True)

    @staticmethod
    def _methode_reprise(init) -> str:
        """session/load si annoncee (agentCapabilities.loadSession), sinon session/resume si
        sessionCapabilities.resume est annoncee ; sinon rien (jamais devine)."""
        caps = (init or {}).get("agentCapabilities") or {}
        if caps.get("loadSession"):
            return "session/load"
        if (caps.get("sessionCapabilities") or {}).get("resume") is not None:
            return "session/resume"
        return ""

    def _reprendre(self, sid, s):
        """Relance l'agent (meme cwd), recharge la session ACP, rejoue mode/modele surs. RuntimeError DITE sinon."""
        agent = s["agent"]
        ancien = s["cli"]
        rc_avant = getattr(getattr(ancien, "proc", None), "poll", lambda: None)()
        self._ecrire(sid, agent, "reprise_debut", {"rc_agent_mort": rc_avant, "cwd": s["cwd"]})
        cli = self._creer_client(sid, agent, s["cwd"])
        try:
            init = cli.initialize()
            methode = self._methode_reprise(init)
            if not methode:
                raise RuntimeError("l'agent n'annonce ni loadSession ni sessionCapabilities.resume")
            params_load = {"sessionId": s["acp"], "cwd": s["cwd"], "mcpServers": []}
            meta = _meta_profil(s.get("profil"))  # le profil est REJOUE a la reprise
            if meta:
                params_load["_meta"] = meta
            res = cli.request(methode, params_load, timeout=60)
            if isinstance(res, dict):
                cli.derniere_session = res
            voulu = s.get("mode")
            if voulu:
                modes = (res.get("modes") or {}) if isinstance(res, dict) else {}
                annonces = [m.get("id") if isinstance(m, dict) else m for m in (modes.get("availableModes") or [])]
                if voulu == MODES_SURS.get(agent) or voulu in annonces:
                    cli.set_mode(s["acp"], voulu)
            if s.get("modele"):
                cli.request("session/set_model", {"sessionId": s["acp"], "modelId": s["modele"]}, timeout=30)
        except Exception as exc:
            detail = f"{exc} | {cli._mort()}" if cli.proc is not None else str(exc)
            cli.close()
            self._ecrire(sid, agent, "reprise_echec", {"erreur": str(exc)[:500], "detail": detail[:800]})
            raise RuntimeError(f"reprise impossible de la session {sid} : {detail}") from exc
        with self._lock:
            s["cli"] = cli
            s["init"] = init if isinstance(init, dict) else {}
        try:
            ancien.close()
        except Exception:  # noqa: BLE001 -- l'ancien est deja mort
            _log.debug("fermeture de l'ancien client", exc_info=True)
        self._ecrire(sid, agent, "reprise", {"methode": methode, "cwd": s["cwd"], "session_acp": s["acp"]})

    def envoyer(self, sid, texte, timeout=_client.DEFAULT_TIMEOUT, proprietaire=None):
        s = self._get(sid)
        self._verifier_proprietaire(s, sid, proprietaire)
        if s.get("libre"):  # session rendue au pool : plus a son appelant (elle peut etre reservee par un autre)
            raise KeyError(f"session inconnue : {sid} (liberee)")
        self._ecrire(sid, s["agent"], "prompt", {"text": texte})
        with s["reprise"]:
            if s["cli"].is_session_busy(s["acp"]):
                raise SessionBusyError(f"session occupee ({s['acp']}) : un seul prompt a la fois par session")
            if self._client_mort(s["cli"]):
                self._reprendre(sid, s)
        try:
            res = s["cli"].prompt(s["acp"], texte, timeout=timeout)  # SessionBusyError si occupee
        except RuntimeError as exc:
            # mort pendant l'ECRITURE (le prompt n'est jamais parti) : une seule reprise, puis renvoi
            if not str(exc).startswith("agent ACP mort ou injoignable"):
                raise
            with s["reprise"]:
                if self._client_mort(s["cli"]):
                    self._reprendre(sid, s)
            res = s["cli"].prompt(s["acp"], texte, timeout=timeout)
        s["dernier"] = self._horloge()
        self._ecrire(sid, s["agent"], "reponse", res)
        return res

    def fermer(self, sid, proprietaire=None):
        """Session poolee : LIBERER (retour au pool), sauf seuil de recyclage atteint ou `isolee` -> fermeture reelle."""
        s = self._get(sid)
        self._verifier_proprietaire(s, sid, proprietaire)
        if s.get("isolee"):
            return self._fermer_reel(sid, "")
        if s["taches"] >= POOL_MAX_TACHES:
            return self._fermer_reel(sid, "taches")
        if self._used.get(sid, 0) > POOL_MAX_USED:
            return self._fermer_reel(sid, "used")
        with self._lock:
            s["libre"] = True
            s["dernier"] = self._horloge()
        self._ecrire(sid, s["agent"], "pool_liberee", {"taches": s["taches"], "used": self._used.get(sid, 0)})

    def lister(self, proprietaire=None):
        with self._lock:
            items = [(i, s) for i, s in self._sessions.items() if not s.get("libre")  # libres = interne au pool
                     and (proprietaire is None or s.get("proprietaire") == proprietaire)]  # 29/10 : les siennes
        return [{"id": i, "agent": s["agent"], "cwd": s["cwd"],
                 "occupee": s["cli"].is_session_busy(s["acp"])} for i, s in items]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    def _val(flag):
        from nokido_agent.app.forge_utils import valeur_option   # source unique (cliquet clones 31/10)
        return valeur_option(argv, flag)

    dossier = _val("--dossier")
    if "--permissions" in argv:
        print(json.dumps(lister_en_attente(dossier), ensure_ascii=False, indent=1))
        return 0
    if "--decider" in argv:
        pid = _val("--decider")
        option = _val("--option")
        if not pid or (option is None and "--refuser" not in argv):
            print("usage: --decider <id> (--option <optionId> | --refuser)", file=sys.stderr)
            return 2
        try:
            print(json.dumps(decider(pid, option=option, refuser="--refuser" in argv, dossier=dossier,
                                         signer=signer_hub)))
        except (ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    print("usage: --permissions | --decider <id> (--option <optionId> | --refuser) [--dossier <d>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
