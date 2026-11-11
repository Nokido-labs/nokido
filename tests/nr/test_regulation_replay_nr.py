# -*- coding: utf-8 -*-
"""NR -- simulateur de REJEU de la regulation RAM (tools/forge_regulation_replay.py, GO owner 28/10).

Contrat :
  * le rejeu APPELLE les fonctions existantes (tick Hamilton reel, plan_hamilton, regulation_hamilton_ram,
    gestes_observes, palier_pression_ram, _noter_ram_fenetre, delai_de_grace) -- jamais une copie ;
  * les seuils sont INJECTES le temps du rejeu puis RESTAURES (module et environnement intacts) ;
  * aucun etat vivant : ni get_snapshot, ni ordre superviseur, ni hormone, ni audit, ni fichier d'etat ;
  * la fidelite se MESURE contre le journal (concordance + ecarts nommes) ;
  * l'illisible se DIT (lignes rejetees comptees, signaux non journalises inventories).

Fixture : fenetre REELLE du 28/10 (08:51-08:59 UTC, vitals_history.jsonl + supervisor_ordres.jsonl du depot
vivant) -- 9 des 13 executeurs endormis a 08:53:56 et reveilles a 08:57:13 (4 noms caviardes a l'extraction).
"""
import ast
import json
import logging
import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

pytestmark = pytest.mark.timeout(120)

T_MINUIT = 1793145600.0  # 2026-10-28T00:00:00Z


def _t(hms: str) -> float:
    h, m, s = hms.split(":")
    return T_MINUIT + int(h) * 3600 + int(m) * 60 + float(s)


# (heure UTC, ram_pct, ram_free_gb, ram_used_gb) -- extrait verbatim de vitals_history.jsonl
VITAUX_28_10 = [
    ("08:51:05", 75.0, 5.93, 17.74), ("08:51:21", 75.2, 5.87, 17.79), ("08:51:36", 75.1, 5.9, 17.76),
    ("08:51:51", 74.8, 5.97, 17.69), ("08:52:06", 75.3, 5.84, 17.83), ("08:52:21", 74.5, 6.02, 17.64),
    ("08:52:37", 81.2, 4.45, 19.21), ("08:52:55", 81.7, 4.32, 19.34), ("08:53:10", 80.1, 4.71, 18.95),
    ("08:53:25", 80.1, 4.7, 18.96), ("08:53:40", 79.3, 4.9, 18.76), ("08:53:55", 76.4, 5.58, 18.09),
    ("08:54:11", 68.2, 7.53, 16.13), ("08:54:26", 68.1, 7.56, 16.11), ("08:54:41", 67.8, 7.61, 16.05),
    ("08:54:58", 67.7, 7.65, 16.02), ("08:55:14", 67.7, 7.65, 16.02), ("08:55:29", 68.0, 7.57, 16.09),
    ("08:55:44", 68.1, 7.56, 16.11), ("08:56:01", 68.6, 7.42, 16.24), ("08:56:16", 68.5, 7.46, 16.2),
    ("08:56:32", 67.9, 7.61, 16.06), ("08:56:47", 67.8, 7.61, 16.06), ("08:57:04", 68.7, 7.4, 16.27),
    ("08:57:19", 73.0, 6.38, 17.29), ("08:57:34", 76.5, 5.56, 18.1), ("08:57:50", 78.4, 5.11, 18.55),
    ("08:58:07", 76.6, 5.53, 18.14), ("08:58:22", 76.8, 5.48, 18.18), ("08:58:38", 76.8, 5.49, 18.17),
    ("08:58:53", 76.9, 5.47, 18.19),
]
EXECUTEURS = ["NokidoTaskExecutorCodex", "NokidoTaskExecutorMistral", "NokidoTaskExecutorOpencodeNemotron",
              "NokidoTaskExecutorOpencodeGlm", "NokidoTaskExecutorAntigravity", "NokidoTaskExecutorOpencodeGptoss",
              "NokidoTaskExecutorClaude", "NokidoTaskExecutorAgy", "NokidoTaskExecutor"]
SOMMEILS = ["08:53:56.265", "08:53:57.010", "08:53:57.300", "08:53:57.600", "08:53:58.000", "08:53:58.400",
            "08:53:58.900", "08:53:59.500", "08:54:00.100"]
REVEILS = ["08:57:13.100", "08:57:15.000", "08:57:16.000", "08:57:16.500", "08:57:17.000", "08:57:18.000",
           "08:57:19.000", "08:57:22.000", "08:57:23.000"]


def _iso(t: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@pytest.fixture()
def journal(tmp_path):
    """Racine factice : sandbox/vitals_history.jsonl, sandbox/supervisor_ordres.jsonl, lifecycle, services.toml."""
    sb = tmp_path / "sandbox"
    sb.mkdir()
    with open(sb / "vitals_history.jsonl", "w", encoding="utf-8") as f:
        for hms, pct, libre, used in VITAUX_28_10:
            f.write(json.dumps({"ts": _t(hms), "ram_pct": pct, "ram_free_gb": libre, "ram_used_gb": used}) + "\n")
        f.write("{ligne tronquee par rotation\n")
    with open(sb / "supervisor_ordres.jsonl", "w", encoding="utf-8") as f:
        for svc, hms in zip(EXECUTEURS, SOMMEILS):
            f.write(json.dumps({"ts": _iso(_t(hms)), "methode": "POST", "chemin": "/supervisor/sleep/" + svc,
                                "agent_declare": "RESOURCE_MANAGER"}) + "\n")
        for svc, hms in zip(EXECUTEURS, REVEILS):
            f.write(json.dumps({"ts": _iso(_t(hms)), "methode": "POST", "chemin": "/supervisor/wake/" + svc,
                                "agent_declare": "RESOURCE_MANAGER"}) + "\n")
        f.write(json.dumps({"ts": _iso(_t("08:55:00")), "methode": "POST",
                            "chemin": "/supervisor/service/stop/NokidoEmbedTrigger",
                            "agent_declare": "LLAMA_KEEPER"}) + "\n")
        # sommeil RESOURCE_MANAGER que le tick Hamilton suivant ne signe pas (« rien de neuf ») : autre chemin
        f.write(json.dumps({"ts": _iso(_t("08:55:30")), "methode": "POST",
                            "chemin": "/supervisor/sleep/NokidoChainExecutor",
                            "agent_declare": "RESOURCE_MANAGER"}) + "\n")
    with open(sb / "lifecycle_actions.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-10-28T08:54:02.000+00:00", "domain": "ram", "action": "hamilton_arme",
                            "reason": "pression SOI : 41 a ceder, 30 epargne(s) : 41 service(s) pour 3321 Mo a "
                                      "rendre (1534 Mo vises)"}) + "\n")
        f.write(json.dumps({"ts": "2026-10-28T08:55:59.000+00:00", "domain": "ram", "action": "hamilton_arme",
                            "reason": "RAM 67.7 % < seuil 78 % : rien de neuf a ceder"}) + "\n")
    toml = ["[[services]]\nname = \"%s\"\nessential = false\nwave = 5\nheartbeat_tier = \"slow\"\n" % s
            for s in EXECUTEURS]
    toml.append("[[services]]\nname = \"NokidoMCP\"\nessential = true\nwave = 1\n")
    (tmp_path / "services.toml").write_text("\n".join(toml), encoding="utf-8")
    return tmp_path


def _rp():
    import forge_regulation_replay as rp
    return rp


def _rejouer(journal, **seuils):
    """Fenetre REELLE du 28/10, rejouee sous la politique d'alors : reprise d'avant le budget RAM du 31/10
    (reprise_budget=0) -- la fidelite se juge contre le journal de ce jour-la, pas contre la politique d'aujourd'hui."""
    rp = _rp()
    fen = rp.lire_fenetre(journal, _t("08:51:00"), _t("08:59:00"))
    # 7/11 : ni duree minimale de sommeil, ni lot de reprise, ni plancher de gain ce jour-la (politique d'alors)
    seuils = {"reprise_budget": 0.0, "sommeil_min_s": 0.0, "reprise_lot": 1e9, "gain_min_mb": 0.0, **seuils}
    return rp, fen, rp.rejouer(fen, toml=journal / "services.toml", seuils=seuils,
                               phase_ts=fen["phase_journal"])


def test_la_politique_du_31_10_retient_la_reprise_sans_budget(journal):
    """Meme fenetre, politique d'aujourd'hui (budget arme, poids ILLISIBLES -> forfait prudent) : les 9 executeurs
    endormis a 08:53:56 ne repartent pas tous d'un coup comme le 28/10 -- et le rejeu ne lit jamais le tasks.db vivant."""
    rp = _rp()
    fen = rp.lire_fenetre(journal, _t("08:51:00"), _t("08:59:00"))
    r = rp.rejouer(fen, toml=journal / "services.toml", seuils={"reprise_budget": 1.0}, phase_ts=fen["phase_journal"])
    repris = [d for d in r["decisions"] if d["geste"] == "REPRENDRE"]
    assert len(repris) < len(EXECUTEURS), repris
    assert r["seuils"]["reprise_budget"] == 1.0


def test_couleur_declaree_et_aucune_copie_de_logique():
    rp = _rp()
    assert isinstance(getattr(rp, "__FORGE_COLOR__", None), str) and rp.__FORGE_COLOR__.startswith("regulation/")
    src = Path(rp.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(src)
    definis = {n.name for n in ast.walk(arbre) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for nom in ("palier_pression_ram", "regulation_hamilton_ram", "gestes_observes", "plan_hamilton",
                "ordre_delestage", "classe_hamilton", "delai_de_grace", "_regulation_hamilton_tick"):
        assert nom not in definis, "logique de regulation recopiee : %s" % nom
    # except muet interdit : tout except dit ce qu'il avale
    for n in ast.walk(arbre):
        if isinstance(n, ast.ExceptHandler):
            assert not (len(n.body) == 1 and isinstance(n.body[0], ast.Pass)), "except muet ligne %d" % n.lineno


def test_lecture_journal_compte_l_illisible(journal):
    rp = _rp()
    fen = rp.lire_fenetre(journal, _t("08:51:00"), _t("08:59:00"))
    assert len(fen["vitaux"]) == len(VITAUX_28_10)
    assert fen["rejets"]["vitals_history.jsonl"] == 1  # ligne tronquee : comptee, jamais avalee
    ordres = fen["decisions_journal"]
    assert len(ordres) == 18  # LLAMA_KEEPER n'est pas la regulation RAM
    assert {o["geste"] for o in ordres} == {"SUSPENDRE", "REPRENDRE"}
    assert fen["phase_journal"] == int(_t("08:53:56.265"))
    assert fen["verdicts"] and fen["verdicts"][0][1] == "SOI"


def test_sommeil_non_signe_par_le_tick_hamilton_est_hors_hamilton(journal):
    rp = _rp()
    fen = rp.lire_fenetre(journal, _t("08:51:00"), _t("08:59:00"))
    hors = fen["hors_hamilton_journal"]
    assert [h["service"] for h in hors] == ["NokidoChainExecutor"]
    assert "rien de neuf" in hors[0]["origine"]
    assert "NokidoChainExecutor" not in {d["service"] for d in fen["decisions_journal"]}


def test_verdict_maintenu_seulement_sur_demande():
    rp = _rp()
    verdicts = [(1000.0, "NON_SOI", "hamilton_arme")]
    assert rp._verdict_au(1100.0, verdicts, "SOI", 60.0)[0] == "SOI"
    assert rp._verdict_au(1100.0, verdicts, "SOI", 60.0, maintien_s=300.0)[0] == "NON_SOI"
    assert rp._verdict_au(1400.0, verdicts, "SOI", 60.0, maintien_s=300.0)[0] == "SOI"


def test_ecarts_portent_un_code(journal):
    rp, fen, r = _rejouer(journal, seuil_sommeil=80.0)
    c = rp.concordance(r["decisions"], fen["decisions_journal"], tolerance_s=45.0, fen=fen)
    assert {e["code"] for e in c["absents_du_rejeu"]} <= {"PRESSION_NON_VUE", "REPRISE_NON_REPRODUITE"}
    assert {e["code"] for e in c["absents_du_rejeu"]} == {"PRESSION_NON_VUE", "REPRISE_NON_REPRODUITE"}


def test_rejeu_appelle_le_tick_reel_et_les_fonctions_pures(journal, monkeypatch):
    appels = {"tick": 0, "regulation": 0, "palier": 0, "gestes": 0, "plan": 0}
    for nom, cle in (("_regulation_hamilton_tick", "tick"), ("regulation_hamilton_ram", "regulation"),
                     ("palier_pression_ram", "palier"), ("gestes_observes", "gestes"), ("plan_hamilton", "plan")):
        vrai = getattr(rm, nom)

        def espion(*a, _v=vrai, _c=cle, **k):
            appels[_c] += 1
            return _v(*a, **k)
        monkeypatch.setattr(rm, nom, espion)
    _rejouer(journal)
    assert all(v > 0 for v in appels.values()), appels


def test_aucun_etat_vivant_touche(journal, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("etat vivant touche")
    for nom in ("get_snapshot", "_supervisor_auth_headers", "_audit_lifecycle", "_sample_once",
                "vetos_sommeil_actifs", "attribuer_pression", "_memoire_privee_mb"):
        monkeypatch.setattr(rm, nom, interdit)
    fenetre_avant = list(rm._RAM_FENETRE)
    etat_avant = rm._HAMILTON_ETAT_RAM_PATH
    _, _, r = _rejouer(journal)
    assert r["ticks"], "aucun tick rejoue"
    assert not [t for t in r["ticks"] if "ILLISIBLE" in str(t["motif"])], r["ticks"]
    assert list(rm._RAM_FENETRE) == fenetre_avant
    assert rm._HAMILTON_ETAT_RAM_PATH is etat_avant


def test_seuils_injectes_puis_restaures(journal):
    avant = (rm._SUPERVISOR_SLEEP_RAM_THRESHOLD, rm._HAMILTON_CALME_MIN_S, rm._PALIER_GENE_PCT,
             os.environ.get("LAFORGE_DETRESSE_LIBRE_GB"), rm.time)
    _, _, r = _rejouer(journal, seuil_sommeil=80.0, detresse_libre_gb=0.9, calme_min_s=30.0, gene_pct=90.0)
    assert (rm._SUPERVISOR_SLEEP_RAM_THRESHOLD, rm._HAMILTON_CALME_MIN_S, rm._PALIER_GENE_PCT,
            os.environ.get("LAFORGE_DETRESSE_LIBRE_GB"), rm.time) == avant
    assert r["seuils"]["seuil_sommeil"] == 80.0
    # plancher 60 s a 08:53:56 = 79.3 % : sous 80 % rien ne s'endort
    assert not [d for d in r["decisions"] if d["geste"] == "SUSPENDRE"]


def test_fidelite_fenetre_reelle_28_10(journal):
    rp, fen, r = _rejouer(journal)
    sommeils = [d for d in r["decisions"] if d["geste"] == "SUSPENDRE"]
    assert {d["service"] for d in sommeils} == set(EXECUTEURS)
    assert all(abs(d["ts"] - _t("08:53:56")) < 1.0 for d in sommeils)
    tick = next(t for t in r["ticks"] if abs(t["ts"] - _t("08:53:56")) < 1.0)
    assert tick["ram_decision"] == 79.3 and tick["palier"] == "RALENTISSEMENT"
    c = rp.concordance(r["decisions"], fen["decisions_journal"], tolerance_s=45.0)
    assert c["concordance"] == 1.0, c
    assert c["n_journal"] == 18 and c["n_rejeu"] == 18
    assert all(abs(a["delta_s"]) <= 45.0 for a in c["apparies"])


def test_ecarts_nommes_quand_le_rejeu_diverge(journal):
    rp, fen, r = _rejouer(journal, seuil_sommeil=80.0)
    c = rp.concordance(r["decisions"], fen["decisions_journal"], tolerance_s=45.0)
    assert c["concordance"] == 0.0
    assert len(c["absents_du_rejeu"]) == 18 and not c["absents_du_journal"]
    assert all(e.get("cause") for e in c["absents_du_rejeu"])


def test_modele_superviseur_un_endormi_quitte_le_registre(journal):
    _, _, r = _rejouer(journal)
    t2 = next(t for t in r["ticks"] if abs(t["ts"] - _t("08:54:56")) < 1.0)
    assert not set(EXECUTEURS) & set(t2["vivants"])
    fin = r["ticks"][-1]
    assert set(EXECUTEURS) <= set(fin["vivants"])


def test_inventaire_dit_l_illisible(journal):
    rp = _rp()
    inv = rp.inventorier_signaux(journal, _t("08:51:00"), _t("08:59:00"))
    par_nom = {s["signal"]: s for s in inv}
    assert par_nom["ram_pct"]["statut"] == "PARTIEL" and 14.0 <= par_nom["ram_pct"]["cadence_s"] <= 17.0
    for illisible in ("palier_pression_ram", "registre_vivants", "rss_par_service", "vetos_sommeil"):
        assert par_nom[illisible]["statut"] == "ILLISIBLE", par_nom[illisible]
    assert par_nom["ordres_superviseur"]["statut"] == "LU"


def test_cout_expose_ses_composantes(journal):
    rp, fen, r = _rejouer(journal)
    c = rp.cout(r, fen)
    sommeil = c["composantes"]["temps_endormi_executeurs_s"]
    # 9 executeurs endormis du tick 08:53:56 au tick de reprise (120 s de calme -> 08:56:56 ou 08:57:56)
    assert 9 * 170 <= sommeil <= 9 * 250, sommeil
    assert set(c["composantes"]) >= {"temps_endormi_executeurs_s", "pics_ram_s", "arrets_docker"}
    assert c["total"] >= 0 and c["limites"]


def test_delai_docker_sans_effet_de_bord_journal():
    rp = _rp()
    avant = list(logging.getLogger().handlers)
    d = rp.delai_docker("DETRESSE")
    assert d == 0.0
    assert list(logging.getLogger().handlers) == avant
