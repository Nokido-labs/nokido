"""Le gate de release doit REFUSER, y compris dans le doute.

Une CI de developpement est tolerante par choix (triage incremental) ; une
release ne l'est pas. Ce qui est verrouille ici n'est pas l'import du module mais
son ARBITRAGE : ce qu'il fait d'un controle rouge, d'un controle illisible, et
d'un controle qui explose.

La propriete centrale vient du verrou de composition (2026-08-14) : **une absence
de mesure n'est jamais un succes**. Un gate qui rend GO parce qu'il n'a pas pu
regarder est pire qu'aucun gate -- il fabrique une autorisation.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_release_gate as frg  # noqa: E402


def _fige(monkeypatch, *etats):
    """Remplace les controles reels par des verdicts imposes."""
    monkeypatch.setattr(frg, "CONTROLES",
                        [("c%d" % i, (lambda e: (lambda: (e, "fixe")))(e))
                         for i, e in enumerate(etats)])


def test_tout_vert_donne_GO(monkeypatch):
    _fige(monkeypatch, frg.VERT, frg.VERT)
    code, rapport = frg.gate()
    assert (code, rapport["verdict"]) == (0, "GO")


def test_un_rouge_donne_NO_GO(monkeypatch):
    _fige(monkeypatch, frg.VERT, frg.ROUGE, frg.VERT)
    code, rapport = frg.gate()
    assert (code, rapport["verdict"]) == (1, "NO-GO")


def test_un_illisible_ne_passe_JAMAIS_pour_un_succes(monkeypatch):
    """La propriete qui compte : ne pas avoir pu mesurer n'autorise rien."""
    _fige(monkeypatch, frg.VERT, frg.ILLISIBLE, frg.VERT)
    code, rapport = frg.gate()
    assert code == 2 and rapport["verdict"] == "INDETERMINE"
    assert code != 0, "un controle non mesure a produit une autorisation"


def test_rouge_prime_sur_illisible(monkeypatch):
    """Un defaut PROUVE est plus fort qu'un doute : le verdict doit le nommer."""
    _fige(monkeypatch, frg.ILLISIBLE, frg.ROUGE)
    code, rapport = frg.gate()
    assert (code, rapport["verdict"]) == (1, "NO-GO")


def test_un_controle_qui_explose_devient_INDETERMINE_pas_vert(monkeypatch):
    """Un controle qui leve ne doit jamais etre compte comme reussi."""
    def _explose():
        raise RuntimeError("sonde cassee")

    monkeypatch.setattr(frg, "CONTROLES", [("boum", _explose)])
    code, rapport = frg.gate()
    assert code == 2
    assert rapport["controles"][0]["etat"] == frg.ILLISIBLE
    assert "RuntimeError" in rapport["controles"][0]["detail"]


def test_syntaxe_voit_le_depot_reel():
    """Le controle de syntaxe doit MESURER, pas rendre un vert de complaisance."""
    etat, detail = frg.ctrl_syntaxe()
    assert etat in (frg.VERT, frg.ROUGE, frg.ILLISIBLE)
    assert any(car.isdigit() for car in detail), "aucun compte rendu : mesure absente"


def test_filet_clonable_est_un_controle_du_gate():
    """La gouvernance qui survit au clone fait partie des conditions de release."""
    assert "filet clonable" in [nom for nom, _ in frg.CONTROLES]


def test_un_module_hors_git_est_un_travail_dans_le_vide(monkeypatch):
    """Mesure 2026-08-29 : le pipeline de consolidation historique existait sur
    le disque sans etre suivi par git -- donc invisible pour tout autre poste,
    jamais joue par la CI, et refuse par trusted_script (« privilege = code
    revu »). Le gate doit le voir."""
    monkeypatch.setattr(frg, "_git",
                        lambda *a, **k: (0, "?? tools/fantome.py", ""))
    etat, detail = frg.ctrl_modules_versionnes()
    assert etat == frg.ROUGE and "fantome.py" in detail


def test_arbre_sans_module_orphelin_est_vert(monkeypatch):
    monkeypatch.setattr(frg, "_git", lambda *a, **k: (0, "", ""))
    assert frg.ctrl_modules_versionnes()[0] == frg.VERT


def test_git_muet_ne_certifie_rien(monkeypatch):
    """Ne pas pouvoir demander a git n'autorise pas a conclure que tout est suivi."""
    monkeypatch.setattr(frg, "_git", lambda *a, **k: (128, "", "boom"))
    assert frg.ctrl_modules_versionnes()[0] == frg.ILLISIBLE


def test_les_branches_jugees_sont_celles_du_MIROIR(tmp_path, monkeypatch):
    """Incoherence corrigee le 2026-08-29 : le controle jugeait les branches de
    l'ATELIER (review/*, hackathon/*...) alors que la strategie publie un MIROIR.
    Un gate qui controle autre chose que ce qu'on publie ne controle rien."""
    faux = tmp_path / "miroir"
    (faux / ".git").mkdir(parents=True)
    monkeypatch.setattr(frg, "_miroir", lambda: faux)
    monkeypatch.setattr(frg, "_git", lambda *a, **k: (0, "alpha", ""))
    etat, detail = frg.ctrl_branches_exposees()
    assert etat == frg.VERT and "miroir" in detail


def test_miroir_perime_BLOQUE(tmp_path, monkeypatch):
    """« Ne jamais publier sur la foi d'une verification ancienne » etait une
    regle ecrite, donc suspendue a la vigilance de qui publie. Elle est mesuree."""
    faux = tmp_path / "miroir"
    (faux / ".git").mkdir(parents=True)
    (faux / ".git" / "nokido_source_sha").write_text("a" * 40, encoding="utf-8")
    monkeypatch.setattr(frg, "_miroir", lambda: faux)
    monkeypatch.setattr(frg, "_git", lambda *a, **k: (0, "b" * 40, ""))
    etat, detail = frg.ctrl_miroir_a_jour()
    assert etat == frg.ROUGE and "REGENERER" in detail.upper()


def test_miroir_a_jour_passe(tmp_path, monkeypatch):
    faux = tmp_path / "miroir"
    (faux / ".git").mkdir(parents=True)
    (faux / ".git" / "nokido_source_sha").write_text("c" * 40, encoding="utf-8")
    monkeypatch.setattr(frg, "_miroir", lambda: faux)
    monkeypatch.setattr(frg, "_git", lambda *a, **k: (0, "c" * 40, ""))
    assert frg.ctrl_miroir_a_jour()[0] == frg.VERT


def test_absence_de_miroir_bloque_l_ouverture(monkeypatch):
    monkeypatch.setattr(frg, "_miroir", lambda: None)
    assert frg.ctrl_miroir_a_jour()[0] == frg.ROUGE


def _rapport_ui(tmp_path, monkeypatch, contenu, age_h=0.0):
    import json as _j
    import os
    import time as _t
    # PERIMETRE par defaut = celui du contrat COURANT (2026-08-30). Le controle
    # verifie desormais que le rapport couvre TOUTES les routes declarees, pas
    # seulement qu'il est frais : un rapport peut etre recent ET incomplet. On le
    # lit par `frg._routes_du_contrat()` plutot qu'en dur, sinon chaque route
    # ajoutee a la campagne casserait ces tests sans rien dire du gate.
    contenu = dict(contenu)
    contenu.setdefault("couverture_clics",
                       {"routes_enumerees": frg._routes_du_contrat()})
    p = tmp_path / "report.json"
    p.write_text(_j.dumps(contenu), encoding="utf-8")
    if age_h:
        vieux = _t.time() - age_h * 3600
        os.utime(p, (vieux, vieux))
    monkeypatch.setattr(frg, "_RAPPORT_UI", p)
    return p


def test_parcours_ui_conforme_et_recent_passe(tmp_path, monkeypatch):
    _rapport_ui(tmp_path, monkeypatch,
                {"verdict": "CONFORME", "route_en_cause": [], "routes_non_jugees": []})
    assert frg.ctrl_parcours_ui()[0] == frg.VERT


def test_parcours_ui_viole_bloque(tmp_path, monkeypatch):
    _rapport_ui(tmp_path, monkeypatch,
                {"verdict": "VIOLE", "route_en_cause": ["/forge/debate"],
                 "routes_non_jugees": []})
    etat, detail = frg.ctrl_parcours_ui()
    assert etat == frg.ROUGE and "debate" in detail


def test_route_non_jugee_n_est_pas_un_succes(tmp_path, monkeypatch):
    """« Pas pu juger » n'est pas « conforme » : distinction deja acquise par la
    campagne le 2026-08-12, le gate ne doit pas l'ecraser."""
    _rapport_ui(tmp_path, monkeypatch,
                {"verdict": "CONFORME", "route_en_cause": [],
                 "routes_non_jugees": ["/vitals"]})
    assert frg.ctrl_parcours_ui()[0] == frg.ILLISIBLE


def test_contrat_ui_perime_ne_vaut_pas_preuve(tmp_path, monkeypatch):
    """Un parcours vert d'avant-hier ne dit rien du HEAD : meme regle que le miroir."""
    _rapport_ui(tmp_path, monkeypatch,
                {"verdict": "CONFORME", "route_en_cause": [], "routes_non_jugees": []},
                age_h=72.0)
    etat, detail = frg.ctrl_parcours_ui()
    assert etat == frg.ILLISIBLE and "rejouer" in detail.lower()


def test_campagne_jamais_jouee_bloque(tmp_path, monkeypatch):
    monkeypatch.setattr(frg, "_RAPPORT_UI", tmp_path / "absent.json")
    assert frg.ctrl_parcours_ui()[0] == frg.ROUGE


def test_ouvrir_n_est_pas_livrer(monkeypatch):
    """OUVRIR le depot est irreversible ; livrer ne l'est pas. Les conditions
    d'exposition ne doivent donc s'ajouter QUE sous --public, sinon le gate
    serait rouge en permanence pour de simples releases internes."""
    monkeypatch.setattr(frg, "CONTROLES", [("c", lambda: (frg.VERT, "fixe"))])
    monkeypatch.setattr(frg, "CONTROLES_PUBLICS", [("expo", lambda: (frg.ROUGE, "fixe"))])
    assert frg.gate(public=False)[0] == 0
    assert frg.gate(public=True)[0] == 1


def test_checklist_une_case_ouverte_refuse_l_ouverture(monkeypatch, tmp_path):
    """Une condition d'ouverture non tenue interdit d'ouvrir : la checklist est
    une CONDITION, pas un document d'intention."""
    f = tmp_path / "c.md"
    f.write_text("## %s\n- [x] fait\n- [ ] scan secrets historique\n" % frg._SECTION_P0,
                 encoding="utf-8")
    monkeypatch.setattr(frg, "_CHECKLIST", f)
    etat, detail = frg.ctrl_checklist_publique()
    assert etat == frg.ROUGE and "scan secrets" in detail


def test_checklist_tout_coche_autorise(monkeypatch, tmp_path):
    f = tmp_path / "c.md"
    f.write_text("## %s\n- [x] fait\n- [x] aussi\n" % frg._SECTION_P0, encoding="utf-8")
    monkeypatch.setattr(frg, "_CHECKLIST", f)
    assert frg.ctrl_checklist_publique()[0] == frg.VERT


def test_checklist_absente_est_illisible_pas_verte(monkeypatch, tmp_path):
    """Ne pas trouver les conditions d'ouverture n'autorise pas a ouvrir."""
    monkeypatch.setattr(frg, "_CHECKLIST", tmp_path / "inexistante.md")
    assert frg.ctrl_checklist_publique()[0] == frg.ILLISIBLE
