"""NR — un job lance par /admin doit etre OBSERVABLE et RECONCILIABLE.

MESURE DU 2026-09-20, de bout en bout. Deux jobs lances par `/admin/run_job` :

    HTTP 200, job_id rendu, pid rendu          -> ACCEPTED  prouve
    enfants reels vivants (pid 6532, 9540)     -> STARTED   prouve
    .log 0 o · .err 0 o · .rc ABSENT a 12 min  -> PRODUCED  INDETERMINE
    (le script prend 23 s quand il tourne par l'autre voie)

TROIS CAUSES CUMULEES, mesurees et non deduites :

  1. WRAPPER MINIMAL. `/admin` genere 266 octets :

         rc = subprocess.run([py, script]).returncode
         open(rc_file, 'w').write(str(rc))

     Aucune redirection : `.log` et `.err` sont vides PAR CONSTRUCTION, ce n'est
     pas une panne. Aucun `LAFORGE_JOB_ID` / `NOKIDO_HUB_RUN_ID` /
     `NOKIDO_SERVICE_ID` : aucune correlation n'est possible entre un stimulus
     (NREM1) et le processus qui en resulte.
     La voie `/mcp` genere 3 536 octets pour le meme travail : redirection,
     identifiants de correlation, garde RSS et log, et un `_dire()` qui ne leve
     jamais -- « un journal qui echoue ne desarme pas un garde ».

  2. REPERTOIRE SEPARE. `/admin` ecrit dans `C:/tmp/nokido_jobs`, le
     reconciliateur balaie `sandbox/jobs`. Mesure : `reconcile_jobs()` a vu
     1 948 fiches et ZERO de mes deux jobs. Les jobs admin sont donc hors de
     portee de l'organe qui repare les `status: running` a vie -- exactement le
     defaut que ce reconciliateur existe pour corriger (51 fiches figees le
     2026-08-02).

  3. `lane` N'EST JAMAIS LUE. `admin_run_job` lit `script` et `online`, rien
     d'autre. Le superviseur le SAIT deja : son propre code dit, pour un autre
     appel, « via /mcp et non /admin/run_job : seule cette voie passe par
     forge_job_runner et honore la lane (anti-saturation du 2026-08-30) ». La
     lecon est ecrite a un endroit et pas appliquee a l'autre.

CE QUE CE NR GARDE : `/admin/run_job` passe par l'organe canonique
`forge_job_runner.launch_job`, qui apporte les trois proprietes d'un coup. On ne
construit pas un contrat d'execution -- il existe, il est teste, il est deja
nomme par l'appelant. On le RACCORDE.

Ce NR lit la SOURCE : le comportement complet demande un hub demarre et un job
reel, ce qu'un test pur ne doit pas exiger. La preuve d'execution est faite
separement, a la main, et consignee au commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
HUB = RACINE / "tools" / "nokido_hub.py"


def _corps_admin_run_job() -> str:
    if not HUB.exists():
        pytest.skip("nokido_hub.py absent")
    src = HUB.read_text(encoding="utf-8", errors="replace")
    d = re.search(r"async def admin_run_job\(request\):", src)
    assert d, "admin_run_job introuvable : la forme du hub a change"
    suite = re.search(r"\n    async def \w+|\n    def \w+", src[d.end():])
    fin = d.end() + (suite.start() if suite else 4000)
    return src[d.start():fin]


def test_admin_run_job_passe_par_l_organe_canonique():
    """`forge_job_runner.launch_job` porte deja redirection, correlation, lane et
    garde RSS. Le raccorder apporte les trois proprietes manquantes d'un coup."""
    corps = _corps_admin_run_job()
    assert "launch_job" in corps, (
        "/admin/run_job genere toujours son propre wrapper minimal (266 o) au lieu "
        "de passer par forge_job_runner.launch_job : les jobs restent sans log, "
        "sans correlation, hors du reconciliateur et sans lane."
    )


def test_la_lane_demandee_est_LUE():
    """Un job sans lane a sature la machine le 2026-08-30 (hub bloque, 4 appels en
    timeout). L'appelant la passe deja ; c'est la route qui l'ignorait."""
    corps = _corps_admin_run_job()
    # DEUX formes acceptables, une seule exigence : que le chemin emprunte soit
    # PROUVE lire la lane. La route peut la lire elle-meme, ou deleguer a
    # l'organe qui lance -- la delegation est meme preferable, puisqu'elle
    # empeche chaque appelant de relire le corps a sa facon et d'en oublier un
    # champ. Ce qu'on refuse, c'est qu'aucun des deux ne l'emporte.
    if "params_depuis_corps" in corps:
        # On ne se contente PAS de voir le nom : on APPELLE le traducteur.
        # Un nom present ne prouve rien -- c'est la lecon du 2026-09-21.
        from nokido_agent.app.forge_job_runner import params_depuis_corps
        assert params_depuis_corps({"lane": "ci"})["lane"] == "ci", (
            "la route delegue a params_depuis_corps, mais celui-ci ne transmet "
            "pas la lane : la delegation ne vaut que si le delegue tient"
        )
        return
    assert re.search(r'body\.get\(\s*["\']lane["\']', corps), (
        "`lane` n'est pas lue dans le corps de la requete : l'anti-saturation ne "
        "peut pas s'appliquer, quoi que demande l'appelant."
    )


def test_le_wrapper_minimal_n_est_PLUS_genere_ici():
    """Le pendant : sans lui, on pourrait AJOUTER launch_job en laissant l'ancien
    chemin actif, et croire le defaut corrige alors que rien n'a change."""
    corps = _corps_admin_run_job()
    assert "subprocess.run(" not in corps, (
        "le wrapper minimal est toujours construit ici : l'ancien chemin survit "
        "a cote du neuf, et c'est lui qui produirait les jobs muets."
    )
