# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_llama_keeper_1

forge_llama_keeper.py — Lifecycle ON-DEMAND du modèle local llama-server (mirror
forge_docker_keeper : monitor-only + on-demand). Empêche le bug racine du 2026-06-02 :
llama-server immobilisait 7.1GB AU REPOS → RAM 85% → tout job lourd (veille/embed)
OOM le hub. [[chunks_tiering_embed_eco_2026-06-02]] [[supervisor_load_fixes_2026-06-01]]

POLITIQUE (selon RAM dispo, comme demandé) :
- RAM% >= FREE_AT (def 80) ET llama-server idle (0 connexion active :8080/:8091)
  -> DÉCHARGE (terminate) tous les llama-server -> libère ~7GB.
- RAM% <= RELOAD_OK (def 55) ET llama down ET WANT_LOCAL -> RECHARGE (start_llamacpp_native).
- Entre les deux : ne touche à rien (hystérésis anti-flap).
- Tue aussi les DOUBLONS llama-server CODER (garde le plus gros) dès >1.

POURQUOI `ungoverned_n` (2026-07-16) : les PROTÉGÉS (embed :8099, reranker, gemma) sont
hors dédup/unload PAR CONSTRUCTION (default-deny `_is_coder`). C'est VOULU et la Tâche #12
a eu raison. Mais ce keeper est le SEUL à compter les llama-server : quand il publie
`action: none` sur un tissu qu'il ne gouverne pas, il rend « tout va bien » indiscernable
de « je ne regarde pas ». D'où `ungoverned_n` au heartbeat.

CE QU'IL A FAIT SORTIR, DÈS LE PREMIER TICK : 3 llama-server pour 2 attendus. Enquête ->
2× LISTENING sur :8099. Le superviseur (`:8765/supervisor/status`) revendique **pid 4716
= NokidoLlamaEmbed** (restarts=0) et NE revendique PAS l'autre : enfant VIVANT lancé par
deno puis perdu de son registre (zombie-gap / `state.proc=null` de la course de génération,
cf [[supervised_service_restart_gotcha_2026-07-01]] + [[supervisor_doom_loop_generation_race_2026-07-03]]).
Ce n'est donc PAS de la nécrose faute d'éboueur : c'est une perte de TRACKING en AMONT.
Le keeper ne doit pas « nettoyer » ça — ce serait tuer à l'aveugle un enfant du superviseur.
Son rôle s'arrête à le DIRE ; la réparation est chez le superviseur.

⚠️ PIÈGE MESURÉ, coûteux : le RSS n'est PAS un signal de propriété. L'orphelin faisait
665Mo, le service LÉGITIME 303Mo. La convention « garde le plus gros » (étape 1 ci-dessous,
appliquée aux coders) aurait gardé l'orphelin et TUÉ NokidoLlamaEmbed. La propriété se
DEMANDE au superviseur, elle ne se déduit ni du RSS, ni du port, ni de netstat.

PERMS : doit tourner EN COMPTE SERVICE (via superviseur Master / NSSM) pour pouvoir
terminate le llama-server (lancé par le service). Depuis le sandbox = AccessDenied.
-> wirer dans services.toml (cf. tâche). En attendant : run_job sous compte adéquat.

ENV : LAFORGE_LLAMA_KEEPER_FREE_AT, _RELOAD_OK, _IDLE_SEC, _WANT_LOCAL (1/0),
      _INTERVAL (s), _MONITOR_ONLY (1 = log seulement, ne kill pas).
"""
from __future__ import annotations

import os
import time

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

FREE_AT = float(os.environ.get("LAFORGE_LLAMA_KEEPER_FREE_AT", "80"))
RELOAD_OK = float(os.environ.get("LAFORGE_LLAMA_KEEPER_RELOAD_OK", "55"))
INTERVAL = int(os.environ.get("LAFORGE_LLAMA_KEEPER_INTERVAL", "30"))
WANT_LOCAL = os.environ.get("LAFORGE_LLAMA_KEEPER_WANT_LOCAL", "1") not in ("0", "false", "")
MONITOR_ONLY = os.environ.get("LAFORGE_LLAMA_KEEPER_MONITOR_ONLY", "0") in ("1", "true")
# MODE PILIERS (2026-09-20) — sert les piliers RAG SANS toucher au coder.
#
# Ce keeper est `disabled = true` depuis le 2026-09-05, pour un motif qui ne vise
# QU'UNE de ses sept sections : « rallumait le coder (4,8 Go) sur llama.wanted pose
# en boucle par forge_viable_system -> deadlock documente 19/08 ». Le gel a emporte
# les six autres, dont `_piliers_on_demand` -- SEUL consommateur de `rerank.wanted`
# et `embed.wanted`. Cout mesure : :8100 ferme, NokidoEpistemicSoif en defer
# eternel, et le dernier pouls de ce keeper (2026-09-05T20:36:02) est la minute
# exacte de la mort notee au SSoT. Un organe entier eteint pour un defaut sur une
# seule de ses fonctions.
#
# MONITOR_ONLY ne pouvait pas servir ici : il neutralise AUSSI les piliers
# (`if MONITOR_ONLY: return [would ...]`). Observer n'est pas servir.
#
# Sous ce mode : aucune primitive destructrice n'est atteignable (`_kill` des
# doublons, de la decharge et du reconcile zombie-gap) et `_start_local` -- la
# section EXACTEMENT en cause -- ne tire pas. `_piliers_on_demand`, `_drain_on_demand`
# et le degel d'Ollama continuent : ils passent par `forge_ensure_service.ensure`,
# route gouvernee, JAMAIS par `_kill`.
#
# L'OBSERVATION N'EST PAS FALSIFIEE : `coder` reste calcule pour de vrai et
# `coder_n` continue de dire ce qui tourne. Neutraliser en vidant la liste aurait
# fabrique le faux calme que ce depot combat -- on retire le POUVOIR d'agir, jamais
# la CAPACITE de voir.
# Garde : tests/nr/test_keeper_piliers_only_nr.py
PILIERS_ONLY = os.environ.get("LAFORGE_LLAMA_KEEPER_PILIERS_ONLY", "0") in ("1", "true")
# Le corps ne gouverne le coder que hors de ce mode. Nom unique, lu partout.
_GOUVERNE_CODER = not PILIERS_ONLY


def _serving_pids() -> set:
    """Qui ECOUTE sur les ports geres (_MANAGED_PORTS) -- identification par CAPACITE
    SERVIE, ni par nom d'executable ni par cmdline.

    2026-07-17 : le seul critere fiable des deux. (a) le NOM ment -- le fallback pip
    llama-cpp-python de _start_local() est un python.exe/uvicorn, pas un
    llama-server.exe ; (b) la CMDLINE est inaccessible -- psutil leve AccessDenied sur
    un process d'un autre compte (mesure : AccessDenied meme sous le compte owner).
    Le port, lui, se demande a l'OS sans ACL. Cf "recuperation par capacites servies".
    """
    import psutil

    out = set()
    try:
        for c in psutil.net_connections("tcp"):
            if (c.status == "LISTEN" and c.laddr and c.pid
                    and str(c.laddr.port) in _MANAGED_PORTS):
                out.add(c.pid)
    except Exception:
        pass  # prudence : pas de vue reseau -> ensemble vide, on ne devine pas
    return out


def _ollama_pids() -> set:
    """PIDs des process ollama.exe (parents de ses modeles keep_alive)."""
    import psutil
    out = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info["name"] or "").lower() == "ollama.exe":
                out.add(p.info["pid"])
        except Exception:
            pass
    return out


def _ollama_child_pids(llama_pids) -> set:
    """Parmi les llama-server observes, ceux dont le PARENT est ollama = modeles
    keep_alive gouvernes PAR OLLAMA (self-unload a expiration). NI orphelins
    superviseur, NI a reclamer par ce keeper -> a EXCLURE du compte ungoverned
    (sinon fausse alarme 'orphelin superviseur', mesure owner 2026-07-23). Le ppid
    se lit sans ACL, contrairement a la cmdline."""
    import psutil
    ollama = _ollama_pids()
    out = set()
    if not ollama:
        return out
    for _rss, pid in llama_pids:
        try:
            if psutil.Process(pid).ppid() in ollama:
                out.add(pid)
        except Exception:
            pass
    return out


def _llama_pids():
    """Tissu llama observe = les llama-server.exe + TOUT process qui SERT un port gere.

    2026-07-17 : filtrer sur le seul nom "llama-server.exe" rendait l'enfant de ce
    keeper INVISIBLE a ce keeper (le fallback pip est un python.exe) -> coder_n=0 ->
    la regle FREE_AT ne se declenchait JAMAIS -> ~5 GB jamais rendus a RAM 78-95%,
    3 respawns en 28 min. Une classe exemptee du balayage est une zone que plus rien
    ne ramasse.
    """
    import psutil

    out, seen = [], set()
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            if (p.info["name"] or "").lower() == "llama-server.exe":
                out.append((p.info["memory_info"].rss, p.info["pid"]))
                seen.add(p.info["pid"])
        except Exception:
            pass
    for pid in _serving_pids():
        if pid in seen:
            continue
        try:
            out.append((psutil.Process(pid).memory_info().rss, pid))
            seen.add(pid)
        except Exception:
            pass
    out.sort(reverse=True)  # plus gros d'abord
    return out


# Tâche #12 : NE JAMAIS killer l'embedder (:8099 BGE-M3) ni le reranker -> casserait
# le RAG (ce sont des llama-server aussi). Reconnus par leur cmdline (port/modèle).
# 2026-06-14 : +9379/gemma3-1b = routeur gemma du CLI Gemini (gemmaModelRouter, classe
# flash<->pro en LOCAL = économie quota Pro). Petit (~1-2GB) mais latency-critique à chaque
# tour Gemini : l'évincer sous pression VRAM = crash node Gemini. Donc protégé (homéostasie
# iGPU : le gros llama-server du swarm cède, gemma reste). Override via LAFORGE_LLAMA_KEEPER_PROTECT.
_PROTECT_MARKERS = [m.strip().lower() for m in os.environ.get(
    "LAFORGE_LLAMA_KEEPER_PROTECT", "8099,bge-m3,embed,rerank,9379,gemma3-1b").split(",") if m.strip()]


def _is_protected(pid: int) -> bool:
    import psutil

    try:
        cl = " ".join(psutil.Process(pid).cmdline()).lower()
        return any(m in cl for m in _PROTECT_MARKERS)
    except Exception:
        return True  # prudence : si on ne sait pas -> protéger (ne pas killer)

# Tâche #12 (close 2026-06-12) : DEFAULT-DENY. Seul un llama-server écoutant sur un
# port GÉRÉ (8080/8091 = coder on-demand) est éligible dédup/unload/reload-count.
# Tout le reste (embed :8099, reranker :8100, router :8092, bitnet :8093, futur
# service llama) est intouchable PAR CONSTRUCTION — plus besoin d'énumérer chaque
# protégé (bitnet/router n'étaient pas couverts par les markers).
_MANAGED_PORTS = [m.strip() for m in os.environ.get(
    "LAFORGE_LLAMA_KEEPER_MANAGED_PORTS", "8080,8091").split(",") if m.strip()]

# Anti-flap : delai minimal entre un unload et le reload suivant. Cf tick() etape 3.
RELOAD_COOLDOWN_S = float(os.environ.get("LAFORGE_LLAMA_KEEPER_RELOAD_COOLDOWN_S", "600"))
_LAST_UNLOAD_TS = 0.0

# INTENTION NON CONSOMMEE (owner 2026-08-19). Une intention protegeait un backend
# de facon ABSOLUE tant qu'elle etait fraiche, sans jamais croiser « on me le
# reclame » avec « quelqu'un s'en sert ». Mesure du jour : `forge_llm_ondemand.
# _poser_drapeau` repose `llama.wanted` toutes les ~300 s alors que le TTL est de
# 900 s -- le drapeau ne PERIME donc JAMAIS, `_intention_perimee` ne rend jamais
# True, et le coder tenait 4,82 Go avec `active_conns=0` en affichant
# `unload_differe`. L'extinction on-demand etait neutralisee en permanence.
#
# Le delai de grace reste ENTIER : un cerveau qu'on vient d'allumer est inactif
# PAR DEFINITION (regression du 2026-07-26, quatre allumages fauches en 15-30 s).
# On ne mesure donc pas l'age du drapeau -- il est remis a zero a chaque repose --
# mais la duree CONTINUE a zero connexion, qui elle ne triche pas.
_INUTILE_S = float(os.environ.get("LAFORGE_LLAMA_INTENTION_INUTILE_S", "600"))
_ZERO_CONNS_DEPUIS = 0.0


def _maj_inutilite(conns: int, coder: list) -> float:
    """Duree CONTINUE (s) pendant laquelle un coder tourne sans servir. 0 = sert.

    L'horodatage est relu du heartbeat au demarrage : un keeper qui redemarre
    repartirait sinon de zero a chaque fois et l'intention menteuse redeviendrait
    protectrice indefiniment -- le compteur doit survivre au processus qui le tient.
    """
    global _ZERO_CONNS_DEPUIS
    if conns != 0 or not coder:
        _ZERO_CONNS_DEPUIS = 0.0
        return 0.0
    if not _ZERO_CONNS_DEPUIS:
        repris = 0.0
        try:
            import json as _j

            with open(_HB, encoding="utf-8") as _f:
                repris = float(_j.load(_f).get("zero_conns_depuis") or 0.0)
        except Exception:  # noqa: BLE001 - pas d'antecedent lisible : on repart de maintenant
            repris = 0.0
        _ZERO_CONNS_DEPUIS = repris or time.time()
    return max(0.0, time.time() - _ZERO_CONNS_DEPUIS)

def _is_coder(pid: int) -> bool:
    # La CAPACITE SERVIE tranche EN PREMIER : elle ne depend d'aucune ACL, la cmdline si.
    # L'ancien `except -> return False` etait prudent contre un kill a l'aveugle, mais il
    # rendait AUSSI le keeper aveugle a son propre enfant (AccessDenied = False = jamais
    # gouverne = jamais decharge). Aucun protege n'ecoute sur 8080/8091 (gemma 9379,
    # embed 8099, reranker 8100) -> servir un port gere suffit a qualifier ; le veto
    # _PROTECT_MARKERS reste applique des que la cmdline est lisible.
    import psutil

    serving = pid in _serving_pids()
    try:
        cl = " ".join(psutil.Process(pid).cmdline()).lower()
    except Exception:
        return serving  # cmdline muette -> la capacite servie decide
    if any(m in cl for m in _PROTECT_MARKERS):
        return False
    return serving or any(p in cl for p in _MANAGED_PORTS)


def _active_conns() -> int:
    import psutil

    try:
        return sum(
            1 for c in psutil.net_connections("tcp")
            if c.laddr and c.laddr.port in (8080, 8091) and c.status == "ESTABLISHED"
        )
    except Exception:
        return 1  # prudence : si on ne sait pas, considérer actif (ne pas killer)


_GEMMA_PORT = int(os.environ.get("LAFORGE_GEMMA_ROUTER_PORT", "9379"))


def _gemma_up() -> bool:
    """Le routeur gemma du CLI Gemini (:9379, gemmaModelRouter) écoute-t-il ? Si oui il a la
    PRIORITÉ iGPU (latency-critique à CHAQUE tour Gemini) : sur 4GB partagés, gemma + coder 7B
    = OOM -> crash node Gemini. Le coder doit céder. Fail-safe : indéterminé -> False (ne force pas
    l'éviction sur un doute)."""
    import psutil

    try:
        return any(
            c.laddr and c.laddr.port == _GEMMA_PORT and c.status == "LISTEN"
            for c in psutil.net_connections("tcp")
        )
    except Exception:  # noqa: BLE001
        return False


def _intention_voulue(nom_fichier: str, ttl_s: float = 900.0) -> bool:
    """Le corps VEUT-il ce service maintenant ? (drapeau d'intention, TTL 900 s)

    MEME mecanisme que `docker.wanted`, lu par forge_resource_manager.
    get_active_intents : un seul vocabulaire d'intention pour tout l'organisme,
    sinon deux organes se contredisent en toute bonne foi. En cas de doute
    (fichier illisible), on rend False -- une intention qu'on ne sait pas lire
    n'autorise rien, elle ne bloque rien non plus.
    """
    try:
        import os as _o
        import time as _t

        _p = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                          "sandbox", nom_fichier)
        return _o.path.exists(_p) and (_t.time() - _o.path.getmtime(_p)) < ttl_s
    except Exception:  # noqa: BLE001
        return False


def _intention_perimee(nom_fichier: str, ttl_s: float = 900.0):
    """True = le drapeau EXISTE mais a EXPIRE ; False = encore frais ;
    None = drapeau ABSENT, donc aucune intention n'a jamais ete posee.

    La distinction porte une decision, elle n'est pas cosmetique.
    Drapeau ABSENT : Nokido n'a JAMAIS demande ce backend. S'il tourne quand
    meme, c'est l'owner qui l'a lance a la main, et on ne retire pas un outil
    des mains de son proprietaire -- meme regle que `est_pilote` pour LM Studio.
    Drapeau PERIME : c'est bien Nokido qui l'a allume, et plus personne ne le
    veut. La ou `_intention_voulue` rend False dans les DEUX cas, ici on les
    separe, parce qu'ils appellent des gestes opposes.
    """
    try:
        import os as _o
        import time as _t

        _p = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                          "sandbox", nom_fichier)
        if not _o.path.exists(_p):
            return None
        return (_t.time() - _o.path.getmtime(_p)) >= ttl_s
    except Exception:  # noqa: BLE001 - illisible : on ne conclut rien
        return None


def _kill(pid: int) -> bool:
    import psutil

    # GATE world-model (owner 2026-07-23) : anticiper avant de tuer. Un duplicata/zombie
    # (pid != legit revendique) est autorise ; tuer le LEGIT d'un service essentiel dont
    # d'autres dependent est refuse (sauf force). Best-effort : indispo -> ne bloque pas.
    try:
        import os as _o
        import sys as _s
        _app = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_body_world_model import guard as _guard
        _g = _guard(pid, "kill")
        if not _g.get("allowed", True):
            print(f"[llama-keeper] kill {pid} REFUSE par world-model: "
                  f"{_g['impact'].get('reason')}", flush=True)
            return False
    except Exception:  # noqa: BLE001
        pass

    try:
        p = psutil.Process(pid)
        p.terminate()
        p.wait(timeout=8)
        return True
    except Exception as e:
        print(f"[llama-keeper] kill {pid} échoué (perms ? lancer en compte service): {e}", flush=True)
        return False


def _start_local():
    # Chemin 1 = profil LITE natif :8091 (wake_llama_native --lite, validé 2026-06-12 :
    # iGPU 780M safe — ngl=20, no draft, ctx 8192 ; le profil FULL crashe la VRAM 4GB).
    # Le script self-check « déjà up » + healthcheck -> idempotent entre ticks.
    # 2026-07-17 : etait C:\tmp\wake_llama_native.py. Le renommage LaForge->Nokido
    # (scope = depot) n'a jamais balaye C:\tmp -> le script y cherchait encore
    # "LaForgeLlamaNative" -> rc=2 -> chute SILENCIEUSE en Chemin 2. Tracke dans
    # tools/, il suit desormais les renommages.
    wake = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "forge_wake_llama_native.py")
    if os.path.exists(wake):
        import subprocess
        import sys

        try:
            r = subprocess.run(
                [sys.executable, wake, "--lite"],
                capture_output=True, text=True, errors="replace", timeout=180,
            )
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            print(f"[llama-keeper] wake --lite rc={r.returncode}: {out[-300:]}", flush=True)
            if r.returncode == 0:
                return
        except Exception as e:
            print(f"[llama-keeper] wake --lite échoué: {e}", flush=True)
    # Chemin 2 (fallback historique) : serveur pip llama-cpp-python (:8080)
    try:
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from nokido_agent.tools.forge_services_launcher import start_llamacpp_native

        r = start_llamacpp_native()
        print(f"[llama-keeper] reload local: {r}", flush=True)
    except Exception as e:
        print(f"[llama-keeper] reload échoué: {e}", flush=True)


def _supervisor_claimed() -> dict:
    """port RAG -> pid REVENDIQUE par le superviseur (8099 embed, 8100 reranker).
    La legitimite se DEMANDE au superviseur (registre), JAMAIS deduite du RSS/port
    (l'orphelin faisait 665Mo, le legitime 303Mo, mesure 07-16). Vide si injoignable
    -> on ne devine pas, on ne reconcilie pas."""
    import json as _j
    import urllib.request as _u
    name_port = {"NokidoLlamaEmbed": 8099, "NokidoLlamaReranker": 8100}
    out = {}
    try:
        with _u.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=4) as r:
            svc = _j.loads(r.read()).get("services", {})
        for n, port in name_port.items():
            i = svc.get(n) or {}
            if i.get("status") == "running" and i.get("pid"):
                out[port] = int(i["pid"])
    except Exception:
        pass
    return out


def _conns_port(port: int) -> int:
    """Connexions ETABLIES sur un port. Rend -1 si ILLISIBLE — jamais 0.

    Trois etats, jamais deux : un capteur qui rend 0 pour « pas de trafic » ET pour
    « je n'ai pas pu regarder » ferait eteindre un pilier EN PLEIN TRAVAIL. Le -1
    ne satisfait aucune condition d'extinction : on s'abstient par construction.
    """
    import psutil

    try:
        return sum(1 for c in psutil.net_connections(kind="inet")
                   if c.laddr and c.laddr.port == port and c.status == "ESTABLISHED")
    except Exception:  # noqa: BLE001
        return -1


# Piliers RAG lourds : (service, port, drapeau d'intention).
_PILIERS = (("NokidoLlamaEmbed", 8099, "embed.wanted"),
            ("NokidoLlamaReranker", 8100, "rerank.wanted"))

# Le drapeau appartient au SERVICE : on le redemande a `_PILIERS` plutot que de
# le relire dans la chaine `raison`, qui est de la prose destinee a un humain.
_DRAPEAU_PAR_SERVICE = {nom: drapeau for nom, _port, drapeau in _PILIERS}


def _observer_signal(signal: str) -> None:
    """CONSTATE la lecture d'une intention par ce site.

    MESURE 2026-09-20 (`forge_signal_coupling`) :

        rerank.wanted   EMIS 0   LU 1   TRANSDUIT 0
        lecteur : forge_resource_manager.get_active_intents
                  n = 36 799, derniere lecture il y a 46,8 s

    Le signal n'est donc PAS ignore -- il est lu massivement et en continu. Mais
    son seul lecteur lit pour EPARGNER le service, jamais pour le RALLUMER : il
    fixe le ligand et n'a aucun domaine de signalisation. C'est le RECEPTEUR
    LEURRE (OPG, ACKR3) que `forge_rag_warmup` documente deja pour les hormones.
    Etat reel : CONSUMER_NO_EFFECT -- surtout pas CONSUMER_DEAD.

    Sans cette declaration, « lu sans agir » et « ce code n'a pas tourne » sont
    indistinguables, et accuser le second est le faux positif qui fait desarmer
    un garde.
    """
    try:
        from nokido_agent.app.forge_signal_coupling import observe_signal as _obs

        _obs(signal, consumer="forge_llama_keeper._piliers_on_demand")
    except Exception:  # noqa: BLE001 - muet-ok : un capteur de couplage ne doit
        pass          # JAMAIS casser la regulation qu'il observe.


def _transduire_signal(signal: str) -> None:
    """CONSTATE l'EFFET, au site de l'effet -- la seule preuve qu'une voie transduit.

    Patron copie de `forge_rag_warmup.warmup_rag`, eprouve sur TSH/INSULIN depuis
    le 2026-08-05 : `_observer` au site de la LECTURE, `_transduire` au site de
    l'EFFET. On ne l'appelle QUE sur un `ensure` reussi -- une abstention de
    l'arbitre ou un `ok=False` ne sont pas des effets, et les compter ferait
    declarer COUPLEE une voie qui n'agit jamais (`attempt != success`).
    """
    try:
        from nokido_agent.app.forge_signal_coupling import transduce_signal as _tr

        _tr(signal, consumer="forge_llama_keeper._piliers_on_demand")
    except Exception:  # noqa: BLE001 - muet-ok, meme raison
        pass


def _dette_embed() -> int:
    """Chunks sans vecteur, lus depuis l'evenement d'organe DEJA calcule ailleurs.

    On ne recompte pas 700k lignes a chaque tick : `embed_consolidation_debt` est
    emis par le capteur de dette, on le CONSOMME. Rend -1 si ILLISIBLE — jamais 0 :
    un capteur muet ne doit pas se lire comme « plus de dette », sinon le drain
    s'eteindrait sur une absence de mesure au lieu d'une mesure d'absence.
    """
    try:
        import sys as _s

        _ad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
        if _ad not in _s.path:
            _s.path.insert(0, _ad)
        from nokido_agent.app import forge_critical_events as _ce  # type: ignore

        evts = _ce.unprocessed(30) or []
    except Exception:  # noqa: BLE001
        return -1
    for e in evts:
        if isinstance(e, dict) and e.get("kind") == "embed_consolidation_debt":
            try:
                return int((e.get("payload") or {}).get("hot_null") or 0)
            except Exception:  # noqa: BLE001
                return -1
    return 0


# Dette minimale avant d'armer le drain : evite de le faire flapper sur quelques chunks.
DETTE_MIN = int(os.environ.get("LAFORGE_EMBED_DETTE_MIN", "1000"))


def _drain_on_demand(ram: float) -> list:
    """Allume le drain de vectorisation quand il y a de la DETTE et que l'embedder
    repond ; l'eteint quand la dette est resorbee.

    Mesure 2026-08-10 : 150 681 chunks sans vecteur dormaient derriere un compteur
    d'alerte que personne ne detaillait, avec NokidoEmbedTrigger en disabled=true et
    deps=[8099]. L'embedder coupe au boot empechait le drain de demarrer, et RIEN ne
    le redemandait — la dette ne pouvait que croitre. Le drain suit donc la meme
    logique que les piliers, a ceci pres qu'il est pilote par un besoin MESURE (la
    dette) et non par une intention declaree : c'est du travail en attente, pas une
    envie. Un drain sans dette ne sert a rien ; une dette sans drain ne se resorbe
    jamais.
    """
    dette = _dette_embed()
    if dette < 0:
        return []  # illisible -> abstention, on n'eteint pas sur une non-mesure
    embed_up = 8099 in _supervisor_claimed()
    hb = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "sandbox", "embed_auto_trigger.heartbeat")
    try:
        vivant = os.path.exists(hb) and (time.time() - os.path.getmtime(hb)) < 300.0
    except Exception:  # noqa: BLE001
        return []  # heartbeat illisible -> abstention
    nom = "NokidoEmbedTrigger"
    if dette >= DETTE_MIN and embed_up and not vivant and ram <= FREE_AT:
        acte, raison = "running", f"dette={dette} chunks + embedder up + ram {ram:.0f}%"
    elif dette == 0 and vivant:
        acte, raison = "stopped", "dette resorbee"
    else:
        return []
    if MONITOR_ONLY:
        return [f"would {nom}->{acte} ({raison})"]
    try:
        from nokido_agent.tools.forge_ensure_service import ensure as _ensure

        res = _ensure(nom, acte)
        ok = bool((res or {}).get("success")) if isinstance(res, dict) else bool(res)
        print(f"[llama-keeper] drain {nom} -> {acte} ok={ok} :: {raison}", flush=True)
        return [f"{nom}->{acte} ok={ok} ({raison})"]
    except Exception as e:  # noqa: BLE001
        print(f"[llama-keeper] drain {nom} -> {acte} ECHOUE: {e!r}", flush=True)
        return [f"{nom}->{acte} ECHOUE"]


def _pilier_accorde(drapeau: str) -> bool:
    """Le corps accorde-t-il encore ce pilier ? (politique `config/pillar_policy.json`)

    Arbitre absent ou illisible => True. Le keeper ne coupe jamais sur une absence
    de mesure : c'est la meme regle que `_dette_embed()` qui rend -1 et fait
    s'abstenir plutot que d'arreter.
    """
    try:
        from nokido_agent.app.forge_pillar_arbiter import pilier_accorde as _pa

        return _pa(drapeau, "keeper")
    except Exception as e:  # noqa: BLE001 - arbitre indisponible : on n'agit pas dessus
        print(f"[llama-keeper] arbitre indisponible ({e!r}) -- pilier non filtre", flush=True)
        return True


def _pilier_inutile(nom: str, port: int, drapeau: str, conns: int, up: bool) -> bool:
    """Ce pilier tourne-t-il pour RIEN ? (independant de la pression RAM)

    Trois conditions, et un garde par pilier :

    * `up` et `conns == 0` : il est la et ne sert personne MAINTENANT ;
    * intention PERIMEE, pas absente. Un drapeau absent veut dire que Nokido n'a
      jamais demande ce backend -- c'est alors l'owner qui l'a lance, et on ne
      retire pas un outil des mains de son proprietaire (meme regle que
      `_intention_perimee` pour le coder).
    * GARDE EMBEDDER : tant qu'il reste de la DETTE de vectorisation, l'embedder
      travaille meme sans connexion ouverte a l'instant du tick (le drain fait des
      rafales). Le couper la relancerait le cercle mesure le 2026-08-10 :
      l'embedder eteint empeche le drain de demarrer, et RIEN ne le redemande --
      la dette ne peut alors que croitre. `_dette_embed()` rend -1 si le capteur
      est MUET : on s'abstient aussi dans ce cas, une non-mesure n'autorise pas
      un arret.

    Le reranker n'a pas besoin d'un tel garde : sa perte est BORNEE et mesuree
    (`forge_rag_engine` : -0.10 R@1 / -0.06 NDCG@10) et il a deux filets, Cohere
    puis lexical. Le RAG le redemande lui-meme (`rerank.wanted`) des qu'une
    recherche le veut.
    """
    if not up or conns != 0:
        return False
    if not _pilier_accorde(drapeau):
        # Le corps ne l'accorde plus : il est inutile MEME avec de la dette, puisque
        # la politique nomme un substitut qui l'absorbe. Sans cette sortie anticipee,
        # le GARDE EMBEDDER ci-dessous rendait le pilier local inevincable a vie : la
        # dette ne tombe jamais a zero pendant qu'un autre chemin la traite.
        return True
    if _intention_perimee(drapeau) is not True:
        return False          # fraiche, ou ABSENTE (outil de l'owner) -> on n'y touche pas
    if port == 8099 or "Embed" in nom:
        dette = _dette_embed()
        if dette != 0:        # dette restante OU capteur muet (-1) -> on s'abstient
            return False
    return True


def _piliers_on_demand(ram: float) -> list:
    """Allume/eteint les piliers RAG selon (intention x RAM dispo). Directive owner
    2026-08-10 : « les services necessitant trop de RAM devraient etre lances
    dynamiquement, et coupes dynamiquement, lorsque de la RAM est disponible ».

    Ils etaient traites en TOUT ou RIEN : `disabled = true` au boot pour tenir la
    RAM, donc JAMAIS la. Cout mesure le meme jour : NokidoEpistemicSoif declare
    deps=[8099, 8100] et restait bloque en « starting » sans jamais journaliser --
    une mort silencieuse causee par une decision de RAM, pas par un bug.

    On reutilise la politique DEJA eprouvee du coder (FREE_AT / RELOAD_OK /
    intention TTL 900 s) au lieu d'en inventer une seconde : deux politiques de
    regulation sur la meme ressource finissent par se contredire de bonne foi.

    Le passage se fait par `forge_ensure_service.ensure` (route gouvernee), JAMAIS
    par `_kill` : `_PROTECT_MARKERS` reste entier et ces piliers ne doivent pas etre
    abattus au milieu d'une vectorisation.
    """
    claimed = _supervisor_claimed()
    if not claimed and not any(_intention_voulue(d) for _, _, d in _PILIERS):
        return []  # superviseur muet ET aucune intention -> rien a decider
    actes = []
    _bloc: list[str] = []   # besoins exprimes et NON satisfaits, a rendre visibles
    for nom, port, drapeau in _PILIERS:
        # Une intention REFUSEE par le corps n'est pas une intention. Sans ce filtre,
        # un drapeau residuel (TTL 900 s) rallumait le pilier apres que la politique
        # l'eut ecarte -- le client aurait garde le dernier mot sur la regulation.
        # LECTURE CONSTATEE ICI, EFFET CONSTATE PLUS BAS. Les deux sont necessaires :
        # sans la lecture, l'absence d'effet ne distingue pas le recepteur leurre du
        # code qui n'a pas tourne.
        _observer_signal(drapeau)
        voulu = _intention_voulue(drapeau) and _pilier_accorde(drapeau)
        up = port in claimed
        conns = _conns_port(port)
        if voulu and not up and ram <= RELOAD_OK:
            actes.append((nom, "running",
                          f"intention {drapeau} + ram {ram:.0f}% <= {RELOAD_OK:.0f}%"))
        elif (not voulu) and up and ram >= FREE_AT and conns == 0:
            actes.append((nom, "stopped",
                          f"sans intention + idle + ram {ram:.0f}% >= {FREE_AT:.0f}%"))
        elif _pilier_inutile(nom, port, drapeau, conns, up):
            # INUTILITE PILIER -- decharge INDEPENDANTE de la pression RAM.
            # Meme correction que pour le coder (2026-08-19) : toute la decharge
            # etait conditionnee a `ram >= FREE_AT`, donc un pilier dont plus
            # personne ne veut restait allume tant que la machine n'etouffait pas.
            # MESURE du jour : reranker :8100 a 1,43 Go et embedder :8099 a 3,23 Go
            # TOUJOURS la avec `rerank.wanted` perime depuis 1137 s et zero
            # connexion -- simplement parce que la RAM etait redescendue a 58 %.
            # Directive owner : « arreter systematiquement tout ce qui n'est pas
            # utile, puis ne rallumer QUE quand c'est necessaire ». Reguler sur la
            # seule pression, c'est attendre la detresse pour agir.
            actes.append((nom, "stopped",
                          f"INUTILE : {drapeau} perime + 0 connexion "
                          f"(ram {ram:.0f}%, non declenchant)"))
        elif voulu and not up:
            # CONTENTION : le pilier est RECLAME et ne demarre pas. Sans cette
            # branche, le heartbeat rendait `piliers: -` -- c'est-a-dire « rien a
            # signaler » -- alors qu'un besoin exprime restait insatisfait.
            # MESURE 2026-08-19 : `embed.wanted` frais depuis 444 s, RAM a 78 %
            # parce que le coder (4,40 Go, `llama.wanted` frais lui aussi) tenait
            # la place. DEUX intentions fraiches, UNE seule place, AUCUN arbitre
            # -- et le silence faisait passer ce blocage pour un etat nominal.
            # Les 172 607 chunks sans vecteur attendaient derriere.
            # On ne tranche PAS ici : arbitrer entre deux consommateurs legitimes
            # est une politique, pas un correctif de keeper. On le NOMME.
            _bloc.append(
                f"{nom} RECLAME mais NON DEMARRE : ram {ram:.0f}% > {RELOAD_OK:.0f}% "
                f"(contention memoire, aucun arbitrage entre consommateurs)")
    if not actes:
        # ⚠️ On rend `_bloc` MEME sans acte : c'est precisement le cas ou le
        # keeper ne peut rien faire, et donc celui ou son silence trompe le plus.
        # Une liste vide se lit « tout va bien » ; un besoin insatisfait doit se
        # lire « je n'ai pas pu ».
        return _bloc
    if MONITOR_ONLY:
        return [f"would {n}->{e} ({r})" for n, e, r in actes] + _bloc
    faits = []
    for nom, etat, raison in actes:
        try:
            from nokido_agent.tools.forge_ensure_service import ensure as _ensure

            res = _ensure(nom, etat)
            ok = bool((res or {}).get("success")) if isinstance(res, dict) else bool(res)
            if ok:
                # SEUL chemin qui a REELLEMENT agi sur le corps. C'est ici -- et
                # nulle part ailleurs -- que `rerank.wanted` cesse d'etre
                # « LU SANS EFFET » dans `couplage()`.
                _drapeau = _DRAPEAU_PAR_SERVICE.get(nom)
                if _drapeau:
                    _transduire_signal(_drapeau)
            faits.append(f"{nom}->{etat} ok={ok} ({raison})")
            print(f"[llama-keeper] pilier {nom} -> {etat} ok={ok} :: {raison}", flush=True)
            if not ok:
                # Un `ok=False` disparaissait dans la liste des faits comme s'il
                # valait un succes. Il se lit desormais comme ce qu'il est : un
                # besoin exprime que le keeper n'a PAS su satisfaire.
                _bloc.append(f"{nom}->{etat} A ECHOUE ({raison})")
        except Exception as e:  # noqa: BLE001
            # PAS muet : un pilier qu'on croit rallume et qui ne l'est pas, c'est
            # exactement la mort silencieuse qu'on corrige ici.
            print(f"[llama-keeper] pilier {nom} -> {etat} ECHOUE: {e!r}", flush=True)
            faits.append(f"{nom}->{etat} ECHOUE")
    return faits + _bloc


# ── SONDE « scheduler Ollama fige » (mesure 2026-08-20) ──────────────────────
# Signature OBSERVEE : `/api/tags` rend 200 (il sert du CACHE, il ment donc sur
# la sante) PENDANT que `/api/ps` timeoute et qu'AUCUN `llama-server` enfant
# d'ollama n'existe. Ollama n'echoue pas : il ATTEND un slot chez des runners
# qu'il croit charges (`sched.go: "loaded runners" count=2`) et qui n'existent
# plus. Mesure qui tranche : compter les process pendant la requete -> ZERO
# tentative de spawn, donc ni VRAM insuffisante, ni modele trop lourd, ni file
# d'attente. Vecu : toute chaine passant par Ollama se fige, et l'owner
# reinstalle Ollama pour rien — le binaire est sain, l'etat interne ne l'est
# pas. Seul un REDEMARRAGE du service le remet a zero.
_OLLAMA_FIGE_N = 0
_OLLAMA_LAST_FIX_TS = 0.0
_OLLAMA_FIX_COOLDOWN_S = float(os.environ.get("LAFORGE_OLLAMA_FIX_COOLDOWN_S", "900"))
_OLLAMA_FIGE_CONFIRM = int(os.environ.get("LAFORGE_OLLAMA_FIGE_CONFIRM", "2"))


def _ollama_fige() -> str:
    """Rend "" si sain, sinon la RAISON. Jamais de verdict sur une non-mesure."""
    import json as _j
    import urllib.request as _u

    try:
        with _u.urlopen("http://127.0.0.1:11434/api/tags", timeout=4) as r:
            if int(getattr(r, "status", 0) or 0) != 200:
                return ""
    except Exception:
        return ""  # injoignable = panne FRANCHE (visible ailleurs), pas un figeage
    # `/api/ps` est LEGER : il ne charge aucun modele et repond en millisecondes
    # sur un scheduler sain. Le voir timeouter n'est donc pas « une lenteur ».
    try:
        with _u.urlopen("http://127.0.0.1:11434/api/ps", timeout=8) as r:
            _j.loads(r.read())
        return ""
    except Exception:
        pass
    try:
        import psutil as _psutil  # module-level absent ici : import LOCAL obligatoire

        _opids = _ollama_pids()
        _enfants = [p.pid for p in _psutil.process_iter(["name", "ppid"])
                    if "llama-server" in ((p.info.get("name") or "").lower())
                    and p.info.get("ppid") in _opids]
    except Exception:
        return ""  # mesure impossible -> on s'abstient, on ne redemarre pas au hasard
    if _enfants:
        return ""  # un runner VIT : chargement legitime en cours, on le laisse finir
    return "api/tags OK mais api/ps timeout ET 0 runner enfant"


def tick() -> dict:
    # _ZERO_CONNS_DEPUIS est ASSIGNE plus bas (remise a zero apres un unload) :
    # sans le declarer global ici, sa LECTURE dans cette meme fonction leve
    # `cannot access local variable` a chaque tick -- mesure 2026-08-19, le keeper
    # crashait en boucle et n'ecrivait plus de heartbeat. Le meme piege que
    # `global` apres usage qui a tue le hub le matin : une assignation quelque part
    # dans la fonction rend le nom local PARTOUT dans la fonction.
    global _LAST_UNLOAD_TS, _ZERO_CONNS_DEPUIS
    import psutil

    ram = psutil.virtual_memory().percent
    pids = _llama_pids()
    # Tâche #12 : les décisions lifecycle ne portent QUE sur les llama-server CODER
    # (ports gérés 8080/8091, default-deny via _is_coder). Compter tous les pids
    # faisait (a) garder l'embedder comme « plus gros » et tuer d'autres services en
    # dédup, (b) bloquer le reload tant que :8099 vivait (`not pids` jamais vrai)
    # -> le coder ne revenait JAMAIS en on-demand.
    coder = [(rss, pid) for rss, pid in pids if _is_coder(pid)]
    conns = _active_conns()
    # Tissu que ce keeper VOIT mais ne gouverne pas (protégé / non-coder). Un écart
    # normal vaut 2 (embed :8099 + reranker :8100), +1 si le routeur gemma tourne.
    # Au-delà = un llama-server que PERSONNE ici ne revendique -> le suspect n°1 est un
    # enfant orphelin du superviseur (vivant mais absent de son registre), pas un mort
    # à ramasser. Cf l'en-tête du module : mesuré le 2026-07-16.
    # On ne TUE PAS : un enfant du superviseur ne se tue pas depuis ce keeper, et le RSS
    # ne dit pas qui est légitime. On DÉCLARE, et on pointe vers l'organe qui SAIT.
    # Modeles ollama (parent=ollama) : self-managed via keep_alive, ni orphelins ni
    # a reclamer -> EXCLUS du compte ungoverned (fin de la fausse alarme 'orphelin
    # superviseur' sur un modele ollama legitime, mesure owner 2026-07-23).
    ollama_models = _ollama_child_pids(pids)
    ungoverned = len(pids) - len(coder) - len(ollama_models)
    state = {"ram": ram, "llama_n": len(pids), "coder_n": len(coder),
             "ollama_models_n": len(ollama_models),
             "ungoverned_n": ungoverned, "active_conns": conns,
             "action": "none", "gemma_up": _gemma_up()}
    expected = 2 + (1 if state["gemma_up"] else 0)
    if ungoverned > expected:
        state["health"] = "untracked"
        # ASCII PUR : cette note part dans le print() du daemon, et un stdout cp1252
        # sur un caractere non-latin1 leve UnicodeEncodeError = keeper mort. Deja
        # vecu (create_switch, U+2192). Le message ne vaut rien s'il tue l'organe.
        state["note"] = (f"{ungoverned} llama-server non gouvernes (attendu {expected}, "
                         f"hors {len(ollama_models)} modeles ollama) -- perte tracking "
                         "superviseur probable, verifier :8765/supervisor/status "
                         "(le RSS ne dit PAS qui est legitime)")

    # RECONCILE zombie-gap (owner 2026-07-23) : un port RAG avec un listener != pid
    # REVENDIQUE par le superviseur = enfant perdu du registre au boot -> terminate.
    # Legitimite DEMANDEE au superviseur, jamais deduite du RSS. Garde anti-fork : on
    # ne tue pas un worker enfant du legit. Le keeper a le droit (compte service) ; le
    # sandbox/trusted non (AccessDenied mesure 07-23). Proprioception -> regulation.
    if not MONITOR_ONLY and _GOUVERNE_CODER:
        _claimed = _supervisor_claimed()
        if _claimed:
            import psutil as _ps
            for _c in _ps.net_connections("tcp"):
                if not (_c.status == "LISTEN" and _c.pid and _c.laddr
                        and _c.laddr.port in _claimed):
                    continue
                _legit = _claimed[_c.laddr.port]
                if _c.pid == _legit:
                    continue
                try:  # garde : worker fork du legit -> ne pas tuer
                    if _ps.Process(_c.pid).ppid() == _legit:
                        continue
                except Exception:  # noqa: BLE001
                    pass
                # GARDE 1 -- QUI est perime, le listener ou le registre ?
                # Si le pid « legitime » n'est MEME PLUS VIVANT, c'est le registre
                # qui ment, pas le processus qui sert. Tuer le vivant au nom d'un
                # fantome, c'est reconcilier a l'envers. Mesure 2026-07-26 : le
                # superviseur annoncait NokidoLlamaNative running sur le pid 21292
                # DEJA MORT, et ce chemin a fauche quatre demarrages successifs du
                # cerveau codeur en 15-30 s -- sans pression RAM (8,77 Go libres) et
                # sans la moindre trace dans le journal de cycle de vie.
                try:
                    _legit_vivant = _ps.pid_exists(int(_legit))
                except Exception:  # noqa: BLE001
                    _legit_vivant = True  # doute -> comportement historique
                if not _legit_vivant:
                    print(f"[llama-keeper] :{_c.laddr.port} listener {_c.pid} EPARGNE -- "
                          f"le pid revendique {_legit} est mort (registre perime, "
                          "pas le listener)", flush=True)
                    state.setdefault("registre_perime", []).append(_c.laddr.port)
                    continue
                # GARDE 2 -- intention a la demande. Meme drapeau que docker.wanted,
                # pose par forge_llm_ondemand : on n'evince pas ce que l'owner vient
                # d'allumer. Sans lui, allumer et faucher se repondaient en boucle.
                if _c.laddr.port == 8091 and _intention_voulue("llama.wanted"):
                    print(f"[llama-keeper] :8091 listener {_c.pid} EPARGNE -- "
                          "intention llama.wanted posee", flush=True)
                    state.setdefault("epargnes_intention", []).append(_c.pid)
                    continue
                if _kill(_c.pid):
                    state.setdefault("reconciled", []).append(_c.pid)
                    state["action"] = "reconciled_dup"

    # NOTE 2026-06-14 : iGPU 780M = 8.59GB VRAM dédiée (PAS 4GB). coder 7B + gemma + embedder
    # (~7.7GB) cohabitent -> PAS d'éviction coder pour gemma (l'ancienne règle reposait sur une
    # fausse prémisse 4GB). gemma reste protégé de l'éviction (_PROTECT_MARKERS). Si OOM réel
    # observé sous charge, ré-introduire une éviction CONDITIONNELLE (mesure VRAM, pas "gemma up").

    # 1. Doublons : >1 llama-server CODER -> kill tous sauf le plus gros (gâchis RAM)
    if len(coder) > 1 and not MONITOR_ONLY and _GOUVERNE_CODER:
        for _rss, pid in coder[1:]:
            if _kill(pid):
                state["action"] = "killed_dup"

    # 2. RAM tight + idle -> décharge les coders (protégés intouchés, RAG préservé)
    #
    # GARDE D'INTENTION (2026-07-26) : un cerveau qu'on VIENT d'allumer est
    # inactif PAR DEFINITION -- personne n'a encore eu le temps de l'interroger.
    # Cette regle le condamnait donc a la seconde ou il naissait : mesure du
    # jour, `action: unloaded` avec ram 82.1 >= 80.0 et active_conns 0, quatre
    # allumages fauches d'affilee entre 15 et 30 s. Le drapeau llama.wanted
    # (meme vocabulaire que docker.wanted, TTL 900 s) suspend la decharge le
    # temps que le cerveau serve a quelque chose ; passe le TTL, le corps
    # reprend la main tout seul -- une intention qui ne perime pas serait un
    # blocage permanent, pas une intention.
    # 2a. INUTILITE -- decharge INDEPENDANTE de la pression RAM.
    #
    # DIRECTIVE OWNER 2026-08-19 : « arreter systematiquement tout ce qui n'est
    # pas utile au corps, puis ne rallumer QUE quand c'est necessaire ».
    # Toute la decharge etait conditionnee a `ram >= FREE_AT` : un coder dont
    # plus personne ne veut restait donc allume tant que la machine n'etouffait
    # pas. MESURE du jour : `llama.wanted` perime depuis ~1000 s, ZERO connexion
    # active, et 4,40 Go toujours tenus sur :8091 -- simplement parce que la RAM
    # plafonnait a 68 %, sous le seuil de 80 %.
    # Reguler sur la seule PRESSION, c'est attendre la detresse pour agir. C'est
    # la correction deja faite pour LM Studio, dont l'arret sur inactivite est
    # explicitement INDEPENDANT de la pression RAM.
    #
    # Un drapeau ABSENT ne declenche RIEN (cf. `_intention_perimee`) : seul un
    # backend que Nokido a lui-meme demande peut etre repris par Nokido.
    _perimee = _intention_perimee("llama.wanted")
    # Duree continue sans servir : c'est ELLE qui demasque une intention menteuse.
    _inutile_s = _maj_inutilite(conns, coder)
    state["zero_conns_depuis"] = _ZERO_CONNS_DEPUIS or None
    state["inutile_s"] = round(_inutile_s)
    # ETAT CONSTATE (2026-09-02, phase de coexistence). Le keeper est bien
    # place pour DIRE ce qu'il voit -- il a le process et les connexions sous
    # les yeux. Il n'a en revanche PAS le droit de poser une demande :
    # `forge_organ_demand.acquerir()` refuse tout appelant de cette couche, et
    # journalise la tentative. C'est la separation que ce chantier installe --
    # jusqu'ici, constater que llama vivait suffisait a le declarer necessaire,
    # d'ou un veto qui ne retombait jamais.
    #
    # AUCUN EFFET sur la decision : ni ce keeper, ni le regulateur ne lisent
    # encore cet etat. On mesure d'abord, on debranche le faux emetteur ensuite.
    try:
        from nokido_agent.app.forge_organ_demand import poser_etat as _poser_etat

        if not coder:
            _etat_vu = "OFF"
        elif conns > 0:
            _etat_vu = "SERVING"
        elif _inutile_s >= _INUTILE_S:
            _etat_vu = "IDLE"
        else:
            _etat_vu = "READY"
        _poser_etat("llama", _etat_vu, emetteur="forge_llama_keeper.tick")
        state["etat_constate"] = _etat_vu
    except Exception:  # noqa: BLE001 - muet-ok : la telemetrie ne casse pas le keeper
        pass
    # Une intention qui reclame sans JAMAIS consommer cesse de proteger. On le DIT
    # dans l'action : outrepasser une intention doit se lire, jamais se deviner.
    _intention_menteuse = (_GOUVERNE_CODER and coder and conns == 0
                           and _perimee is False and _inutile_s >= _INUTILE_S)
    if _intention_menteuse and not MONITOR_ONLY:
        for _rss, pid in coder:
            _kill(pid)
        state["action"] = ("unloaded_intention_non_consommee "
                           "(reclamee mais 0 connexion depuis %ds >= %ds)"
                           % (_inutile_s, _INUTILE_S))
        _LAST_UNLOAD_TS = time.time()
        _ZERO_CONNS_DEPUIS = 0.0
    elif _intention_menteuse:
        state["action"] = ("would_unload_intention_non_consommee (monitor_only, %ds)"
                           % _inutile_s)
    elif _GOUVERNE_CODER and coder and conns == 0 and _perimee is True:
        if MONITOR_ONLY:
            state["action"] = "would_unload_inutile (monitor_only)"
        else:
            for _rss, pid in coder:
                _kill(pid)
            state["action"] = "unloaded_inutile (llama.wanted perime, 0 connexion)"
            _LAST_UNLOAD_TS = time.time()
    elif (_GOUVERNE_CODER and ram >= FREE_AT and coder and conns == 0
            and _intention_voulue("llama.wanted")):
        # Sursis EXPLICITEMENT borne : on affiche le compte a rebours, sinon
        # « differe » se lit comme un etat stable alors que c'est une attente.
        state["action"] = ("unload_differe (intention llama.wanted, inutile %ds/%ds)"
                           % (_inutile_s, _INUTILE_S))
    elif _GOUVERNE_CODER and ram >= FREE_AT and coder and conns == 0:
        if MONITOR_ONLY:
            state["action"] = "would_unload (monitor_only)"
        else:
            for _rss, pid in coder:
                _kill(pid)
            state["action"] = "unloaded"
            _LAST_UNLOAD_TS = time.time()
    # 3. RAM roomy + want local + coder down -> recharge
    elif (ram <= RELOAD_OK and not coder and WANT_LOCAL and not MONITOR_ONLY
            and _GOUVERNE_CODER):
        # ANTI-FLAP (2026-07-17). La bande morte FREE_AT-RELOAD_OK vaut 10 points ; le
        # modele en pese ~21 (5 GB / 23.7 GB) -> recharger le fait RE-franchir FREE_AT
        # aussitot = thrash (chaque tour = un chargement de 15-30s de CPU/disque). Pire,
        # la baseline idle mesuree de la box est 65-77% : 65+21 = 86 > FREE_AT=80, donc
        # le modele ne peut PAS coexister avec la baseline sous ce plafond -- la config
        # est infaisable, pas juste mal reglee. Tant que _llama_pids() etait aveugle,
        # `coder` restait vide et ce chemin ne tirait jamais : le defaut etait MASQUE,
        # pas absent. Le rendre visible l'arme -> il lui faut son garde.
        since = time.time() - _LAST_UNLOAD_TS
        if since < RELOAD_COOLDOWN_S:
            state["note"] = (f"reload differe {int(RELOAD_COOLDOWN_S - since)}s (anti-flap): "
                             f"bande morte {FREE_AT - RELOAD_OK}pts < empreinte modele ~21pts")
        else:
            _start_local()
            state["action"] = "reloaded"

    # Piliers RAG : meme politique (intention x RAM), appliquee aux gros modeles.
    _p = _piliers_on_demand(ram)
    if _p:
        state["piliers"] = _p

    # Drain de vectorisation : pilote par la DETTE mesuree, pas par une intention.
    _d = _drain_on_demand(ram)
    if _d:
        state["drain"] = _d

    # Scheduler Ollama fige : sans cette sonde, chaque chaine qui passe par lui
    # meurt en silence et PERSONNE ne fait le lien (une veille est restee bloquee
    # une matinee entiere le 2026-08-20). Deux confirmations + cooldown : un
    # chargement de modele lent ne doit pas declencher un redemarrage.
    global _OLLAMA_FIGE_N, _OLLAMA_LAST_FIX_TS
    _raison = _ollama_fige()
    if _raison:
        _OLLAMA_FIGE_N += 1
        state["ollama_fige"] = "%s (%d/%d)" % (_raison, _OLLAMA_FIGE_N, _OLLAMA_FIGE_CONFIRM)
        if (_OLLAMA_FIGE_N >= _OLLAMA_FIGE_CONFIRM
                and (time.time() - _OLLAMA_LAST_FIX_TS) >= _OLLAMA_FIX_COOLDOWN_S
                and not MONITOR_ONLY):
            try:
                from nokido_agent.tools.forge_ensure_service import ensure as _ensure

                # `desired_state=restarted` ARRETE SANS RELANCER (mesure 2026-08-20 :
                # rend success:False avec pourtant deux HTTP 200 dans son detail).
                # On enchaine donc stop PUIS running, et on lit le resultat du start.
                _ensure("NokidoOllama", "stopped")
                _r = _ensure("NokidoOllama", "running")
                _ok = bool((_r or {}).get("success")) if isinstance(_r, dict) else bool(_r)
                _OLLAMA_LAST_FIX_TS = time.time()
                _OLLAMA_FIGE_N = 0
                state["action"] = "ollama_degele"
                state["ollama_fige"] = "redemarrage demande ok=%s (%s)" % (_ok, _raison)
                print("[llama-keeper] ollama FIGE -> redemarrage ok=%s :: %s"
                      % (_ok, _raison), flush=True)
            except Exception as e:  # noqa: BLE001
                # Pas muet : un degel qu'on croit fait et qui ne l'est pas est
                # exactement la mort silencieuse que cette sonde corrige.
                state["ollama_fige"] = "redemarrage IMPOSSIBLE (%r) : %s" % (e, _raison)
                print("[llama-keeper] ollama fige, degel IMPOSSIBLE: %r" % (e,), flush=True)
    else:
        _OLLAMA_FIGE_N = 0

    return state


_HB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox", "llama_keeper.heartbeat")


def _code_identity() -> dict:
    """Identité du code RÉELLEMENT CHARGÉ (cf tools/forge_code_identity.py) — un keeper
    qui exécute un fichier périmé doit se voir dans son propre battement (mesuré 02/08)."""
    try:
        from nokido_agent.tools.forge_code_identity import fields
        return fields(__file__)
    except Exception:  # muet-ok : diagnostic, jamais un SPOF pour le keeper
        return {}


def _heartbeat(state: dict) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`
    # qui manquait, sans quoi le porteur du pouls reste inattribuable.
    # La charge se construit par `update` et NON par deux depaquetages `**` dans
    # l'appel : un litteral de dict tolere une clef en double (la derniere gagne),
    # un appel de fonction leve `TypeError`.
    # `app/` n'est PAS sur le sys.path de ce module (verifie) : sans cette amorce,
    # l'import echouerait, le pouls disparaitrait, et le superviseur redemarrerait un
    # keeper qui recharge plusieurs Go de modele. Meme idiome que les autres tools.
    import sys as _sys
    from pathlib import Path as _Path

    _app = str(_Path(__file__).resolve().parent.parent / "app")
    if _app not in _sys.path:
        _sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    charge = {"health": "idle"}
    charge.update(_code_identity())
    charge.update(state)
    beat_daemon("llama_keeper", **charge)


def main() -> int:
    print(f"[llama-keeper] start free_at={FREE_AT}% reload_ok={RELOAD_OK}% "
          f"interval={INTERVAL}s want_local={WANT_LOCAL} monitor_only={MONITOR_ONLY}", flush=True)
    while True:
        try:
            s = tick()
            _heartbeat(s)
            if s["action"] != "none":
                print(f"[llama-keeper] {s}", flush=True)
        except Exception as e:
            print(f"[llama-keeper] tick err: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    import sys

    if "--once" in sys.argv:
        print(tick())
    else:
        raise SystemExit(main())
