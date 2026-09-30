"""tools/forge_docker_test_a_vide.py — L'ENGINE DOCKER TIENT-IL A VIDE ?

Test decisif du blocker « l engine Docker meurt sous charge conteneur », ouvert
depuis le 25-07 et jamais tranche. Question posee, une seule : l engine survit-il
SANS conteneur, ou meurt-il de lui-meme ?

  - s il TIENT a vide  -> la cause est dans les conteneurs qui le rechargent
                          (searxng porte --restart unless-stopped et remonte des
                          que l engine demarre : boucle) ;
  - s il MEURT a vide  -> la cause est dans l engine ou dans WSL, et aucun reglage
                          de conteneur n y changera rien.

Les deux reponses sont utiles ; c est ce qui fait un bon test. L hypothese du bind
settings.yml (chemin hote avec espaces) n a JAMAIS ete prouvee comme lien de
causalite — ce protocole ne la suppose pas.

REVERSIBILITE, le point qui compte : les politiques de redemarrage sont RELEVEES
avant d etre modifiees, ecrites dans un fichier d etat, et restaurees a la fin
(y compris si le test echoue en cours de route). Rien n est supprime, aucun
conteneur n est detruit : on ne fait que suspendre leur redemarrage automatique
le temps de la mesure.

COMPTE D EXECUTION — piege paye a la premiere tentative : lance en `run_job`, ce
script tourne sous le compte du BAC A SABLE, qui recoit « permission denied while
trying to connect to the docker API » sur le pipe. Il lisait donc « engine DOWN »
alors que le keeper voyait `daemon_up: true, 29.6.2` au meme instant — un « je ne
peux pas voir » compte comme un « c est mort », exactement le defaut que ce depot
documente partout. Seul LaForgeTrusted est membre de docker-users : ce script se
lance en `trusted_script`, JAMAIS en run_job.

Le cap de duree de trusted_script (~120 s) impose de decouper le protocole :
  --setup    prepare (demarre l engine, releve et neutralise les politiques,
             arrete les conteneurs) — quelques dizaines de secondes ;
  --sonde N  observe N secondes et rend un verdict PARTIEL ; on l enchaine
             plusieurs fois pour couvrir la fenetre critique (~2 min apres le
             boot, ou la mort a ete mesuree) ;
  --restore  restaure les politiques, rejouable seul a tout moment.

Usage : run action=trusted_script path=tools/forge_docker_test_a_vide.py
        script_args="--setup"   puis   script_args="--sonde 90"   (x3)
        puis script_args="--restore"
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETAT = ROOT / "sandbox" / "docker_test_a_vide_etat.json"
JOURNAL = ROOT / "sandbox" / "docker_test_a_vide.jsonl"
INTERVALLE = 30.0


def _d(*args, timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def _engine_up() -> bool:
    rc, _ = _d("version", "--format", "{{.Server.Version}}", timeout=20)
    return rc == 0


def _politiques() -> dict:
    """{nom: politique} pour TOUS les conteneurs, y compris arretes."""
    rc, out = _d("ps", "-a", "--format", "{{.Names}}")
    if rc != 0:
        return {}
    pol = {}
    for nom in [n.strip() for n in out.splitlines() if n.strip()]:
        rc2, o2 = _d("inspect", "-f", "{{.HostConfig.RestartPolicy.Name}}", nom)
        if rc2 == 0:
            pol[nom] = o2.strip() or "no"
    return pol


def _sauvegarder_etat(pol: dict) -> dict:
    """Sauvegarde les politiques de redémarrage sans écraser les politiques d'origine non-'no'."""
    sauve = dict(pol)
    if ETAT.is_file():
        try:
            prev = json.loads(ETAT.read_text(encoding="utf-8"))
            prev_pol = prev.get("politiques") or {}
            all_current_no = all(v == "no" for v in pol.values()) if pol else False
            all_prev_no = all(v == "no" for v in prev_pol.values()) if prev_pol else False
            # Conserver la politique non-"no" d'origine si la politique courante est "no"
            for k, prev_v in prev_pol.items():
                if prev_v and prev_v != "no" and sauve.get(k) == "no":
                    sauve[k] = prev_v
            if all_current_no and not all_prev_no:
                print("NOTE: Politiques courantes toutes a 'no' — fusion avec l'etat precedent pour preserver l'origine.")
        except Exception as e:  # noqa: BLE001
            print(f"WARN: Erreur lecture etat precedent pour fusion: {e}")
    ETAT.write_text(json.dumps({"ts": time.time(), "politiques": sauve}, indent=1), encoding="utf-8")
    return sauve


def _restaurer() -> int:
    if not ETAT.is_file():
        print("aucun etat sauvegarde — rien a restaurer [rien-a-restaurer]")
        return 0
    try:
        d = json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ARRET : fichier d'etat corrompu ({e}) [etat-perdu]")
        return 1

    politiques = d.get("politiques") or {}
    non_no = {k: v for k, v in politiques.items() if v and v != "no"}
    if not politiques or not non_no:
        print("0 politique(s) restauree(s) (etat-perdu ou 0 politique d'origine non-no) [etat-perdu]")
        return 0

    if not _engine_up():
        print("ARRET : engine DOWN, restauration impossible maintenant.")
        print("        relancer ce script avec --restore quand Docker sera up.")
        return 2

    n = 0
    for nom, pol in non_no.items():
        rc, out = _d("update", f"--restart={pol}", nom)
        print(f"  restore {nom} -> {pol} ({'ok' if rc == 0 else out[:70]})")
        n += (rc == 0)

    if n > 0:
        print(f"{n} politique(s) restauree(s) [restaure]")
    else:
        print("0 politique(s) restauree(s) (echec des commandes docker update) [echec-restauration]")
    return 0


def _sonde(secondes: int) -> int:
    """Observe l engine SANS rien modifier. Verdict PARTIEL, a enchainer."""
    print(f"=== SONDE {secondes}s (a vide) ===", flush=True)
    fin = time.time() + secondes
    n_ok = n_ko = 0
    premier_ko = None
    t0 = time.time()
    with JOURNAL.open("a", encoding="utf-8") as j:
        while time.time() < fin:
            up = _engine_up()
            rc_c, out_c = _d("ps", "-q")
            nb = len([x for x in out_c.split() if x.strip()]) if rc_c == 0 else -1
            j.write(json.dumps({"ts": time.time(), "up": up, "conteneurs": nb,
                                "phase": "sonde"}) + "\n")
            j.flush()
            if up:
                n_ok += 1
            else:
                n_ko += 1
                if premier_ko is None:
                    premier_ko = round(time.time() - t0)
            print(f"  T+{round(time.time()-t0):3d}s  engine={'UP' if up else 'DOWN'}"
                  f"  conteneurs={nb}", flush=True)
            time.sleep(INTERVALLE)
    print(f"\nSONDE : UP={n_ok} DOWN={n_ko}"
          + (f" — 1er echec a T+{premier_ko}s" if premier_ko is not None else ""))
    if n_ko == 0:
        print("  -> a vide, l engine a TENU pendant cette fenetre.")
    else:
        print("  -> l engine est TOMBE a vide : la cause n est pas dans les conteneurs.")
    return 0


def _isoler(nom: str, minutes: int, latence_sec: int = 300) -> int:
    """Remonte UN SEUL conteneur nomme et mesure si l engine tient AVEC lui.

    Sortie du test a vide : l engine tient sans conteneur. Ce mode designe le
    COUPABLE. On neutralise tout (reversible), on demarre le seul `nom`, on observe.
    Si l engine tombe avec ce conteneur seul -> c est lui. Sinon -> pas lui.

    Concu pour tourner en session OWNER (agy delegue) : pas de cap de duree, donc
    setup + demarrage + observation longue + restauration dans un seul appel.
    Restaure TOUJOURS a la fin, y compris sur interruption.
    """
    print(f"=== ISOLATION : engine + le SEUL conteneur '{nom}' ===", flush=True)
    if not _engine_up():
        print("ARRET : engine down — lancer d abord une mise en place / demarrage.")
        return 3
    pol = _politiques()
    if nom not in pol:
        print(f"ARRET : conteneur '{nom}' inconnu. Connus : {list(pol)}")
        return 2
    pol = _sauvegarder_etat(pol)
    try:
        # 1. Neutraliser TOUTES les politiques + arreter tout le monde.
        for n, p in pol.items():
            if p in ("always", "unless-stopped", "on-failure"):
                _d("update", "--restart=no", n)
        rc, out = _d("ps", "-q")
        actifs = [x for x in out.split() if x.strip()]
        if actifs:
            _d("stop", *actifs, timeout=120)
        time.sleep(5)
        # 2. Demarrer LE SEUL conteneur cible.
        rc, out = _d("start", nom)
        print(f"[start {nom}] {'ok' if rc == 0 else out[:120]}", flush=True)
        # 3. Observer : l engine tient-il avec ce conteneur seul ?
        fin = time.time() + minutes * 60
        t0 = time.time()
        n_ok = n_ko = 0
        premier_ko = None
        with JOURNAL.open("a", encoding="utf-8") as j:
            while time.time() < fin:
                up = _engine_up()
                rc_c, out_c = _d("ps", "-q")
                nb = len([x for x in out_c.split() if x.strip()]) if rc_c == 0 else -1
                j.write(json.dumps({"ts": time.time(), "up": up, "conteneurs": nb,
                                    "phase": f"isoler:{nom}"}) + "\n")
                j.flush()
                if up:
                    n_ok += 1
                else:
                    n_ko += 1
                    if premier_ko is None:
                        premier_ko = round(time.time() - t0)
                print(f"  T+{round(time.time()-t0):3d}s  engine={'UP' if up else 'DOWN'}"
                      f"  conteneurs={nb}", flush=True)
                time.sleep(INTERVALLE)
        print(f"\n=== VERDICT ISOLATION '{nom}' : UP={n_ok} DOWN={n_ko} ===")
        if n_ko == 0:
            seuil_innocence_sec = 2 * latence_sec
            duree_sec = minutes * 60
            if duree_sec < seuil_innocence_sec:
                mins_requis = (seuil_innocence_sec + 59) // 60
                print(f"  VERDICT NON CONCLUANT : l engine a tenu {minutes} min avec '{nom}' seul,")
                print(f"  mais la fenetre ({minutes} min) est inferieure au seuil d'innocence (>= 2x latence observee {latence_sec // 60} min = {mins_requis} min).")
                print(f"  -> Pour innocenter '{nom}', rejouer avec --minutes {mins_requis} minimum.")
            else:
                print(f"  l engine a TENU avec '{nom}' seul pendant {minutes} min (>= 2x latence observee {latence_sec // 60} min) -> ce conteneur N EST PAS le coupable.")
        else:
            print(f"  l engine est TOMBE avec '{nom}' seul (1er echec T+{premier_ko}s)")
            print(f"  -> '{nom}' EST le coupable (ou l un des coupables).")
    finally:
        # Restauration systematique — meme si l observation a echoue en cours.
        print("\n[restore] retablissement des politiques", flush=True)
        _restaurer()
    return 0


def main() -> int:
    args = sys.argv[1:]
    latence_sec = 300
    if "--latence-sec" in args:
        k = args.index("--latence-sec")
        if k + 1 < len(args) and args[k + 1].isdigit():
            latence_sec = int(args[k + 1])
    if "--restore" in args:
        return _restaurer()
    if "--isoler" in args:
        i = args.index("--isoler")
        nom = args[i + 1] if i + 1 < len(args) else ""
        mins = 4
        if "--minutes" in args:
            k = args.index("--minutes")
            if k + 1 < len(args) and args[k + 1].isdigit():
                mins = int(args[k + 1])
        if not nom:
            print("usage: --isoler <nom_conteneur> [--minutes N] [--latence-sec M]")
            return 1
        return _isoler(nom, mins, latence_sec=latence_sec)
    if "--sonde" in args:
        i = args.index("--sonde")
        n = int(args[i + 1]) if i + 1 < len(args) and args[i + 1].isdigit() else 90
        return _sonde(n)
    minutes = 0  # --setup : preparation seule, l observation passe par --sonde
    if "--minutes" in args:
        i = args.index("--minutes")
        if i + 1 < len(args) and args[i + 1].isdigit():
            minutes = int(args[i + 1])

    print("=== TEST : l engine Docker tient-il A VIDE ? (preparation) ===", flush=True)

    # 1. L engine doit etre up pour qu on puisse neutraliser les politiques.
    if not _engine_up():
        print("[1] engine DOWN -> demande de demarrage via le keeper souverain", flush=True)
        (ROOT / "sandbox" / "docker.wanted").write_text(str(time.time()), encoding="utf-8")
        for _ in range(5):  # borne courte : trusted_script est cape a ~120 s
            time.sleep(12)
            if _engine_up():
                break
        if not _engine_up():
            print("MISE EN PLACE INCOMPLETE : l engine n a pas demarre dans la fenetre.")
            print("  docker.wanted est POSE, le keeper va le lancer — relancer --setup")
            print("  dans une minute. Ce n est PAS le resultat du test.")
            return 3
    print("[1] engine UP", flush=True)

    # 2. Relever AVANT de modifier — sans quoi la restauration serait une devinette.
    pol = _politiques()
    pol = _sauvegarder_etat(pol)
    auto = {n: p for n, p in pol.items() if p in ("always", "unless-stopped", "on-failure")}
    print(f"[2] {len(pol)} conteneurs, dont {len(auto)} en redemarrage AUTO : {list(auto)}", flush=True)

    # 3. Neutraliser (reversible) puis arreter. On ne DETRUIT rien.
    for nom in auto:
        rc, out = _d("update", "--restart=no", nom)
        print(f"    {nom} -> restart=no ({'ok' if rc == 0 else out[:60]})", flush=True)
    rc, out = _d("ps", "-q")
    actifs = [x for x in out.split() if x.strip()]
    if actifs:
        print(f"[3] arret de {len(actifs)} conteneur(s) actif(s)", flush=True)
        _d("stop", *actifs, timeout=120)
    else:
        print("[3] aucun conteneur actif", flush=True)

    if minutes <= 0:
        print("\n[4] PRET. Le vide est etabli : enchainer maintenant")
        print("    script_args=\"--sonde 90\"  (plusieurs fois, la mort a ete mesuree")
        print("    ~2 min apres le boot), puis script_args=\"--restore\".")
        return 0

    # Observation A VIDE. Un echantillonnage regulier, pas une lecture unique :
    # la mort de l engine est un fait TEMPOREL (mesure : ~2 min apres le boot).
    print(f"[4] observation a vide pendant {minutes} min (echantillon /{int(INTERVALLE)}s)", flush=True)
    fin = time.time() + minutes * 60
    n_ok = n_ko = 0
    premier_ko = None
    with JOURNAL.open("a", encoding="utf-8") as j:
        while time.time() < fin:
            up = _engine_up()
            rc_c, out_c = _d("ps", "-q")
            nb = len([x for x in out_c.split() if x.strip()]) if rc_c == 0 else -1
            j.write(json.dumps({"ts": time.time(), "up": up, "conteneurs": nb}) + "\n")
            j.flush()
            if up:
                n_ok += 1
            else:
                n_ko += 1
                if premier_ko is None:
                    premier_ko = round(time.time() - (fin - minutes * 60))
                    print(f"    !! engine DOWN a T+{premier_ko}s", flush=True)
            if nb > 0:
                print(f"    (note : {nb} conteneur(s) sont remontes — le vide n est plus tenu)",
                      flush=True)
            time.sleep(INTERVALLE)

    print("\n=== VERDICT ===")
    print(f"  echantillons UP={n_ok}  DOWN={n_ko}  sur {minutes} min")
    if n_ko == 0:
        print("  L ENGINE TIENT A VIDE.")
        print("  => la cause est DANS LES CONTENEURS qui le rechargent au demarrage")
        print("     (searxng porte --restart unless-stopped). Piste : les remonter UN A UN")
        print("     en mesurant, pour designer le coupable au lieu de le supposer.")
    else:
        print(f"  L ENGINE MEURT A VIDE (1er echec a T+{premier_ko}s).")
        print("  => la cause est dans l ENGINE ou dans WSL, PAS dans les conteneurs.")
        print("     Aucun reglage de conteneur n y changera rien ; regarder les logs WSL")
        print("     et Docker Desktop, et l historique des mises a jour (l integration WSL")
        print("     a deja ete decochee par une mise a jour, cf. 25-07).")
    print(f"\n  journal : {JOURNAL}")
    print("\n[5] restauration des politiques de redemarrage")
    _restaurer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
