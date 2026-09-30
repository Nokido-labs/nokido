# -*- coding: utf-8 -*-
"""Demonstration VERIFIEE des 4 piliers d'autonomie Nokido.

v2 (durcie — corrige la livraison AGY). Ce qui change vs v1 :
  - VERDICT REEL : chaque pilier renvoie True/False ; main agrege et sort en
    sys.exit(1) si un pilier echoue. Le banner « prouve » n'apparait QUE si 4/4
    (v1 imprimait « 100% PROUVEE » meme si les 4 piliers levaient).
  - ASSERTS SORTIS DU CATCH-ALL : v1 avalait les assert dans un except large =
    un assert faux devenait un log, pas un echec. Ici = branche explicite ok=False.
  - ZERO RESIDU MUTANT sur le systeme vivant :
      * pilier 2 restaure le rythme endocrine PRECEDENT dans un finally
        (v1 : revert vers NORMAL en dur, saute si exception avant la derniere
        ligne = essaim laisse en CONSERVE 30 min) ;
      * pilier 4 SUPPRIME le candidat de demo de l'arene dans un finally
        (v1 : accumulait un candidat par run et en promouvait un en Ring 1 sans
        nettoyage = residu de privilege persistant).
A lancer hors periode de drain lourd (le pilier 2 touche brievement le rythme).
"""

__FORGE_COLOR__ = "qualite/preuve : demonstration verifiee des 4 piliers d'autonomie, verdict reel par pilier"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _sub in ("tools", "app"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def print_header(title):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def print_info(label, value):
    print(f"  - {label} : {value}")


def print_success(msg):
    print(f"  [OK] {msg}")


def print_fail(msg):
    print(f"  [!!] {msg}")


def prove_metabolism_sensors():
    print_header("PILIER 1 : CAPTEURS DE METABOLISME (TOKEN METER & RYTHME)")
    ok = True

    # 1A. Token Meter (lecture seule).
    try:
        from nokido_agent.tools import forge_token_meter as ftm
        stats = ftm.aggregate_by_agent(since_hours=720)
        total_tok = sum(s.get("total_tokens", 0) for s in stats.values())
        total_usd = sum(s.get("cost_usd", 0.0) for s in stats.values())
        print_info("Sonde SQLite Token Meter", f"Actif ({len(stats)} agents/identites tracked)")
        print_info("Consommation cumulee", f"{total_tok:,} tokens (${total_usd:.4f} USD)")
        print_success("Suivi metabolique 100% local, deterministe, cout zero (SQLite WAL).")
    except Exception as e:
        print_fail(f"Token Meter: {e}")
        ok = False

    # 1B. Lecture Rythme Endocrine (lecture seule).
    try:
        from nokido_agent.app import forge_endocrine_system as fes
        status = fes.get_rhythm_status()
        print_info("Rythme metabolique actuel", f"{status.rhythm} (multiplicateur delai: {status.delay_multiplier}x)")
        print_success("L'hypothalamus de l'essaim lit et publie le rythme en temps reel.")
    except Exception as e:
        print_fail(f"Rythme Endocrine: {e}")
        ok = False

    return ok


def prove_anti_contention_shield():
    print_header("PILIER 2 : BOUCLIER ANTI-CONTENTION (BUS ENDOCRINE)")
    ok = True
    fes = None
    prior = None
    try:
        from nokido_agent.app import forge_endocrine_system as fes
        # Capture de l'etat AVANT toute mutation (restauration fidele en finally).
        prior = fes.get_rhythm_status()

        print("  >> Simulation : activite interactive detectee sur le CLI Antigravity...")
        fes.set_rhythm("CONSERVE", ttl_s=1800, reason="preuve pilier anti-contention", source="prove_script")

        status = fes.get_rhythm_status()
        print_info("Nouvel etat impose", f"{status.rhythm} (TTL restant: {status.remaining_ttl_s}s)")
        print_info("Multiplicateur de sommeil", f"{status.delay_multiplier}x")

        watch_paused = fes.should_pause_worker("forge_watch_agent", "background")
        rss_paused = fes.should_pause_worker("rss_watcher", "background")
        vital_paused = fes.should_pause_worker("forge_token_watchdog", "vital")

        print_info("Statut 'forge_watch_agent'", "EN PAUSE" if watch_paused else "ACTIF")
        print_info("Statut 'rss_watcher'", "EN PAUSE" if rss_paused else "ACTIF")
        print_info("Statut 'forge_token_watchdog'", "ACTIF (vital immunise)" if not vital_paused else "EN PAUSE")

        if watch_paused and rss_paused and not vital_paused:
            print_success("Bouclier OK : veilles de fond gelees, watchdog vital immunise.")
        else:
            print_fail(f"Comportement inattendu (watch={watch_paused} rss={rss_paused} vital={vital_paused})")
            ok = False
    except Exception as e:
        print_fail(f"Bouclier Anti-Contention: {e}")
        ok = False
    finally:
        # Restauration de l'etat PRECEDENT quoi qu'il arrive (jamais NORMAL en dur).
        if fes is not None and prior is not None:
            try:
                fes.set_rhythm(
                    prior.rhythm,
                    ttl_s=max(60, int(prior.remaining_ttl_s)),
                    reason="restore post-preuve",
                    source="prove_script",
                )
                print_info("Rythme restaure", prior.rhythm)
            except Exception as e:
                print_fail(f"ECHEC restauration rythme -> {e} (verifier l'endocrine !)")
                ok = False
    return ok


def prove_anti_spoofing_locks():
    print_header("PILIER 3 : VERROUS ANTI-SPOOFING & RBAC STRICT")
    ok = True
    try:
        from nokido_agent.app import forge_videur as v

        # 3A. Usurpation d'identite CLAUDE sans token cryptographique.
        print("  >> Attaque : script anonyme envoie 'X-Agent-Name: CLAUDE' sans token...")
        ident = v.resolve_identity("CLAUDE", token="")
        print_info("Resolution par le Videur", f"agent={ident['agent']} -> Ring {ident['ring']} (via {ident['via']})")
        if ident["ring"] == 4:
            print_success("Anti-spoofing : attaquant degrade au Ring 4 (UNTRUSTED / lecture seule).")
        else:
            print_fail(f"Ring attendu 4, obtenu {ident['ring']} — anti-spoofing defaillant !")
            ok = False

        # 3B. Ce faux Ring 4 tente d'appeler l'outil d'execution 'run'.
        print("  >> Attaque : ce faux Ring 4 tente d'appeler l'outil d'execution 'run'...")
        auth = v.authorize("CLAUDE", token="", tool="run")
        print_info("Decision d'autorisation", f"allow={auth['allow']} ({auth['reason']})")
        if auth["allow"] is False:
            print_success("RBAC Enforce : execution de code arbitraire bloquee.")
        else:
            print_fail("RBAC aurait du bloquer l'appel 'run' depuis le Ring 4 !")
            ok = False
    except Exception as e:
        print_fail(f"Verrous Anti-Spoofing: {e}")
        ok = False
    return ok


def prove_darwinian_quarantine():
    print_header("PILIER 4 : QUARANTAINE DARWINIENNE (RING 4 & EVOLUTION)")
    ok = True
    fda = None
    cid = None
    try:
        from nokido_agent.app import forge_darwinian_arena as fda

        # 4A. Automutation malveillante (injection OS) -> rejet AST immediat.
        print("  >> Test 1 : soumission d'un code avec 'import os' (injection systeme)...")
        try:
            fda.submit_candidate("mut_evil_injection", "import os\ndef solve(): return os.system('whoami')")
            print_fail("Le scanner AST aurait du rejeter le code malveillant !")
            ok = False
        except fda.SecurityError as sec_e:
            print_info("Resultat Scanner AST", f"REJET IMMEDIAT ({sec_e})")
            print_success("Quarantaine : empoisonnement bloque avant insertion en base.")

        # 4B. Candidat sain autogenere -> quarantaine Ring 4.
        print("  >> Test 2 : soumission d'un algorithme sain (tri decroissant)...")
        cand = fda.submit_candidate(
            "prove_demo_sort",
            "def solve(data): return sorted(data, reverse=True)",
            author="prove_script",
        )
        cid = cand["candidate_id"]
        print_info("ID du Candidat", cid)
        print_info("Statut & Ring initial", f"status='{cand['status']}' | Ring={cand['ring']}")
        if cand["ring"] == 4 and cand["status"] == "quarantine":
            print_success("Candidat en quarantaine stricte Ring 4 (Ring 0/1 non pollue).")
        else:
            print_fail(f"Attendu Ring 4 / quarantine, obtenu Ring {cand['ring']} / {cand['status']}")
            ok = False

        # 4C. Epreuves synthetiques en bac a sable Ring 4.
        print("  >> Test 3 : 3 epreuves synthetiques dans le harnais isole...")
        fda.run_synthetic_test(cid, test_input=[[3, 1, 4, 2]], expected_output=[4, 3, 2, 1])
        fda.run_synthetic_test(cid, test_input=[[10, -5, 0]], expected_output=[10, 0, -5])
        res3 = fda.run_synthetic_test(cid, test_input=[[1]], expected_output=[1])
        print_info("Resultats", f"{res3['test_passes']}/{res3['test_runs']} reussis (trust={res3['trust_score']})")
        if res3["trust_score"] == 1.0:
            print_success("Code autogenere fiable dans l'arene synthetique.")
        else:
            print_fail(f"trust_score attendu 1.0, obtenu {res3['trust_score']}")
            ok = False

        # 4D. Evaluation de promotion. Derogation time-lock ASSUMEE (demo) ; le
        # teardown en finally garantit qu'aucun privilege Ring 1 ne persiste.
        print("  >> Test 4 : evaluation darwinienne pour promotion Ring 1 (demo, time-lock deroge)...")
        promo = fda.evaluate_promotion(cid, min_test_runs=3, min_trust_score=0.85, ignore_time_lock=True)
        print_info("Decision", f"promu={promo.get('promoted')} | statut={promo.get('status')} | Ring={promo.get('ring')}")
        if promo.get("promoted") is True and promo.get("ring") == 1:
            print_success("Chaine evolutive complete : quarantaine -> test -> promotion Ring 1.")
        else:
            print_fail(f"Promotion inattendue : {promo.get('reason')}")
            ok = False
    except Exception as e:
        print_fail(f"Quarantaine Darwinienne: {e}")
        ok = False
    finally:
        # Teardown : supprime le candidat de demo (pas d'accumulation, pas de residu Ring 1).
        if fda is not None and cid is not None:
            try:
                conn = fda._conn()
                conn.execute("DELETE FROM darwinian_candidates WHERE candidate_id = ?", (cid,))
                conn.commit()
                conn.close()
                print_info("Teardown arene", f"candidat {cid} supprime (zero residu)")
            except Exception as e:
                print_fail(f"ECHEC teardown candidat {cid}: {e}")
                ok = False
    return ok


def main():
    print("\n" + "#" * 78)
    print("  === DEMONSTRATION VERIFIEE : LES 4 PILIERS D'AUTONOMIE NOKIDO ===")
    print("#" * 78)

    results = {}
    results["Metabolisme"] = prove_metabolism_sensors()
    time.sleep(0.3)
    results["Anti-contention"] = prove_anti_contention_shield()
    time.sleep(0.3)
    results["Anti-spoofing"] = prove_anti_spoofing_locks()
    time.sleep(0.3)
    results["Quarantaine darwinienne"] = prove_darwinian_quarantine()

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print("\n" + "#" * 78)
    print(f"  BILAN : {passed}/{total} piliers verifies")
    for name, v in results.items():
        print(f"    {'[OK]' if v else '[!!]'} {name}")
    if passed == total:
        print("  === C.Q.F.D. : LES 4 PILIERS D'AUTONOMIE SONT OPERATIONNELS ET VERIFIES ===")
    else:
        print("  === ECHEC : au moins un pilier n'est PAS verifie (voir ci-dessus) ===")
    print("#" * 78 + "\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
