"""NR d'INTEGRATION — la chaine complete sur le chemin REEL.

Le NR de contrat (test_skill_execution_nr) injecte des realisations : il
verifie le CONTRAT. Celui-ci traverse les realisations REELLES, lit de VRAIS
fichiers de pouls et passe par le point d'entree CLI.

Motif : « un NR emprunte le chemin reel, pas seulement la fonction ».
`check()` passait ses tests pendant que `--check` mourait en NameError ; deux
fois le meme jour le 2026-09-12, un point d'entree a casse pendant que sa
fonction etait verte. Ici on execute vraiment, on observe vraiment.

Aucun effet irreversible n'est cable : lire un pouls ne change rien. Faire
tourner une capacite a effet physique pour pouvoir ecrire « E2E PASS »
transformerait une demonstration en incident.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_skill_capability_graph as cg  # noqa: E402
import forge_skill_execution as ex  # noqa: E402
import forge_skill_realisations as re_  # noqa: E402


def _pouls(dossier: pathlib.Path, service: str, age_s: float = 0.0) -> pathlib.Path:
    """Ecrit un VRAI fichier de pouls, avec un mtime reel."""
    dossier.mkdir(parents=True, exist_ok=True)
    p = dossier / ("%s.heartbeat" % service)
    p.write_text(str(time.time()), encoding="utf-8")
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


def _plan_diagnostic():
    return cg.planifier(but=cg.Fait("diagnostic_pipeline_rendu"),
                        connus={cg.Fait("service_nomme")})


def test_chaine_complete_sur_un_pouls_frais(tmp_path, monkeypatch):
    """Deux capacites reelles, executees et OBSERVEES, en une seule lignee."""
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    _pouls(tmp_path, "svc_temoin", age_s=0)

    contexte = {"service": "svc_temoin"}
    trace = ex.executer_plan(_plan_diagnostic(), re_.REALISATIONS, contexte)

    assert trace.verdict == "PLAN_COMPLETED", trace.motif
    assert len(trace.executions) == 2
    assert all(e.execution_mode == ex.NOKIDO_NATIF for e in trace.executions), (
        "ces deux capacites sont executees PAR NOKIDO, pas deleguees a un client")
    # Le contexte final se lit sur la TRACE : l'executeur travaille sur une
    # copie et remonte le resultat, il ne mute pas le dict de l'appelant.
    assert "VIVANT" in trace.contexte.get("diagnostic", "")

    racines = {e.execution_racine for e in trace.executions}
    assert len(racines) == 1
    assert trace.executions[1].parent_execution_id == trace.executions[0].execution_id


def test_un_pouls_fige_donne_la_piste_1_de_la_checklist(tmp_path, monkeypatch):
    """La procedure DOCUMENTEE par le skill est celle qui s'execute."""
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    _pouls(tmp_path, "svc_mort", age_s=re_.SEUIL_FIGE_S + 60)

    contexte = {"service": "svc_mort"}
    trace = ex.executer_plan(_plan_diagnostic(), re_.REALISATIONS, contexte)

    assert trace.verdict == "PLAN_COMPLETED", trace.motif
    diag = trace.contexte.get("diagnostic", "")
    assert "FIGE" in diag and "backlog" in diag, (
        "consommateur fige => le drain est mort et le backlog s'empile : "
        "c'est la piste 1 de la checklist du skill, pas une improvisation")


def test_un_pouls_illisible_ne_produit_aucun_fait(tmp_path, monkeypatch):
    """ILLISIBLE ne se range jamais du cote de ce qu'on sait.

    Le fichier n'existe pas : la sonde ne peut PAS conclure. Elle ne doit
    surtout pas rendre « mort » — c'est le capteur qui rend False pour
    « pas la » ET pour « acces refuse », et qui fabrique des pannes fictives.
    """
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))

    contexte = {"service": "svc_absent"}
    trace = ex.executer_plan(_plan_diagnostic(), re_.REALISATIONS, contexte)

    assert trace.verdict == "REPLAN_REQUIS"
    assert trace.executions[0].statut == "STEP_FAILED"
    assert not trace.executions[0].faits_acquis
    assert len(trace.executions) == 1, (
        "la seconde etape ne doit pas tourner sur une precondition non produite")
    assert "etat_consommateur_connu" in " ".join(trace.executions[0].faits_manquants)
    assert trace.contexte.get("etat_consommateur") is None
    assert "ILLISIBLE" in trace.contexte.get("etat_motif", "")


def _services_toml(tmp_path: pathlib.Path, nom: str, pouls: str,
                   disabled: bool) -> pathlib.Path:
    """Ecrit un VRAI services.toml au format reel du depot."""
    p = tmp_path / "services.toml"
    p.write_text(
        '[[service]]\nname = "%s"\nheartbeat = "sandbox/%s.heartbeat"\n'
        'disabled = %s\n' % (nom, pouls, "true" if disabled else "false"),
        encoding="utf-8")
    return p


def test_replan_bascule_sur_un_observateur_independant(tmp_path, monkeypatch):
    """Le cas qui prouve le replan : deux chemins REELS vers le meme fait.

    Ce n'est pas un doublon de complaisance. RULES_SHARED impose qu'aucune
    decision ne repose sur un signal unique quand plusieurs observateurs
    existent — et la mesure du 2026-09-12 en donne six cas concrets : des
    services qui declarent un pouls dont le fichier est ABSENT.

    Chemin 1 (heartbeat) ne peut rien dire. Chemin 2 (declaration) repond.
    """
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    monkeypatch.setenv("LAFORGE_SERVICES_TOML",
                       str(_services_toml(tmp_path, "NokidoTemoin", "svc_coupe",
                                          disabled=True)))
    # Aucun fichier de pouls n'est ecrit : le premier chemin DOIT echouer.

    trace = ex.executer_avec_replan(
        cg.Fait("diagnostic_pipeline_rendu"), re_.REALISATIONS,
        connus={cg.Fait("service_nomme")}, contexte={"service": "svc_coupe"})

    assert trace.verdict == "PLAN_COMPLETED", trace.motif
    statuts = [(e.capability_id, e.statut) for e in trace.executions]
    assert ("forge-workflow-autopsy::sonder_consommateur", "STEP_FAILED") in statuts
    assert ("forge-hub::sonder_service_declare", "STEP_COMPLETED") in statuts, (
        "le replan doit basculer sur le producteur ALTERNATIF du meme fait, "
        "pas reproposer celui qui vient d'echouer")

    racines = {e.execution_racine for e in trace.executions}
    assert len(racines) == 1, (
        "toutes les tentatives, replans compris, restent sous UNE lignee : "
        "sinon l'objectif n'est plus rattachable a ce qui a ete tente")
    assert any(e["type"] == "PLAN_REPLANNED" for e in trace.evenements)


def test_coupe_par_politique_n_est_pas_une_panne(tmp_path, monkeypatch):
    """DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE.

    Confondre les deux, c'est envoyer quelqu'un reparer un CHOIX. Le pouls
    absent est ici la CONSEQUENCE d'une decision, pas un symptome.
    """
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    monkeypatch.setenv("LAFORGE_SERVICES_TOML",
                       str(_services_toml(tmp_path, "NokidoCoupe", "svc_off",
                                          disabled=True)))

    trace = ex.executer_avec_replan(
        cg.Fait("diagnostic_pipeline_rendu"), re_.REALISATIONS,
        connus={cg.Fait("service_nomme")}, contexte={"service": "svc_off"})

    diag = trace.contexte.get("diagnostic", "")
    assert "PAS une panne" in diag and "rien a reparer" in diag, (
        "un service coupe par politique ne doit jamais etre rapporte comme "
        "une defaillance a reparer")
    assert trace.contexte["etat_consommateur"] == "DISABLED_BY_POLICY"


def test_un_service_actif_sans_pouls_n_est_pas_declare_mort(tmp_path, monkeypatch):
    """BLOQUE_PAR_DEPENDANCE != DEAD : il n'a peut-etre jamais demarre.

    NokidoEpistemicSoif a ete declare mort 62 h alors que 2 de ses 3 ports de
    dependance etaient muets — il n'avait jamais demarre.
    """
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    monkeypatch.setenv("LAFORGE_SERVICES_TOML",
                       str(_services_toml(tmp_path, "NokidoJamaisDemarre",
                                          "svc_neuf", disabled=False)))

    trace = ex.executer_avec_replan(
        cg.Fait("diagnostic_pipeline_rendu"), re_.REALISATIONS,
        connus={cg.Fait("service_nomme")}, contexte={"service": "svc_neuf"})

    diag = trace.contexte.get("diagnostic", "")
    assert "jamais demarre" in diag and "dependances" in diag, (
        "un service declare actif sans pouls appelle une verification de ses "
        "dependances, pas un constat de mort")


def test_sans_alternative_le_manque_est_qualifie(tmp_path, monkeypatch):
    """Manque de MATIERE et defaut du MECANISME ne se rapportent pas pareil."""
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    monkeypatch.setenv("LAFORGE_SERVICES_TOML", str(tmp_path / "vide.toml"))

    trace = ex.executer_avec_replan(
        cg.Fait("diagnostic_pipeline_rendu"), re_.REALISATIONS,
        connus={cg.Fait("service_nomme")}, contexte={"service": "svc_inconnu"})

    assert trace.verdict != "PLAN_COMPLETED"
    assert "manque de matiere" in trace.motif, (
        "quand le graphe n'offre plus d'alternative, le dire — sinon on lit "
        "un echec du mecanisme la ou il n'y a qu'un catalogue incomplet")


def test_boucle_multi_agent_complete_par_le_cli(tmp_path, monkeypatch, capsys):
    """NOKIDO -> NOKIDO -> CLAUDE -> retour, par le chemin reel.

    C'est le scenario qui distingue un planificateur d'un orchestrateur : le
    plan suspend sur une capacite que Nokido ne peut pas executer, un client
    rend son resultat, Nokido le qualifie et conclut.
    """
    import json

    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    _pouls(tmp_path, "svc_boucle", age_s=re_.SEUIL_FIGE_S + 60)

    # 1. Sans retour : le plan SUSPEND sur la delegation.
    rc = ex.main(["remede_propose", "--service", "svc_boucle"])
    sortie = capsys.readouterr().out
    assert rc == 0
    assert "PLAN_SUSPENDU_DELEGATION" in sortie
    assert "STEP_DELEGUE" in sortie

    # 2. Le client depose son retour ; la boucle se ferme.
    retour = tmp_path / "retour.json"
    retour.write_text(json.dumps({
        "client": "claude",
        "effets_declares": ["remede_propose"],
        "contenu": "remede redige par le client",
    }), encoding="utf-8")

    rc = ex.main(["remede_propose", "--service", "svc_boucle",
                  "--retour-de", str(retour)])
    sortie = capsys.readouterr().out

    assert rc == 0
    assert "PLAN_COMPLETED" in sortie
    assert "3 etape(s)" in sortie, (
        "le compte doit refleter la chaine REELLE : un plan de reprise vide "
        "annoncerait « 0 etape » sur trois etapes menees a leur effet")
    assert "DECLARATION" in sortie, (
        "la preuve doit dire qu'un effet repose sur une declaration de client")


def test_un_retour_qui_ne_declare_pas_l_effet_ne_ferme_pas_l_etape(tmp_path,
                                                                   monkeypatch,
                                                                   capsys):
    """Deposer un retour ne suffit pas : il doit porter l'effet attendu."""
    import json

    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    _pouls(tmp_path, "svc_vide", age_s=0)

    retour = tmp_path / "retour_vide.json"
    retour.write_text(json.dumps({"client": "claude", "effets_declares": []}),
                      encoding="utf-8")

    rc = ex.main(["remede_propose", "--service", "svc_vide",
                  "--retour-de", str(retour)])
    sortie = capsys.readouterr().out

    assert rc == 0
    assert "PLAN_COMPLETED" not in sortie, (
        "un retour qui ne rend pas l'effet attendu ne doit pas conclure le plan")


def test_le_cablage_reel_ne_depend_pas_de_l_ordre_d_import():
    """Un cycle d'import rendait le cablage VIDE selon qui importait en premier.

    Le CLI marchait pendant que la meme chaine sous pytest journalisait
    « cablage reel indisponible (ImportError) » : un comportement qui depend
    de l'ordre d'import est invisible en lecture de code.
    """
    reelles = ex.realisations_reelles()
    assert reelles, "le cablage reel doit se charger quel que soit l'ordre"
    assert "forge-workflow-autopsy::sonder_consommateur" in reelles
    assert "forge-hub::sonder_service_declare" in reelles


def test_le_replan_vise_le_fait_reellement_manquant(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    trace = ex.executer_plan(_plan_diagnostic(), re_.REALISATIONS,
                             {"service": "svc_absent"})

    besoin = ex.fait_manquant(trace)
    assert besoin is not None and besoin.type == "etat_consommateur_connu", (
        "le replan part du fait OBSERVE comme manquant, pas du but initial")


def test_le_point_d_entree_cli_traverse_la_chaine(tmp_path, monkeypatch, capsys):
    """Le CLI est le chemin reel : le tester separement de la fonction.

    Deux fois le 2026-09-12, une fonction etait verte pendant que son point
    d'entree mourait (cle disparue, format sur un None).
    """
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    _pouls(tmp_path, "svc_cli", age_s=0)

    rc = ex.main(["diagnostic_pipeline_rendu", "--service", "svc_cli"])
    sortie = capsys.readouterr().out

    assert rc == 0
    assert "PLAN_COMPLETED" in sortie
    assert "LIGNEE" in sortie and "parent=" in sortie, (
        "la provenance doit etre visible sur le chemin reel, pas seulement "
        "dans les objets internes")


def test_la_sortie_json_du_cli_porte_la_provenance(tmp_path, monkeypatch, capsys):
    """Une preuve doit etre exploitable par une machine, pas seulement lue."""
    monkeypatch.setenv("LAFORGE_POULS_DIR", str(tmp_path))
    _pouls(tmp_path, "svc_json", age_s=0)

    rc = ex.main(["diagnostic_pipeline_rendu", "--service", "svc_json", "--json"])
    assert rc == 0

    import json

    d = json.loads(capsys.readouterr().out)
    assert d["verdict"] == "PLAN_COMPLETED"
    assert d["execution_racine"]
    for champ in ("execution_id", "parent_execution_id", "skill_id",
                  "capability_id", "execution_mode", "transport"):
        assert champ in d["executions"][0], "champ de provenance manquant : %s" % champ
    assert d["executions"][1]["parent_execution_id"] == \
        d["executions"][0]["execution_id"]
