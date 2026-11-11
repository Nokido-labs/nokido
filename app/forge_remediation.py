"""
FORGE INTELLIGENCE — forge_remediation [GREEN]
================================================
ORGANE de remédiation autonomique (autophagie + glymphatique + homéostasie
unifiées). Détecte les 8 DETTES PHYSIQUES (diagnostic biomimétique 2026-06-09) et,
par dette : auto-répare la sûre OU signale durablement (forge_critical_events =
canal owner). Consommé par autonomous_loops.pat_remediation (tick autonomique).

Anti-dup (CLAUDE.md §3) : RÉUTILISE forge_embed_auto_trigger / forge_tier_policy /
forge_orphan_reaper / forge_llm_router / forge_project_state / forge_critical_events.
N'est PAS un détecteur de plus : c'est l'ORCHESTRATEUR des 8 remèdes (meta_evolution
détecte daemons/RAG ; ici = les 8 dettes spécifiques non couvertes ailleurs).

Conservateur par défaut : signal-only ; auto-fix seulement orphan_reaper si armed=True.
Le drain embed n'est PAS relancé ici (le service NokidoEmbedTrigger le fait ; on
signale juste si le backlog grossit = daemon en retard/mort).
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
HEARTBEAT = ROOT / "sandbox" / "remediation.heartbeat"
for _sub in ("app", "tools"):  # forge_tier_policy/orphan_reaper vivent dans tools/
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
log = logging.getLogger("forge_remediation")

EMBED_BACKLOG_ALERT = 3000  # hot-NULL au-dessus = daemon embed en retard/mort


def _signal(kind: str, severity: str, payload: dict) -> int:
    # Signe l'ORIGINE (20/10, fin de la CIVD) : un signal produit PAR le soin n'est pas une nouvelle lesion --
    # forge_coagulation._triage l'inhibe au lieu de relancer la remediation (anticoagulant).
    payload = dict(payload or {}, origine="forge_remediation")
    try:
        from nokido_agent.app.forge_critical_events import persist
        return persist(kind, severity, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("critical_events KO: %s", e)
        return 0


# ── 1. Dette de consolidation mémorielle (embed backlog hot-tier) ────────────
def check_embed_backlog(armed: bool) -> dict:
    """Dette d'embeddings lue comme un TAUX, chez son producteur -- jamais par inventaire.

    20/10 (owner : « usures disques abusives », « criteres ajustes au reel de la base RAG ») : ce controle faisait
    un comptage de la table RAG filtre sur embedding NULL + <CASE a LIKE>, sur 46,6 Go (~260 s, ~85 Mo/s), a chaque
    cycle de soin de NokidoCoagulation. La base reelle (snapshot) : 77 en attente QUALIFIEE, 6,9 M REFUSES par politique
    -- ces derniers ne sont pas une dette (DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE). Comme la coagulation du corps lit
    un taux sanguin mesure ailleurs : forge_memory_availability.snapshot() ne calcule jamais ; perime = INCONNU, sans
    balayage de repli et sans signal."""
    try:
        try:
            from nokido_agent.app import forge_memory_availability as _ma
        except ImportError:
            import forge_memory_availability as _ma
        snap = _ma.snapshot()
    except Exception as e:  # noqa: BLE001 - producteur illisible : INCONNU, jamais un balayage
        return {"etat": "INCONNU", "vector_pending": None, "raison": "snapshot illisible (%s)" % type(e).__name__,
                "alert_threshold": EMBED_BACKLOG_ALERT, "signaled": _signaler_dette_non_mesuree(None)}
    if not snap.get("frais"):
        return {"etat": "INCONNU", "vector_pending": None, "raison": snap.get("raison", ""),
                "age_s": snap.get("age_s"), "alert_threshold": EMBED_BACKLOG_ALERT,
                "signaled": _signaler_dette_non_mesuree(snap.get("age_s"))}
    n = snap.get("vector_pending")
    age = snap.get("age_s")
    if not isinstance(age, (int, float)) or age > EMBED_ALERT_AGE_MAX_S:
        # « frais » selon le TTL de 26 h du producteur ne suffit pas pour une alerte de panne : le drain a pu
        # resorber la dette depuis. Mesure trop vieille = INCONNU (ni panne ni sante), chiffre gardé à titre daté.
        return {"etat": "INCONNU", "vector_pending": None, "vector_pending_ancien": n, "age_s": age,
                "raison": "mesure trop vieille pour decider d'une panne (%s s > %.0f s)"
                          % (None if age is None else round(age), EMBED_ALERT_AGE_MAX_S),
                "alert_threshold": EMBED_BACKLOG_ALERT, "signaled": _signaler_dette_non_mesuree(age)}
    out = {"etat": "MESURE", "vector_pending": n, "vector_refused": snap.get("vector_refused"),
           "age_s": age, "alert_threshold": EMBED_BACKLOG_ALERT}
    if isinstance(n, int) and n > EMBED_BACKLOG_ALERT:
        pouls = _pouls_drain_embed()
        if pouls.get("progresse") is True:
            etat_drain = "le drain progresse (journal ecrit il y a %.0f s)" % pouls["age_s"]
        elif pouls.get("etat") == "ECHOUE":
            etat_drain = "le journal du drain ne montre que des erreurs"
        elif pouls.get("progresse") is False:
            etat_drain = "aucune ecriture du drain depuis %.0f s (journal)" % pouls["age_s"]
        else:
            etat_drain = "pouls du drain illisible"
        out["signaled"] = _signal("embed_consolidation_debt", "warn",
                                  {"vector_pending": n, "mesure_age_s": age, "drain": pouls,
                                   "remedy": "%d chunks en attente, mesure vieille de %.1f h ; %s ; "
                                   "si besoin : forge_embed_auto_trigger --once" % (n, age / 3600.0, etat_drain)})
    return out


EMBED_ALERT_AGE_MAX_S = 7200.0  # 2 h : ~ plusieurs cycles de drain ; au-dela la quantite a pu changer d'ordre
_DRAIN_LOG_ACTIF_S = 900.0
_DRAIN_LOG_QUEUE_OCTETS = 16384
_DRAIN_LOG_LIGNES = 40
import re as _re  # noqa: E402
_RE_EMBED_PROGRES = _re.compile(r"embed\s+\d+/\d+\s+\(\d+%\)")
_RE_EMBED_ERREUR = _re.compile(r"Traceback|Error|Exception", _re.I)


def _pouls_drain_embed() -> dict:
    """Le drain avance-t-il ? Lu sur les DERNIERES lignes (bornees) du journal de NokidoDeportEmbed -- aucune base
    ouverte. Le mtime seul ne prouve rien : un Traceback en boucle ecrit aussi.
    PROGRESSE = ligne `embed 818/5754 (14%) ~0.8/s` vue ; ECHOUE = erreurs seules ; ILLISIBLE = rien de lisible."""
    try:
        chemin = ROOT / "logs" / "supervisor" / "NokidoDeportEmbed.log"
        st = chemin.stat()
        age = round(time.time() - st.st_mtime, 1)
        with open(chemin, "rb") as f:
            f.seek(max(0, st.st_size - _DRAIN_LOG_QUEUE_OCTETS))
            lignes = f.read().decode("utf-8", errors="replace").splitlines()[-_DRAIN_LOG_LIGNES:]
    except Exception:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "progresse": None, "age_s": None}
    if any(_RE_EMBED_PROGRES.search(ln) for ln in lignes):
        return {"etat": "PROGRESSE", "progresse": age < _DRAIN_LOG_ACTIF_S, "age_s": age}
    if any(_RE_EMBED_ERREUR.search(ln) for ln in lignes):
        return {"etat": "ECHOUE", "progresse": False, "age_s": age}
    return {"etat": "ILLISIBLE", "progresse": None, "age_s": age}


_INCONNU_ESPACEMENT_S = 6 * 3600.0
_INCONNU_DERNIER_SIGNAL: dict = {}


def _signaler_dette_non_mesuree(age) -> int:
    """Capteur muet = signal de faible gravite (info), sans parler de panne ; au plus un par _INCONNU_ESPACEMENT_S."""
    now = time.time()
    if now - _INCONNU_DERNIER_SIGNAL.get("t", -1e12) < _INCONNU_ESPACEMENT_S:
        return 0
    _INCONNU_DERNIER_SIGNAL["t"] = now
    depuis = ("%.0f h" % (age / 3600.0)) if isinstance(age, (int, float)) else "duree inconnue"
    return _signal("embed_debt_unmeasured", "info",
                   {"age_s": age, "remedy": "dette d'embedding non mesuree depuis %s (mesure absente ou trop "
                                            "vieille) ; ni sante ni defaut constate" % depuis})


# ── 2. Thrombose circulatoire (lock DB) ──────────────────────────────────────
def check_db_contention(armed: bool) -> dict:
    # Probe NON-BLOQUANTE : tente le write-lock 0.5s. Le détecteur de thrombose ne
    # doit JAMAIS bloquer sur le lock (sinon il se thrombose lui-même).
    try:
        c = sqlite3.connect(str(DB), timeout=0.5)
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("ROLLBACK")
            return {"contention": False}
        finally:
            c.close()
    except sqlite3.OperationalError as e:
        if "lock" in str(e).lower() or "busy" in str(e).lower():
            return {"contention": True,
                    "signaled": _signal("db_lock_contention", "warn",
                                        {"detail": str(e)[:80], "remedy": "écritures ad-hoc à router via "
                                         "event_stream queue (mono-writer) ; éviter sqlite direct"})}
        return {"error": str(e)[:120]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}


# ── 3. Dette glymphatique (orphelins/débris) ─────────────────────────────────
def check_orphans(armed: bool) -> dict:
    # CONTRAT DU FAUCHEUR (15/10). `_managed_scripts` n'existe plus depuis c2705bb03 (le faucheur est
    # devenu moissonneur d'orphelins llama hors registre) : l'import levait a CHAQUE passage, la dette
    # glymphatique n'etait plus jamais mesuree, et la branche armee passait `--arm`, que le faucheur
    # ignore (il attend `--kill`) tout en ecrivant `auto_reaped: True`. On lit desormais SON inventaire.
    try:
        from nokido_agent.tools.forge_orphan_reaper import survey
        res = survey()
    except Exception as e:  # noqa: BLE001 - faucheur illisible : INCONNU, jamais « 0 orphelin »
        return {"etat": "INCONNU", "error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    if not res.get("ok"):
        return {"etat": "INCONNU", "raison": str(res.get("reason") or "inventaire refuse")[:160]}
    cand = len(res.get("candidates") or [])
    out = {"candidates": cand, "epargnes": len(res.get("spared") or [])}
    if cand > 0:
        if armed:
            try:
                r = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_orphan_reaper.py"), "--kill"],
                                   capture_output=True, text=True, timeout=60, errors="replace")
                out["rc"] = r.returncode
                out["moissonnes"] = r.stdout.count("REAPED pid=")
            except Exception as e:  # noqa: BLE001 - dit, jamais compte comme fait
                out["reap_error"] = str(e)[:120]
        else:
            out["signaled"] = _signal("orphan_debris", "warn",
                                      {"candidates": cand,
                                       "remedy": "tools/forge_orphan_reaper.py --kill (ou remediation --armed)"})
    return out


# ── 4. Nécrose : slots provider fantômes ─────────────────────────────────────
def check_phantom_slots(armed: bool) -> dict:
    try:
        from nokido_agent.app.forge_llm_router import PROVIDERS, USE_CASE_CHAINS
        phantoms = sorted({p for chain in USE_CASE_CHAINS.values() for p in chain if p not in PROVIDERS})
    except Exception as e:
        return {"error": str(e)[:120]}
    out = {"phantoms": phantoms}
    if phantoms:
        out["signaled"] = _signal("phantom_provider_slots", "error",
                                  {"phantoms": phantoms[:10], "remedy": "ajouter à PROVIDERS ou retirer "
                                   "de USE_CASE_CHAINS (réconciliation forge_provider_canonical step 4)"})
    return out


# ── 5. Ischémie membrane sandbox (cffi DLL) ──────────────────────────────────
def check_cffi(armed: bool) -> dict:
    try:
        import _cffi_backend  # noqa: F401
        return {"cffi_ok": True}
    except Exception as e:
        sig = _signal("sandbox_cffi_broken", "warn",
                      {"error": str(e)[:120], "platform": sys.platform,
                       "remedy": "perms DLL _cffi_backend pour LaForgeSbxOnline (ICACLS read+exec site-packages)"})
        return {"cffi_ok": False, "error": str(e)[:120], "signaled": sig}


# ── 6. Atrophie OAuth CLI ────────────────────────────────────────────────────
def _owner_home() -> Path:
    """Profil de l'OWNER, pas du compte qui execute (convention forge_conv_indexer.OWNER_HOME). 20/10 : Path.home() d'un
    compte de service ne porte aucun login -- « gh missing » a chaque tour alors que gh etait connecte (keyring)."""
    return Path(os.environ.get("LAFORGE_OWNER_HOME") or ROOT.parent.parent)


def check_oauth(armed: bool) -> dict:
    # heuristique fichiers de creds (sans charger les tokens). Trois etats : present, ABSENT (FileNotFoundError prouve
    # sous un profil lisible), ILLISIBLE (acces refuse, profil introuvable) -- illisible n'est jamais un login manquant.
    home = _owner_home()
    probes = {
        "gemini_cli": home / ".gemini" / "oauth_creds.json",
        "copilot_cli (gh)": home / "AppData" / "Roaming" / "GitHub CLI" / "hosts.yml",
    }
    missing, illisible = [], []
    try:
        home.stat()
        profil_lisible = True
    except OSError:  # profil owner introuvable ou refuse : on ne sait RIEN de ses logins
        profil_lisible = False
    for name, p in probes.items():
        if not profil_lisible:
            illisible.append(name)
            continue
        try:
            p.stat()
        except FileNotFoundError:
            missing.append(name)
        except OSError:  # acces refuse : INCONNU, jamais absent
            illisible.append(name)
    out = {"missing_login": missing, "illisible": illisible}
    if missing:
        out["signaled"] = _signal("oauth_cli_atrophy", "warn",
                                  {"missing": missing, "remedy": "re-login : gh auth login / gemini / claude"})
    return out


# ── 7. Hypoglycémie métabolique (balance 402) ────────────────────────────────
def check_balance_402(armed: bool) -> dict:
    try:
        ce = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        # scan léger d'audit récent (si table) — sinon best-effort log
        ce.close()
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_remediation.py', 172, exc_info=True)
    audit = ROOT / "logs" / "mcp_audit.log"
    has402 = False
    try:
        if audit.exists():
            txt = audit.read_text(encoding="utf-8", errors="ignore")[-200_000:]
            has402 = "402" in txt and ("insufficient" in txt.lower() or "credit" in txt.lower() or "balance" in txt.lower())
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_remediation.py', 180, exc_info=True)
    out = {"has_402": has402}
    if has402:
        out["signaled"] = _signal("provider_balance_low", "warn",
                                  {"http": 402, "remedy": "recharger OPENROUTER_API_KEY (partagée 7 providers) "
                                   "ou basculer free-tier (sambanova/github/groq)"})
    return out


# ── 8. Sarcopénie (fichiers stale) ───────────────────────────────────────────
def check_stale(armed: bool) -> dict:
    # Léger : compte le legacy _attic (proxy sarcopénie). PAS d'AST scan lourd.
    try:
        attic = ROOT / "app" / "_attic"
        n = sum(1 for _ in attic.rglob("*.py")) if attic.exists() else 0
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}
    out = {"attic_legacy": n}
    if n > 100:
        out["signaled"] = _signal("sarcopenia_stale", "warn",
                                  {"attic_legacy": n, "remedy": "purge/archive app/_attic + branches git stale"})
    return out


# ── 9. Dette de PORT ZOMBIE (le registre dit vivant, le réel dit muet) ───────
# Mesure 2026-08-29 : NokidoWebHub déclaré `running` avec :7400 MORT rendait la CI
# ui-acceptance flaky. `forge_ensure_service` portait déjà le remède — personne ne
# l'appelait. Un garde sans porteur ne garde rien : c'est cette boucle qui l'appelle.
_PORTS_SERVICES = {"webhub": (7400, "NokidoWebHub")}
_ZOMBIE_COOLDOWN_S = 900  # anti-pompage : 1 remède / 15 min et par service
_ZOMBIE_ETAT = ROOT / "sandbox" / "port_zombie_state.json"


def _port_ouvert(port: int, timeout: float = 1.5):
    """-> True / False / None. None = pas pu regarder, JAMAIS lu comme « fermé »."""
    import socket
    try:
        with socket.socket() as s:
            s.settimeout(timeout)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return None


def _service_declare_vivant(nom: str):
    """-> True / False / None, via nssm.

    `sc query` sort VIDE sans erreur sous certains comptes (piège mesuré le
    2026-08-25) : un capteur qui rend « rien » pour « refusé » fabrique des faux
    négatifs indétectables. On lit donc nssm, et une sortie vide reste None.
    """
    try:
        r = subprocess.run(["nssm", "status", nom], capture_output=True, text=True,
                           timeout=10, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "").replace("\x00", "").strip().upper()
    return ("RUNNING" in out) if out else None


def _zombie_etats() -> dict:
    try:
        return json.loads(_ZOMBIE_ETAT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _relance(svc: str) -> str:
    try:
        if str(ROOT / "tools") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_ensure_service import ensure
        r = ensure(svc, "restarted")
        # `success` seul MENT parfois (detail peut porter un HTTP 200 ok) : on rend
        # les deux et on laisse le lecteur trancher sur le réel.
        return "success=%s | %s" % (r.get("success"), str(r.get("detail"))[:140])
    except Exception as e:  # noqa: BLE001 - un remède qui échoue ne casse pas le cycle
        return "echec: %s: %s" % (type(e).__name__, str(e)[:110])


def check_port_zombie(armed: bool) -> dict:
    """Service DÉCLARÉ vivant + port MUET = zombie. Déclaré arrêté = rien à dire."""
    out: dict[str, Any] = {}
    etats = _zombie_etats()
    maj = False
    for svc, (port, nom) in _PORTS_SERVICES.items():
        ouvert = _port_ouvert(port)
        if ouvert is None:
            out[svc] = {"etat": "illisible", "port_ouvert": None}
            continue
        # Un port QUI REPOND se suffit : pas besoin d'un témoin extérieur pour
        # conclure « sain ». Interroger nssm d'abord rendait le cas sain ILLISIBLE
        # sur tout compte sans accès aux services — un garde muet la plupart du
        # temps, pour une question qui était déjà tranchée par la mesure directe.
        if ouvert:
            out[svc] = {"etat": "sain", "port": port}
            continue
        # Port muet : reste à savoir si l'arrêt est VOULU. Là seulement, le registre.
        declare = _service_declare_vivant(nom)
        if declare is None:
            out[svc] = {"etat": "illisible", "port_ouvert": False, "declare": None,
                        "detail": "port muet mais etat declare illisible (nssm hors "
                                  "de portee) : ni zombie ni arret voulu prouve"}
            continue
        if not declare:
            out[svc] = {"etat": "arrete (legitime)"}  # ne PAS crier sur un arrêt voulu
            continue
        info = {"etat": "ZOMBIE", "port": port, "service": nom,
                "remedy": "ensure_service %s restarted" % svc}
        depuis = time.time() - float(etats.get(svc, 0) or 0)
        if armed and depuis > _ZOMBIE_COOLDOWN_S:
            info["remede_tente"] = _relance(svc)
            etats[svc] = time.time()
            maj = True
        elif armed:
            info["remede_differe"] = "cooldown %ds restant %ds (anti-pompage)" % (
                _ZOMBIE_COOLDOWN_S, int(_ZOMBIE_COOLDOWN_S - depuis))
        info["signaled"] = _signal("port_zombie", "warn", info)
        out[svc] = info
    if maj:
        try:
            _ZOMBIE_ETAT.parent.mkdir(exist_ok=True)
            _ZOMBIE_ETAT.write_text(json.dumps(etats), encoding="utf-8")
        except OSError as e:  # noqa: BLE001
            log.warning("port_zombie: etat non persiste (%s) -> cooldown non tenu", e)
    return out


# ── 10. Integrite de livraison : verifier, soigner, ne remonter que les decisions (7/11) ─────────────────────
# Owner 7/11 : « si le corps recoit des signaux il doit savoir les traiter de facon autonome », « a part les relayer
# je ne peux pas en faire grand chose ». Mesure : 52 constats jamais acquittes, aucun consommateur de `ack`. Ce
# controle re-mesure chaque constat ouvert (forge_delivery_integrity.remesurer, lecture seule), acquitte le resolu ou
# le contredit et depose UNE tache de reverification par suspect confirme -- les deux SEULEMENT si `armed`.
# Il n'emet AUCUN signal (inhibiteur) : son produit ne doit pas relancer la coagulation.
INTEGRITE_MAX_PASSE = 60                     # constats re-mesures par passe (borne le cout git/gh)
REVERIF_MAX_JOUR = int(os.environ.get("LAFORGE_INTEGRITE_REVERIF_MAX_JOUR", "3"))
REVERIF_AGENT_DEFAUT = "OPENCODE_GLM"        # surface gratuite (meme choix que les enquetes de code epistemiques)
# Miroir de tools/forge_task_executor._SURFACES_PAYANTES (non importe : module lourd, effets de bord au chargement).
_SURFACES_PAYANTES = ("CLAUDE_HEADLESS",)
_REVERIF_ETAT = ROOT / "sandbox" / "integrite_reverif.json"


def _agent_reverif() -> str:
    """Surface de reverification ; une surface payante n'est retenue que sur opt-in explicite."""
    a = (os.environ.get("LAFORGE_INTEGRITE_REVERIF_AGENT") or REVERIF_AGENT_DEFAUT).strip().upper()
    if a in _SURFACES_PAYANTES and os.environ.get("LAFORGE_INTEGRITE_REVERIF_PAYANT") != "1":
        return REVERIF_AGENT_DEFAUT
    return a


def _deposer_reverif(description: str, agent: str) -> dict:
    """Primitive d'assignation existante (`task action=assign` du hub), meme voie que
    forge_epistemic_daemon._deposer_enquete. {"task_id"} | {"error"} ; ne leve jamais."""
    try:
        from nokido_agent.app.forge_hub_client import HubClient

        txt = HubClient(agent="COAGULATION", timeout=30.0).tool("task", {
            "action": "assign", "agent": agent, "intent": "HANDOFF_NEXT", "description": description})
        d = json.loads(txt or "")
    except Exception as e:  # noqa: BLE001 - rendu, jamais cache
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    tid = d.get("task_id") if isinstance(d, dict) else None
    return {"task_id": tid} if tid else {"error": "pas de task_id : %s" % str(d)[:160]}


def _lire_reverif():
    """Etat des depots ({"findings": {id: ...}, "jours": {date: n}}) ; absent = vide ; illisible = None."""
    try:
        etat = json.loads(_REVERIF_ETAT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"findings": {}, "jours": {}}
    except (OSError, ValueError):
        return None
    if not isinstance(etat, dict):
        return None
    etat.setdefault("findings", {})
    etat.setdefault("jours", {})
    return etat


def _description_reverif(f: dict, m: dict) -> str:
    desc = ("REVERIFICATION D'UNE LIVRAISON (lecture seule : ne modifie, ne committe et ne pousse rien).\n"
            "La tache %s (agent %s) est marquee done en citant le commit %s, anterieur a sa creation ; "
            "l'executeur n'a observe aucun commit produit (constat delivery_integrity %s).\n"
            "Verifie dans le depot si le travail demande par cette tache existe (fichiers, fonctions, tests) et "
            "rends : FAIT avec le SHA reel du livrable (7 a 40 hexadecimaux existant dans le depot), NON FAIT "
            "avec ce qui manque, ou ILLISIBLE.\n"
            "Consigne d'origine (extrait) :\n%s\n"
            "pointer_ref attendu : le SHA reel du livrable, jamais un gabarit (ex. sha_vrai_du_livrable)"
            % (m.get("tache"), m.get("agent"), m.get("sha"), f.get("id"), m.get("consigne") or "(illisible)"))
    # Contrat `aucun` dans la forme que lit tools/forge_task_executor._contrat_livrable : la reverification ne
    # produit aucun artefact, l'executeur ne commite pas pour elle, et tout ecrit est un RIEN_PRODUIT nomme.
    return desc + '\n[LIVRABLE_CONTRAT] {"livrable": {"type": "aucun"}}'


def _reverifier_une_fois(etat, f: dict, m: dict) -> dict:
    """UNE tache par constat (dedup sur l'id du constat), au plus REVERIF_MAX_JOUR par jour."""
    ref = "%s:%s" % (f["kind"], f["target"])
    if etat is None:
        return {"ref": ref, "statut": "ETAT_ILLISIBLE", "detail": "%s illisible : aucun depot (doublon possible)"
                % _REVERIF_ETAT.name}
    deja = etat["findings"].get(f["id"])
    if deja:
        return {"ref": ref, "statut": "DEJA_DEPOSEE", "task_id": deja.get("task_id")}
    jour = time.strftime("%Y-%m-%d")
    if int(etat["jours"].get(jour, 0)) >= REVERIF_MAX_JOUR:
        return {"ref": ref, "statut": "PLAFOND_JOUR", "plafond": REVERIF_MAX_JOUR}
    agent = _agent_reverif()
    res = _deposer_reverif(_description_reverif(f, m), agent)
    if not res.get("task_id"):
        return {"ref": ref, "statut": "REFUS", "detail": res.get("error")}
    etat["findings"][f["id"]] = {"task_id": res["task_id"], "ts": time.time(), "agent": agent}
    etat["jours"][jour] = int(etat["jours"].get(jour, 0)) + 1
    return {"ref": ref, "statut": "DEPOSEE", "task_id": res["task_id"], "agent": agent}


def _description_ci(m: dict) -> str:
    return ("ANALYSE D'UNE CI EN ECHEC PERSISTANT (lecture seule : ne relance PAS la CI, ne modifie, ne committe et "
            "ne pousse rien).\n"
            "Workflow %s sur la branche %s, commit %s : le dernier run termine est en echec apres re-mesure.\n"
            "Analyse le run rouge (journal des etapes en echec) et rends : la cause probable et le correctif propose, "
            "ou NON FAIT avec ce qui manque.\n"
            "pointer_ref attendu : le rapport d'analyse."
            % (m.get("workflow"), m.get("branche") or "?", m.get("commit")))


def _analyser_ci_une_fois(etat, f: dict, m: dict) -> dict:
    """UNE tache d'analyse par couple (workflow, commit), au plus REVERIF_MAX_JOUR par jour (meme plafond)."""
    ref = "%s:%s" % (f["kind"], f["target"])
    if etat is None:
        return {"ref": ref, "statut": "ETAT_ILLISIBLE", "detail": "%s illisible : aucun depot (doublon possible)"
                % _REVERIF_ETAT.name}
    if not m.get("workflow") or not m.get("commit"):
        return {"ref": ref, "statut": "CLE_INCOMPLETE"}
    cle = "ci:%s@%s" % (m["workflow"], m["commit"])
    deja = etat["findings"].get(cle)
    if deja:
        return {"ref": ref, "statut": "DEJA_DEPOSEE", "task_id": deja.get("task_id")}
    jour = time.strftime("%Y-%m-%d")
    if int(etat["jours"].get(jour, 0)) >= REVERIF_MAX_JOUR:
        return {"ref": ref, "statut": "PLAFOND_JOUR", "plafond": REVERIF_MAX_JOUR}
    agent = _agent_reverif()
    res = _deposer_reverif(_description_ci(m), agent)
    if not res.get("task_id"):
        return {"ref": ref, "statut": "REFUS", "detail": res.get("error")}
    etat["findings"][cle] = {"task_id": res["task_id"], "ts": time.time(), "agent": agent}
    etat["jours"][jour] = int(etat["jours"].get(jour, 0)) + 1
    return {"ref": ref, "statut": "DEPOSEE", "task_id": res["task_id"], "agent": agent}


def check_delivery_integrity(armed: bool) -> dict:
    """Re-mesure les constats ouverts ; armed : acquitte le resolu/contredit et depose les reverifications."""
    try:
        from nokido_agent.app import forge_delivery_integrity as DI
    except Exception as e:  # noqa: BLE001
        return {"etat": "INCONNU", "raison": "organe illisible (%s)" % type(e).__name__,
                "resume": "soin impossible : forge_delivery_integrity illisible"}
    ouverts = DI.findings_ouverts(INTEGRITE_MAX_PASSE)
    if ouverts is None:
        return {"etat": "INCONNU", "raison": "table des constats illisible",
                "resume": "soin impossible : constats illisibles"}
    out: dict[str, Any] = {"etat": "MESURE", "armed": armed, "ouverts": len(ouverts), "acquittes": [],
                           "a_acquitter": [], "suspects": [], "taches": [], "persistants": [], "inconnus": []}
    etat_rv, ecrire = None, False
    for f in ouverts:
        ref = "%s:%s" % (f["kind"], f["target"])
        m = DI.remesurer(f["kind"], f["target"])
        e = m.get("etat")
        if e in ("RESOLU", "CONTREDIT"):
            if not armed:
                out["a_acquitter"].append(ref)
            elif DI.ack(f["kind"], f["target"], "soin %s : %s" % (e, m.get("motif"))):
                out["acquittes"].append(ref)
            else:
                out["inconnus"].append(ref)
        elif e == "SUSPECT":
            out["suspects"].append(ref)
            if armed:
                if etat_rv is None:
                    etat_rv = _lire_reverif()
                t = _reverifier_une_fois(etat_rv, f, m)
                ecrire = ecrire or t["statut"] == "DEPOSEE"
                out["taches"].append(t)
        elif e == "PERSISTE":
            out["persistants"].append(ref)
            if armed and f["kind"] == "ci_en_echec":
                if etat_rv is None:
                    etat_rv = _lire_reverif()
                t = _analyser_ci_une_fois(etat_rv, f, m)
                ecrire = ecrire or t["statut"] == "DEPOSEE"
                out["taches"].append(t)
        else:
            out["inconnus"].append(ref)
    if ecrire:
        try:
            _REVERIF_ETAT.parent.mkdir(parents=True, exist_ok=True)
            tmp = _REVERIF_ETAT.with_suffix(".tmp")
            tmp.write_text(json.dumps(etat_rv, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, _REVERIF_ETAT)
        except OSError as e:  # noqa: BLE001 - dit : la dedup ne tiendra pas
            out["etat_reverif"] = "NON ECRIT (%s) : doublon de tache possible" % type(e).__name__
    deposees = sum(1 for t in out["taches"] if t.get("statut") == "DEPOSEE")
    if armed:
        out["resume"] = ("soin arme : %d constat(s) relu(s), %d acquitte(s), %d suspect(s) (%d tache(s) deposee(s)), "
                         "%d persistant(s), %d illisible(s)"
                         % (len(ouverts), len(out["acquittes"]), len(out["suspects"]), deposees,
                            len(out["persistants"]), len(out["inconnus"])))
    else:
        out["resume"] = ("soin NON ARME (dry-run, decision owner : --armed) : %d constat(s) relu(s), "
                         "%d acquittable(s), %d suspect(s), %d persistant(s), %d illisible(s)"
                         % (len(ouverts), len(out["a_acquitter"]), len(out["suspects"]),
                            len(out["persistants"]), len(out["inconnus"])))
    return out


CHECKS = [check_embed_backlog, check_db_contention, check_orphans, check_phantom_slots,
          check_cffi, check_oauth, check_balance_402, check_stale, check_port_zombie, check_delivery_integrity]


# Soin CIBLE : type de lesion (fragment du `kind` du signal) -> son remede. Un signal connu ne declenche
# que son controle, pas les 9 a chaque passe.
LESION_REMEDE = {
    "embed": "check_embed_backlog", "backlog": "check_embed_backlog",
    "contention": "check_db_contention", "lock": "check_db_contention", "db_": "check_db_contention",
    "orphan": "check_orphans", "phantom": "check_phantom_slots", "cffi": "check_cffi",
    "oauth": "check_oauth", "balance": "check_balance_402", "402": "check_balance_402",
    "quota": "check_balance_402", "stale": "check_stale", "sarcopenia": "check_stale",
    "zombie": "check_port_zombie", "delivery_integrity": "check_delivery_integrity",
}
# Controles lances SEULEMENT quand une lesion les cible, jamais par le balayage complet (lesions absentes ou
# inconnues, dont forge_autonomous_loops.pat_remediation a chaque tick).
SUR_LESION_SEULEMENT = frozenset({"check_delivery_integrity"})


def controles_pour(lesions):
    """Lesions (kinds) -> ensemble des controles a lancer ; None = inconnu -> tous (jamais moins que le reel)."""
    if not lesions:
        return None
    voulus: set = set()
    for kind in lesions:
        k = str(kind).lower()
        trouves = {chk for frag, chk in LESION_REMEDE.items() if frag in k}
        if not trouves:
            return None  # une lesion non classee : balayage complet, on ne parie pas
        voulus |= trouves
    return voulus


def run_remediation_cycle(armed: bool = False, lesions=None) -> dict:
    """Exécute les contrôles → détecte + signale (+ auto-fix orphans / relance d'un
    port zombie si armed, ce dernier sous cooldown anti-pompage). `lesions` (kinds des
    signaux) restreint aux remèdes ciblés ; absent/inconnu = les 9."""
    t0 = time.monotonic()
    debts: dict[str, Any] = {}
    signaled = 0
    cibles = controles_pour(lesions)
    for chk in CHECKS:
        if cibles is not None and chk.__name__ not in cibles:
            continue
        if cibles is None and chk.__name__ in SUR_LESION_SEULEMENT:
            continue  # 7/11 : soin d'integrite (git, gh, 60 constats) jamais dans le balayage de chaque tick
        try:
            r = chk(armed)
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)[:120]}
        if r.get("signaled"):
            signaled += 1
        debts[chk.__name__.replace("check_", "")] = r
    elapsed = round(time.monotonic() - t0, 2)
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il inscrit le `pid`
    # qui manquait. Cet organe BAT sans etre au registre des services — sans pid, son
    # porteur restait inattribuable, donc son autorite de redemarrage inconnaissable.
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("remediation", elapsed_s=elapsed, armed=armed, signals=signaled)
    return {"ok": True, "elapsed_s": elapsed, "armed": armed, "signals_emitted": signaled, "debts": debts}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Remédiation autonomique des 8 dettes physiques")
    ap.add_argument("--armed", action="store_true", help="autorise auto-fix (orphan_reaper --arm)")
    a = ap.parse_args()
    print(json.dumps(run_remediation_cycle(armed=a.armed), indent=2, ensure_ascii=False))
