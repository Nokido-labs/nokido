"""NR du 27/10 : trois defauts de qualite de la veille, mesures sur 3 veilles terminees (4 sources utiles sur 15).

1. Le crawl prenait arxiv.org/abs/ = le RESUME seul (1 chunk par source) : tenter /html/ (texte complet) d'abord.
2. Le veto d'ancrage PLAFONNAIT a 5.0 alors que le seuil d'ingestion est 4.0 : le hors-sujet passait quand meme
   (une etude sur l'energie des PME nigerianes, ancree par le seul mot « stochastic »). Plafond sous le seuil et
   au moins 2 ancres quand le theme en fournit plusieurs.
3. Les veilles partaient par ordre ALPHABETIQUE d'identifiant, pas dans leur ordre d'arrivee.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import forge_chain_executor as CE  # noqa: E402


def test_crawl_complet_prend_le_html_arxiv():
    vus = []

    def faux(url, t):
        vus.append(url)
        return {"text": "x" * 5000 if "/html/" in url else "resume court"}
    det = CE._crawl_complet("https://arxiv.org/abs/2307.09564v2", faux, 15)
    assert vus[0] == "https://arxiv.org/html/2307.09564v2" and len(det["text"]) == 5000
    assert det["url_crawlee"].endswith("/html/2307.09564v2")


def test_crawl_complet_repli_sur_abs_si_html_vide():
    det = CE._crawl_complet("https://arxiv.org/abs/1211.0557v1",
                            lambda u, t: {"text": "" if "/html/" in u else "resume"}, 15)
    assert det["text"] == "resume"


def test_crawl_complet_url_ordinaire_inchangee():
    vus = []
    CE._crawl_complet("https://example.org/a", lambda u, t: vus.append(u) or {"text": "t"}, 15)
    assert vus == ["https://example.org/a"]


def test_plafond_ancrage_sous_le_seuil_et_deux_ancres():
    ancres = ["stoke", "stochastic", "superoptimization", "mcmc"]
    # une seule ancre generique : plafonne SOUS le seuil d'ingestion (4.0)
    assert CE._plafond_ancrage(8.0, "a stochastic optimization framework for msme energy", ancres) < 4.0
    # deux ancres : rien ne change
    assert CE._plafond_ancrage(8.0, "stochastic superoptimization with mcmc", ancres) == 8.0
    # theme a une seule ancre : une suffit
    assert CE._plafond_ancrage(7.0, "egglog rewrites", ["egglog"]) == 7.0


def test_veilles_dans_l_ordre_d_arrivee(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.execute("create table agent_chain_nodes (chain_id text, status text)")
    ex = object.__new__(CE.ChainExecutor)

    class _C:
        def execute(self, *a):
            return db.execute(*a)

        def close(self):
            pass
    ex._get_conn = lambda: _C()
    monkeypatch.setenv("LAFORGE_VEILLES_MAX", "1")
    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: False)
    by = {"wj_aaa": [{"created_at": "2026-10-27T14:35"}], "wj_zzz": [{"created_at": "2026-10-27T14:32"}]}
    assert set(ex._etaler_veilles(by)) == {"wj_zzz"}  # la plus ANCIENNE part, pas la premiere alphabetique


def test_ancre_par_mot_entier_pas_par_sous_chaine():
    # 27/10 : « Gamba: Marry Gaussian Splatting with Mamba » (reconstruction 3D) ingere dans la veille MBA :
    # « gamba » (homonyme de l'outil GAMBA) + « mba » trouve DANS « Mamba » = 2 ancres par sous-chaine.
    hay = "gamba: marry gaussian splatting with mamba for single view 3d reconstruction"
    assert CE._plafond_ancrage(8.0, hay, ["mba", "gamba", "simba"]) == 3.0
    assert CE._plafond_ancrage(8.0, "simplifying mba expressions, gamba and simba", ["mba", "gamba"]) == 8.0


def test_habillage_arxiv_html_retire():
    corps = "# Vrai Titre\nAbstract. Le contenu utile.\n## 1 Introduction\nTexte."
    brut = ("[Skip to main content](https://arxiv.org/html/1#infobox)\n##### Report GitHub Issue\n"
            "  1. [Abstract.](https://arxiv.org/html/1#abstract1 \"In Vrai Titre\")\n" + corps +
            "\nWe gratefully acknowledge support from our [**major funders**](https://info.arxiv.org/x)\n[About]")
    det = CE._crawl_complet("https://arxiv.org/abs/2604.17364", lambda u, t: {"text": brut + "x" * 3000
                            if "/html/" in u else "resume"}, 15)
    assert det["text"].startswith("# Vrai Titre")
    assert "gratefully acknowledge" not in det["text"] and "Report GitHub Issue" not in det["text"]
    assert det.get("habillage_retire", 0) > 0  # une borne dit COMBIEN elle retire


def test_cle_url_dedoublonne_schema_et_version_arxiv():
    # 27/10 : le meme article crawle deux fois (http:// et https://, Alive-Infer, SCIP 9.0) -> morceaux en double.
    k = CE._cle_url
    assert k("http://arxiv.org/abs/1611.05980v3") == k("https://arxiv.org/abs/1611.05980v3")
    assert k("https://arxiv.org/abs/2402.17702v1") == k("https://arxiv.org/pdf/2402.17702v2")
    assert k("https://www.example.org/doc/") == k("http://example.org/doc")
    assert k("https://arxiv.org/abs/2402.17702") != k("https://arxiv.org/abs/2402.17703")


def test_sans_titre_reconnaissable_rien_n_est_coupe():
    brut = "texte sans titre markdown " * 200
    assert CE._sans_habillage_arxiv(brut)[0] == brut
