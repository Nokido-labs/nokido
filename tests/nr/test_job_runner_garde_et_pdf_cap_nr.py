# -*- coding: utf-8 -*-
"""NR - deux gardes de forme du 2026-09-05 (job_18467ae0f9a1).

1. Le wrapper genere par forge_job_runner tuait bien un job hors cap RSS, puis
   `open(_err, 'a')` levait PermissionError (le .err est le stderr HERITE du hub)
   AVANT l'ecriture du .rc ; `_tue = True` interdisait au principal de le
   reecrire -> job 'running' a vie, lane jamais relachee, motif perdu. Contrat :
   dans le TEMPLATE, chaque `'137'` precede son message, aucun `open(_err` hors
   de `_dire`, et `_dire` n'a aucun chemin qui leve.
2. Le tier PDF du crawler n'avait aucune borne de taille : un PDF biorxiv a fait
   depasser 6 Go au job. Contrat : au-dessus de LAFORGE_CRAWL_PDF_MAX_MB, retour
   vide + avertissement, SANS importer le convertisseur.
"""
from __future__ import annotations

import logging
import re
import sys
import types
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (code appele, job detache)
#   (l.109)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))


def _src(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        pytest.skip(f"{rel} absent")
    return p.read_text(encoding="utf-8", errors="replace")


def test_le_rc_est_ecrit_avant_le_kill_dans_les_deux_gardes():
    """Contrat d'origine (2026-09-05) : un message qui echoue ne laisse jamais le job 'running' a
    vie. Il tient desormais par `_dire` qui ne leve jamais (test_aucune_ouverture_du_err_hors_de_dire).

    Ordre REALIGNE le 2026-10-02 (CI de reference 479480200) sur celui de M4 : message, puis .rc,
    puis kill de l'arbre. L'ancien ordre (kill, .rc, message) portait une course : le garde est un
    thread DAEMON ; le kill reveille `rc = _p.wait()`, le principal voit `_tue` et sort sans ecrire,
    et le wrapper meurt avec son daemon AVANT le .rc -> job 'running' a vie, l'echec meme que ce NR
    devait empecher. Le message precede le .rc : qui lit le .rc trouve le motif dans le journal.
    """
    src = _src("app/forge_job_runner.py")
    for motif in ("boucle probable", "fuite memoire"):
        i_msg = src.find(motif)
        assert i_msg > 0, f"message '{motif}' introuvable dans le template"
        i_rc = src.find("open(_rc, 'w').write('137')", i_msg)
        i_enf = src.find("_tuer_enfants()", i_rc)
        i_kill = src.find("_p.kill()", i_enf)
        assert 0 < i_msg < i_rc < i_enf < i_kill, (motif, i_msg, i_rc, i_enf, i_kill)
        assert i_kill - i_msg < 600, (
            f"'{motif}' : le .rc et le kill doivent appartenir au MEME garde que le message"
        )


def test_le_garde_tue_l_arbre_et_pas_seulement_le_wrapper():
    """Un garde qui tue le wrapper et laisse le gourmand vivant ne borne RIEN.

    Mesure 2026-09-13 : la CI de reference est tuee par le garde RSS (rc 137
    ecrit, job declare mort) et le pytest du lot pur, PETIT-ENFANT du wrapper,
    survit avec 8,6 Go -- identifie par son AGE (839 s quand le run isole venait
    d'etre lance). `Popen.kill()` ne tue que LE process vise : sous Windows les
    descendants ne recoivent rien. Le job est donc compte mort pendant que sa
    memoire reste prise, et le run suivant demarre sur une machine deja chargee.

    Contrat : dans le TEMPLATE, chaque kill de garde arrete les ENFANTS avant le
    wrapper -- meme doctrine que `forge_job_stop._arreter_arbre` (children puis
    parent), qui porte deja cette regle pour l'arret manuel.
    """
    src = _src("app/forge_job_runner.py")
    assert "_tuer_enfants" in src, (
        "le template ne tue que le wrapper : un sous-process gourmand survit au "
        "kill, avec sa memoire, alors que le job est declare mort"
    )
    for motif in ("boucle probable", "fuite memoire"):
        i_msg = src.find(motif)
        assert i_msg > 0, f"message '{motif}' introuvable dans le template"
        # Le kill SUIT le message dans le garde (ordre sans course, 2026-10-02). L'ancienne lecture
        # (rfind avant le message) rendait -1 pour le premier garde et passait A VIDE.
        i_enf = src.find("_tuer_enfants()", i_msg)
        i_kill = src.find("_p.kill()", i_enf)
        assert 0 < i_enf < i_kill and i_kill - i_msg < 600, (
            f"'{motif}' : aucun _tuer_enfants() avant le kill du wrapper", i_msg, i_enf, i_kill
        )
        assert i_kill - i_enf < 400, (
            f"'{motif}' : _tuer_enfants() doit preceder IMMEDIATEMENT le kill du "
            "wrapper, sinon les descendants sont reparentes et deviennent "
            "introuvables"
        )


def test_le_wrapper_reellement_genere_compile(tmp_path, monkeypatch):
    """Le template est une CHAINE : aucun interpreteur ne le relit avant un job.

    Les tests de forme ci-dessus lisent la SOURCE. Ils resteraient verts avec un
    template qui ne compile pas -- et un template casse ne casse pas un job, il
    les casse TOUS. Ce cas-ci emprunte donc le chemin reel : `launch_job` ecrit
    `<job>_wrap.py` AVANT de tenter le spawn, donc le fichier existe meme si le
    spawn echoue (compte non privilegie en CI). On le compile, et on verifie que
    le kill d'arbre y figure : la mesure porte sur ce qui tournera, pas sur ce
    qu'on a ecrit.
    """
    try:
        import forge_job_runner as fjr
    except Exception as exc:  # pragma: no cover - depend de l'env
        pytest.skip(f"forge_job_runner non importable ({type(exc).__name__})")

    monkeypatch.setattr(fjr, "JOBS_DIR", tmp_path, raising=False)

    # `launch_job` n'accepte qu'un .py sous C:/tmp ou la racine Nokido : un
    # tmp_path ne passerait pas le controle de chemin, et c'est voulu.
    bac = Path("C:/tmp")
    if not bac.is_dir():
        pytest.skip("C:/tmp absent : chemin autorise indisponible")
    cible = bac / "nr_cible_wrapper_compile.py"
    cible.write_text("print('nr')\n", encoding="utf-8")

    fjr.launch_job(str(cible), rss_cap_mb=4321)

    wrappers = list(tmp_path.glob("*_wrap.py"))
    assert wrappers, "launch_job n'a ecrit aucun wrapper : chemin reel non emprunte"
    texte = wrappers[0].read_text(encoding="utf-8")

    compile(texte, str(wrappers[0]), "exec")  # leve SyntaxError si le template est casse

    assert "def _tuer_enfants():" in texte, "le wrapper genere ne sait pas tuer l'arbre"
    assert "RSS_CAP = 4321" in texte, "le cap explicite n'atteint pas le wrapper"
    for garde in ("LOG_CAP:", "if _rss > RSS_CAP:"):
        i = texte.find(garde)
        assert i > 0, f"garde '{garde}' absent du wrapper genere"
        # Fenetre = le garde lui-meme (cause, message, .rc, kill) : l'ancienne fenetre de 200
        # caracteres rendait -1 < -1 des que le kill s'eloignait -- et passait si _tuer_enfants
        # manquait. Les deux doivent etre TROUVES, dans le garde, enfants d'abord.
        i_rc = texte.find("write('137')", i)
        i_enf = texte.find("_tuer_enfants()", i)
        i_kill = texte.find("_p.kill()", i)
        assert 0 < i_rc < i_enf < i_kill and i_kill - i < 700, (
            f"'{garde}' : .rc, puis les enfants, puis le wrapper", i, i_rc, i_enf, i_kill
        )


def test_aucune_ouverture_du_err_hors_de_dire():
    src = _src("app/forge_job_runner.py")
    i_dire = src.find('"def _dire(_m):')
    assert i_dire > 0, "_dire absente du template"
    i_guard = src.find('"def _guard():')
    corps_guard = src[i_guard:]
    assert "open(_err, 'a'" not in corps_guard, (
        "le garde ouvre encore le .err par chemin : PermissionError possible, garde mort"
    )
    bloc_dire = src[i_dire:i_guard]
    assert "except Exception" in bloc_dire and "pass" in bloc_dire, "_dire doit ne jamais lever"
    assert "_s.stderr.write" in bloc_dire, "_dire doit passer par le stderr herite d'abord"


def test_un_pdf_au_dessus_du_cap_est_refuse_sans_charger_le_convertisseur(monkeypatch, caplog):
    ct = pytest.importorskip("forge_crawl_tool")
    monkeypatch.setenv("LAFORGE_CRAWL_PDF_MAX_MB", "1")
    piege = types.ModuleType("forge_rag_store")

    class _Boom:
        @staticmethod
        def convert(_p):
            raise AssertionError("le convertisseur ne doit PAS etre appele au-dessus du cap")

    piege.MarkerConverter = _Boom
    monkeypatch.setitem(sys.modules, "forge_rag_store", piege)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_rag_store", piege)
    raw = b"%PDF-1.4" + b"0" * (2 * 1024 * 1024)
    with caplog.at_level(logging.WARNING):
        out = ct._pdf_bytes_to_markdown(raw, "https://x/y.pdf")
    assert out == ""
    assert any("cap" in r.getMessage() and "NON extrait" in r.getMessage() for r in caplog.records), \
        "le refus doit etre DIT dans le journal"


def test_un_pdf_sous_le_cap_passe_au_convertisseur(monkeypatch):
    ct = pytest.importorskip("forge_crawl_tool")
    monkeypatch.setenv("LAFORGE_CRAWL_PDF_MAX_MB", "1")
    faux = types.ModuleType("forge_rag_store")

    class _Conv:
        @staticmethod
        def convert(_p):
            return "# titre\ncorps", {}

    faux.MarkerConverter = _Conv
    monkeypatch.setitem(sys.modules, "forge_rag_store", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_rag_store", faux)
    out = ct._pdf_bytes_to_markdown(b"%PDF-1.4 petit", "https://x/z.pdf")
    assert "corps" in out


def test_le_cap_pdf_est_reglable_par_env():
    src = _src("app/forge_crawl_tool.py")
    assert re.search(r'environ\.get\("LAFORGE_CRAWL_PDF_MAX_MB"', src)
