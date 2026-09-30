"""
tools/forge_orphan_reaper.py — Moissonneur d'orphelins llama (2026-07-25).

Pourquoi un module de plus (anti-dup, justification exigee) :
- forge_port_reconcile tue les fantomes QUI ECOUTENT un port revendique ; un
  orphelin SANS port (5.59 GB mesure ce jour, pid hors registre) lui est invisible.
- forge_llama_keeper ne gouverne que les CODER (_is_coder) et protege embed/reranker.
- _heavy_evictable_services (resource_manager) s'abstient sur tout process NON
  rattache a un service — par design (cout asymetrique).
Le trou couvert ICI : llama-server lourd, sans ecoute, hors registre superviseur,
hors marqueurs proteges. Dry-run par defaut ; kill UNIQUEMENT via --kill
(trusted_script = code revu, compte privilegie).

Doctrine appliquee (RULES_SHARED « avant d'agir ») :
- la legitimite se DEMANDE au superviseur (registre + descendance), jamais
  deduite du RSS ;
- chaque abstention est IMPRIMEE avec sa raison (« rien trouve » != « pas pu voir »).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

REAP_FAMILY = {"llama-server.exe", "llama-server"}
MIN_RSS_GB = 1.0
MIN_AGE_S = 600.0
MAX_REAP_PER_RUN = 2  # garde anti-hecatombe : au-dela, un humain regarde d'abord
PROTECT_MARKERS = ("bge-m3", "bge-reranker", "--embedding", "--reranking")


def _ollama_loaded_count():
    """Nombre de modeles qu'Ollama declare charges. None = PAS PU VOIR.

    Distinguer None de 0 est vital : confondre « API injoignable » et « rien
    charge » ferait moissonner un runner LEGITIME des que l'API bronche.
    """
    import json as _json
    import urllib.request as _ur

    try:
        with _ur.urlopen("http://127.0.0.1:11434/api/ps", timeout=3.0) as r:
            if not (200 <= int(getattr(r, "status", 0) or 0) < 300):
                return None
            data = _json.loads(r.read().decode("utf-8", "replace"))
            return len(data.get("models") or [])
    except Exception:  # noqa: BLE001
        return None


def _is_leaked_ollama_runner(proc) -> bool:
    """Enfant de ollama.exe alors qu'Ollama ne declare AUCUN modele charge.

    Trou mesure le 26-07 : un runner de 5.59 Go a survecu a un unload. Il
    etait descendant du superviseur (donc « legitime » pour la regle
    ci-dessous), absent de /api/ps (donc invisible de l'eviction, qui
    rendait noop), et sans port revendique (donc hors port_reconcile) : il
    echappait aux TROIS regulateurs pendant que le gate P1 bloquait toute la
    machine a 89 %.

    Etre DANS l'arbre du corps ne suffit pas : encore faut-il que le parent
    reconnaisse l'enfant. On ne tranche QUE sur le cas net (zero modele
    declare) ; des qu'Ollama en declare au moins un, on ne sait pas lequel
    porte quel pid -> doute, donc abstention.
    """
    try:
        parent = proc.parent()
        if parent is None:
            return False
        if (parent.name() or "").lower() not in ("ollama.exe", "ollama"):
            return False
    except Exception:  # noqa: BLE001
        return False
    return _ollama_loaded_count() == 0


def survey() -> dict:
    import psutil

    from nokido_agent.app.forge_port_reconcile import _is_descendant, _supervisor_ports

    claimed = _supervisor_ports()
    if not claimed:
        return {"ok": False, "reason": "superviseur muet (:8765) -> on ne devine pas",
                "candidates": []}
    claimed_pids = sorted({int(p) for _port, (_svc, p) in claimed.items()})

    # pid -> ports en LISTEN. Un listener sur un port REVENDIQUE = domaine
    # port_reconcile (on s'abstient). Un listener sur un port NON revendique =
    # l'enfant-perdu type (service on-demand retombe du registre, process vivant) :
    # invisible de port_reconcile (qui n'itere que les ports revendiques) -> ICI.
    listen_ports: dict = {}
    try:
        for c in psutil.net_connections("tcp"):
            if c.status == "LISTEN" and c.pid and c.laddr:
                listen_ports.setdefault(int(c.pid), set()).add(int(c.laddr.port))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"net_connections illisible: {e}", "candidates": []}
    claimed_ports = {int(p) for p in claimed}

    now = time.time()
    candidates, spared = [], []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "create_time"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in REAP_FAMILY:
                continue
            pid = int(proc.info["pid"])
            rss = float(proc.info["memory_info"].rss) / (1024 ** 3)
            age_s = now - float(proc.info.get("create_time") or now)
            # L'age est porte par CHAQUE entree, epargnee comprise : une abstention
            # sans sa mesure n'est pas verifiable. Mesure 26-07 : le moissonneur
            # epargnait un process de 5.59 GB en disant « trop jeune » SANS donner
            # l'age, et je n'ai pas pu trancher si le garde etait juste ou si
            # l'horodatage mentait -- un garde indiscutable est un garde qu'on finit
            # par contourner.
            entry = {"pid": pid, "rss_gb": round(rss, 2), "age_s": round(age_s)}
            if rss < MIN_RSS_GB:
                spared.append({**entry, "why": f"petit ({rss:.2f} GB < {MIN_RSS_GB} GB)"})
                continue
            if age_s < MIN_AGE_S:
                spared.append({**entry,
                               "why": f"trop jeune ({age_s:.0f}s < {MIN_AGE_S:.0f}s, "
                                      "boot en cours ?)"})
                continue
            ports = sorted(listen_ports.get(pid, set()))
            if ports:
                entry["listen_ports"] = ports
            if any(p in claimed_ports for p in ports):
                spared.append({**entry, "why": "ecoute un port REVENDIQUE -> domaine port_reconcile"})
                continue
            if pid in claimed_pids or any(_is_descendant(pid, cp) for cp in claimed_pids):
                if _is_leaked_ollama_runner(proc):
                    entry["why"] = ("enfant de ollama.exe alors que /api/ps ne declare "
                                    "AUCUN modele -> runner fuite, invisible de l'eviction")
                    candidates.append(entry)
                    continue
                spared.append({**entry, "why": "revendique/descendant superviseur"})
                continue
            try:
                cmd = " ".join(proc.cmdline()).lower()
                if any(m in cmd for m in PROTECT_MARKERS):
                    spared.append({**entry, "why": "marqueur protege (embed/reranker)"})
                    continue
                entry["cmdline"] = cmd[:200]
            except Exception:  # noqa: BLE001
                entry["cmdline"] = "(illisible — pas disqualifiant : orphelin d'un autre compte)"
            candidates.append(entry)
        except Exception:  # noqa: BLE001
            continue
    return {"ok": True, "claimed_pids": claimed_pids,
            "candidates": candidates, "spared": spared}


def _audit(action: str, reason: str = "", **extra) -> None:
    """Signature obligatoire de toute moisson. Best-effort, ne leve JAMAIS.

    Trou MESURE le 2026-07-26 : `sandbox/lifecycle_actions.jsonl` ne portait
    AUCUNE entree reaper/orphan — jamais, depuis l'origine. Ce faucheur tuait
    donc sans laisser d'auteur, exactement ce que forge_lifecycle_audit existe
    pour interdire (« le silence est une preuve »).

    Cout concret de ce trou : un redemarrage du hub 22 s apres un `--kill` du
    2026-07-26 11:22:41 est reste INATTRIBUABLE — ni imputable au faucheur, ni
    innocentable. Un garde-fou qui agit sans signer rend son propre proces
    impossible.
    """
    try:
        import sys as _s

        _app = str(ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_lifecycle_audit import record as _record

        _record(action, domain="ram", reason=reason, **extra)
    except Exception:  # noqa: BLE001 - le journal ne doit jamais casser le faucheur
        pass


# Refractaire du faucheur. Le budget de gravite `critical` vaut 2 tirs/h
# (forge_regulation_loops.SEVERITY_BUDGET_PER_HOUR) : l'ABSOLUE vaut donc 1800 s,
# et elle est INFRANCHISSABLE, urgence maximale comprise. Une urgence forte peut
# raccourcir la RELATIVE, jamais l'absolue -- sans quoi la tetanie.
_REAP_ABSOLUE_S = float(os.environ.get("LAFORGE_REAP_REFRACTAIRE_S", "1800"))
# PERSISTE : un cooldown garde en memoire disparait au respawn du regulateur, et
# c'est PRECISEMENT pendant une crise qu'il respawne (lecon deja ecrite dans
# forge_homeostasis_orchestrator).
_REAP_ETAT = ROOT / "sandbox" / "orphan_reaper_state.json"
# Consignes RAM : sous la borne basse, aucune urgence ; au-dela de la haute,
# urgence maximale -- les bornes que le corps utilise deja pour reveil/sommeil.
_RAM_BAS = float(os.environ.get("LAFORGE_REAP_RAM_BAS", "80"))
_RAM_HAUT = float(os.environ.get("LAFORGE_REAP_RAM_HAUT", "92"))


def _dernier_tir() -> float:
    try:
        return float(json.loads(_REAP_ETAT.read_text(encoding="utf-8")).get("ts", 0.0))
    except (OSError, ValueError, AttributeError):
        return 0.0


def _noter_tir() -> None:
    try:
        _REAP_ETAT.parent.mkdir(exist_ok=True)
        _REAP_ETAT.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        print("[reaper] refractaire NON persistee (%s) : elle ne bornera pas un "
              "respawn" % type(e).__name__, file=sys.stderr)


def _urgence_ram(ram_pct: float) -> float:
    """0 sous la consigne basse, 1 au-dela de la haute. Lineaire entre les deux."""
    if _RAM_HAUT <= _RAM_BAS:
        return 0.0
    return max(0.0, min(1.0, (ram_pct - _RAM_BAS) / (_RAM_HAUT - _RAM_BAS)))


def run_cycle(kill: bool = False) -> dict:
    """Survey + moisson optionnelle in-process (parite forge_port_reconcile.run_cycle).

    Appele a chaque cycle par forge_homeostasis_orchestrator : ce moissonneur
    EXISTAIT (2026-07-25) mais aucune cadence ne l'appelait -- organe sans emetteur
    (dette ouverte). Retourne survey + pid moissonnes + effet RAM mesure.

    REFRACTAIRE (2026-08-29). On lui avait donne une cadence sans lui donner de
    FREIN : il moissonnait des qu'il avait des candidats, a chaque tick. Mesure
    `forge_regulation_efficacy` : `kill/ram` a **POMPE** -- 3,7 tirs/h pour un
    budget de 2,0, trois recidives. Le budget existait pourtant : il n'avait AUCUN
    consommateur cote effecteur, il ne servait qu'a constater apres coup.
    Le verdict vient donc de l'organe deja ecrit (`refractaire_verdict`), celui-la
    meme que `run_reclaimers` consulte : on ne redefinit aucune regle ici, on
    branche le nerf qui manquait.
    """
    res = survey()
    res.setdefault("reaped", [])
    if not res.get("ok") or not kill or not res.get("candidates"):
        return res
    import psutil

    _ram_before = psutil.virtual_memory().percent
    _ecoule = time.time() - _dernier_tir()
    _urgence = _urgence_ram(_ram_before)
    try:
        _t = str(ROOT / "tools")
        if _t not in sys.path:
            sys.path.insert(0, _t)
        from nokido_agent.tools.forge_regulation_efficacy import journal as _journal
        from nokido_agent.tools.forge_regulation_efficacy import refractaire_verdict as _verdict
        _v = _verdict("kill", "ram", _ecoule, _REAP_ABSOLUE_S,
                      urgence=_urgence, evenements=_journal())
    except Exception as e:  # noqa: BLE001
        # Capteur meta absent : repli PLAT sur l'absolue. Il se DIT, sinon on croit
        # adaptatif un palier qui ne l'est plus.
        _v = {"fire": _ecoule >= _REAP_ABSOLUE_S,
              "reason": "capteur meta absent (%s) : repli plat" % type(e).__name__}
    if not _v.get("fire"):
        res["refractaire"] = {
            "ecoule_s": int(_ecoule), "absolue_s": int(_REAP_ABSOLUE_S),
            "relative_s": _v.get("relative_s"), "recidive": _v.get("recidive"),
            "ram_pct": round(_ram_before, 1), "urgence": round(_urgence, 3),
            "raison": _v.get("reason", ""),
        }
        # Une abstention n'est PAS un acte : elle se journalise comme telle, sinon
        # on la compte comme un tir et le corps parait pomper alors qu'il se retient.
        _audit("kill_skipped", "refractaire : %ds ecoules, urgence %.2f"
               % (int(_ecoule), _urgence), ram_pct=round(_ram_before, 1))
        return res

    cands = res["candidates"][:MAX_REAP_PER_RUN]
    _noter_tir()
    _audit("kill", "moisson cycle : %d cible(s)" % len(cands),
           ram_pct_before=round(_ram_before, 1))
    for c in cands:
        try:
            p = psutil.Process(c["pid"])
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
            res["reaped"].append(c["pid"])
            _audit("kill", c.get("why") or "orphelin moissonne",
                   target="pid=%s" % c["pid"], rss_gb=c.get("rss_gb"))
        except Exception as e:  # noqa: BLE001
            _audit("kill_failed", ("%s: %s" % (type(e).__name__, e))[:180],
                   target="pid=%s" % c["pid"])
    time.sleep(2)
    _ram_after = psutil.virtual_memory().percent
    res["ram_before"] = round(_ram_before, 1)
    res["ram_after"] = round(_ram_after, 1)
    res["delta_pt"] = round(_ram_before - _ram_after, 1)
    _audit("kill", "effet mesure : %+.1f pt" % res["delta_pt"],
           delta_pt=res["delta_pt"], cibles=len(cands))
    return res


def main() -> int:
    kill = "--kill" in sys.argv
    res = survey()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if not res.get("ok"):
        return 2
    if not kill:
        return 0
    cands = res["candidates"][:MAX_REAP_PER_RUN]
    if len(res["candidates"]) > MAX_REAP_PER_RUN:
        print(f"CAP: {len(res['candidates'])} candidats > {MAX_REAP_PER_RUN} "
              "-> seuls les premiers sont moissonnes, verifier le reste a la main")
    import psutil
    # Une moisson s'annonce AVANT d'agir : si la machine meurt au milieu, l'intention
    # reste lisible. Un journal ecrit seulement apres coup ne survit pas a l'accident
    # qu'il devrait justement documenter.
    # BOUCLE FERMÉE. Une régulation se juge sur l'EFFET obtenu, pas sur la commande
    # émise : le baroréflexe mesure la pression qui en résulte, il ne se contente pas
    # de constater qu'il a envoyé le signal. Ce faucheur tuait et ne vérifiait rien —
    # audit 2026-07-26. On relève donc la RAM avant, puis après.
    _ram_before = psutil.virtual_memory().percent
    _audit("kill", f"moisson --kill : {len(cands)} cible(s) retenue(s)",
           targets=",".join(f"{c['pid']}:{c.get('name')}" for c in cands),
           total_candidats=len(res["candidates"]), epargnes=len(res.get("spared") or []),
           ram_pct_before=round(_ram_before, 1))
    for c in cands:
        try:
            p = psutil.Process(c["pid"])
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
            print(f"REAPED pid={c['pid']} rss={c['rss_gb']}GB")
            _audit("kill", c.get("why") or "orphelin moissonne",
                   target=f"{c.get('name')}(pid={c['pid']})", rss_gb=c.get("rss_gb"))
        except Exception as e:  # noqa: BLE001
            print(f"ECHEC pid={c['pid']}: {e}")
            # L'echec se consigne AUSSI : « j'ai voulu tuer et je n'ai pas pu » est une
            # information de regulation, pas un non-evenement (cf. les 4 formes de kill
            # refusees a tous les comptes clients, RULES_SHARED).
            _audit("kill_failed", f"{type(e).__name__}: {e}"[:180],
                   target=f"{c.get('name')}(pid={c['pid']})", rss_gb=c.get("rss_gb"))
    # L'effet, mesuré. Un delta nul après une moisson annoncée est une information de
    # premier ordre : soit les cibles n'étaient pas les gloutonnes, soit les kills ont
    # échoué. Sans cette mesure, les deux cas se lisaient « moisson effectuée ».
    time.sleep(2)  # laisser l'OS reprendre les pages des process terminés
    _ram_after = psutil.virtual_memory().percent
    _delta = round(_ram_before - _ram_after, 1)
    print(f"EFFET MESURE: RAM {_ram_before:.1f}% -> {_ram_after:.1f}% (libere {_delta:+.1f} pt)")
    _audit("kill", f"effet mesure de la moisson : {_delta:+.1f} pt de RAM",
           ram_pct_before=round(_ram_before, 1), ram_pct_after=round(_ram_after, 1),
           delta_pt=_delta, cibles=len(cands), sans_effet=bool(abs(_delta) < 0.5))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
