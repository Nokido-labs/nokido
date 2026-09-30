# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "observabilite/sse-fuite"
PATCH tools/nokido_hub.py (CRITICAL_FILE) : fuite des abonnes SSE, angle mort
total du journal, et ring de repli fail-OPEN.

POURQUOI UN SCRIPT
==================
`tools/nokido_hub.py` est CRITICAL_FILE : `governed_edit` le refuse, et
`LAFORGE_ALLOW_CRITICAL_WRITE` vit dans l'environnement du hub, qui ne se
recharge pas a chaud. La voie prevue est un script git-tracke lance en
`trusted_script` -- doctrine << privilege = code revu >>. Meme patron que
`tools/forge_patch_muted_paths.py`.

CE QU'IL CORRIGE (constate par lecture le 2026-08-14)
=====================================================
1. `network_stream` : `except:` NU dans le generateur. Il attrape `GeneratorExit`,
   donc la deconnexion d'un client est avalee, la boucle continue, et la queue
   reste abonnee : chaque onglet ferme laisse un fantome que `_sse_broadcast`
   continue de remplir. -> `except Exception:` + `finally` qui desabonne.
2. `watch_stream_api` : MEME fuite, cause differente. Son `except Exception`
   laisse bien passer `GeneratorExit`, mais rien ne retire la queue de
   `_WATCH_SSE_CLIENTS`. -> `finally` qui desabonne.
3. Premier evenement de `watch_stream_api` : JSON malforme
   (`data: "{"type":"connected"}""`) -> le `JSON.parse` du client echoue d'entree.
4. Le SSE etait l'angle mort TOTAL du journal : 0 ligne sur 228 955 le
   2026-08-12. On trace l'OUVERTURE et la FERMETURE, JAMAIS la diffusion :
   `_log_network` appelle `_sse_broadcast`, journaliser chaque diffusion
   bouclerait a l'infini.
5. Repli d'authentification (videur indisponible) : un agent hors du registre
   porteur du master token obtenait `ring 0` en local -- fail-OPEN, a l'inverse
   du videur qui est fail-closed (identite inconnue -> UNTRUSTED). -> defaut 3.

GARANTIES
=========
Sentinelle d'idempotence, chaque ancre doit apparaitre EXACTEMENT une fois sinon
abandon, fins de ligne CRLF preservees, `compile()` avant ecriture, sauvegarde
horodatee, relecture verifiee, dry-run par defaut. L'effet demande un
REDEMARRAGE du hub (le module est deja charge en memoire).

    LAFORGE_PYTHON tools/forge_patch_sse_leak.py            # dry-run
    LAFORGE_PYTHON tools/forge_patch_sse_leak.py --apply
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "tools" / "nokido_hub.py"

# Sentinelle : presente => deja applique.
SENTINELLE = "_sse_trace"

BLOCS = [
    # 1. _sse_broadcast : except nus + naissance de la trace d'abonnement
    (r'''def _sse_broadcast(event: dict):
    data = f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    dead = []
    with _SSE_LOCK:
        for q in _SSE_CLIENTS:
            try:
                q.put_nowait(data)
            except:
                dead.append(q)
        for q in dead:
            try:
                _SSE_CLIENTS.remove(q)
            except:
                pass''',
     r'''def _sse_broadcast(event: dict):
    data = f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    dead = []
    with _SSE_LOCK:
        for q in _SSE_CLIENTS:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                _SSE_CLIENTS.remove(q)
            except ValueError:
                pass


def _sse_trace(phase: str, abonnes: int, flux: str = "network") -> None:
    """Journalise l'ABONNEMENT SSE (ouverture/fermeture), JAMAIS la diffusion.

    Le SSE etait l'angle mort TOTAL du journal : 0 ligne sur 228 955 evenements
    au 2026-08-12, alors que `_sse_broadcast` pousse a chaque evenement.
    Journaliser la DIFFUSION bouclerait : `_log_network` appelle
    `_sse_broadcast`. On ne trace donc que les deux bords -- la ou vit la fuite.
    """
    try:
        from forge_network_logger import Direction, NetworkChannel, net_log

        net_log(NetworkChannel.INTERNAL_HUB, Direction.OUT, tool=f"sse.{phase}",
                agent="SSE", status="ok",
                payload_out=f"flux={flux} abonnes={abonnes}")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.hub").warning(
            "[sse] abonnement %s NON journalise (%s: %s) | consequence: le flux "
            "SSE redevient un angle mort et une fuite d'abonnes repasse inapercue",
            phase, type(e).__name__, str(e)[:80])'''),

    # 2. network_stream : GeneratorExit avale + queue jamais desabonnee
    (r'''    async def network_stream(request: Request):
        q: queue.Queue = queue.Queue(maxsize=500)
        with _SSE_LOCK:
            _SSE_CLIENTS.append(q)

        async def generator():
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: q.get(timeout=25)
                    )
                    yield data
                except:
                    yield ": ping\n\n"''',
     r'''    async def network_stream(request: Request):
        q: queue.Queue = queue.Queue(maxsize=500)
        with _SSE_LOCK:
            _SSE_CLIENTS.append(q)
            _abonnes = len(_SSE_CLIENTS)
        _sse_trace("open", _abonnes)

        async def generator():
            yield 'data: {"type":"connected"}\n\n'
            try:
                while True:
                    # `except Exception` et PAS `except:` : un except nu attrape
                    # GeneratorExit, donc la deconnexion du client serait avalee,
                    # la boucle continuerait, et la queue resterait abonnee.
                    try:
                        data = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: q.get(timeout=25)
                        )
                        yield data
                    except Exception:
                        yield ": ping\n\n"
            finally:
                # Desabonnement INCONDITIONNEL : sans lui, chaque onglet ferme
                # laisse un fantome que `_sse_broadcast` continue de remplir.
                with _SSE_LOCK:
                    try:
                        _SSE_CLIENTS.remove(q)
                    except ValueError:
                        pass
                    _restants = len(_SSE_CLIENTS)
                _sse_trace("close", _restants)'''),

    # 3. watch_stream_api : meme fuite + premier evenement JSON malforme
    (r'''    q: _wqueue.Queue = _wqueue.Queue(maxsize=200)
    with _WATCH_SSE_LOCK:
        _WATCH_SSE_CLIENTS.append(q)

    async def gen():
        yield 'data: "{"type":"connected"}""\n\n'
        while True:
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=20)
                )
                yield data
            except Exception:
                yield ": ping\n\n"''',
     r'''    q: _wqueue.Queue = _wqueue.Queue(maxsize=200)
    with _WATCH_SSE_LOCK:
        _WATCH_SSE_CLIENTS.append(q)
        _abonnes = len(_WATCH_SSE_CLIENTS)
    _sse_trace("open", _abonnes, flux="watch")

    async def gen():
        # JSON valide : la version precedente emettait `"{"type":"connected"}""`,
        # le JSON.parse du client echouait des le premier evenement.
        yield 'data: {"type":"connected"}\n\n'
        try:
            while True:
                try:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: q.get(timeout=20)
                    )
                    yield data
                except Exception:
                    yield ": ping\n\n"
        finally:
            with _WATCH_SSE_LOCK:
                try:
                    _WATCH_SSE_CLIENTS.remove(q)
                except ValueError:
                    pass
                _restants = len(_WATCH_SSE_CLIENTS)
            _sse_trace("close", _restants, flux="watch")'''),

    # 4. repli d'authentification : defaut ring 0 en local = fail-OPEN
    (r'''    expected = _AGENT_TOKENS.get(agent_hdr)
    if expected and hmac.compare_digest(token.encode(), expected.encode()):
        return _agent_ring(agent_hdr, 0 if local else 3), agent_hdr
    if hmac.compare_digest(token.encode(), HUB_TOKEN.encode()):
        agent_id = agent_hdr if agent_hdr and agent_hdr != "UNKNOWN" else "MASTER_TOKEN"
        return _agent_ring(agent_id, 0 if local else 3), agent_id''',
     r'''    # FAIL-CLOSED : une identite hors registre retombe sur 3 (isolee), JAMAIS 0.
    # Le chemin nominal (forge_videur) defaut a UNTRUSTED ; ce repli defaultait a
    # SYSTEM des lors que l'appel venait de la machine locale.
    expected = _AGENT_TOKENS.get(agent_hdr)
    if expected and hmac.compare_digest(token.encode(), expected.encode()):
        return _agent_ring(agent_hdr, 3), agent_hdr
    if hmac.compare_digest(token.encode(), HUB_TOKEN.encode()):
        agent_id = agent_hdr if agent_hdr and agent_hdr != "UNKNOWN" else "MASTER_TOKEN"
        return _agent_ring(agent_id, 3), agent_id'''),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut : dry-run)")
    args = ap.parse_args()

    brut = CIBLE.read_bytes()
    txt = brut.decode("utf-8")
    crlf = "\r\n" in txt
    if crlf:
        txt = txt.replace("\r\n", "\n")

    if SENTINELLE in txt:
        print(f"[deja applique] sentinelle '{SENTINELLE}' presente -- rien a faire")
        return 0

    out = txt
    for i, (ancre, remplacement) in enumerate(BLOCS, 1):
        n = out.count(ancre)
        if n != 1:
            print(f"[ABANDON] bloc {i}: ancre trouvee {n} fois (attendu 1). "
                  f"Le fichier a change -- aucune ecriture.")
            return 2
        out = out.replace(ancre, remplacement, 1)
        print(f"  [ok] bloc {i}/{len(BLOCS)} applique")

    try:
        compile(out, str(CIBLE), "exec")
    except SyntaxError as e:
        print(f"[ABANDON] le resultat ne compile pas : {e}")
        return 3
    print("  [ok] compile() du resultat")

    if not args.apply:
        print(f"\n[dry-run] {len(BLOCS)} blocs prets, "
              f"{len(out) - len(txt):+d} caracteres. Relancer avec --apply.")
        return 0

    horodatage = time.strftime("%Y%m%d_%H%M%S")
    sauvegarde = CIBLE.with_suffix(f".py.bak.{horodatage}")
    sauvegarde.write_bytes(brut)
    print(f"  [ok] sauvegarde : {sauvegarde.name}")

    final = out.replace("\n", "\r\n") if crlf else out
    CIBLE.write_bytes(final.encode("utf-8"))

    relu = CIBLE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    if SENTINELLE not in relu:
        print("[ECHEC] relecture : la sentinelle est absente APRES ecriture")
        return 4
    print(f"  [ok] relu : {CIBLE.stat().st_size} octets, sentinelle presente")
    print("\n[applique] Le hub doit etre REDEMARRE pour recharger le module.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
