"""NR — le registre des prerequis couvre TOUTE la surface declaree, et ne ment pas.

Trois defauts sont verrouilles ici, tous mesures le 2026-09-19 :

1. Le registre se PERIME. Il est ecrit a la main ; un service neuf apportant un
   binaire neuf le laisserait muet. `exes_non_couverts()` re-derive la surface
   depuis `services.toml` — la source qui fait autorite — et ce test echoue tant
   qu'un executable declare n'a pas d'entree.

2. `ABSENT` invente des pannes. La premiere sonde rendait `ABSENT` pour `deno` et
   `ollama`, qui TOURNAIENT : leur dossier vit hors ACL du compte de service.
   Un chemin qu'on n'a pas pu lire est `ILLISIBLE`.

3. Un booleen effacerait la distinction. Chaque ligne porte l'un des trois etats,
   jamais `True`/`False`.

Le test traverse aussi le CLI par son `main()`, pas seulement les fonctions :
`check()` peut passer pendant que `--check` meurt en `NameError`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app import forge_install_prerequis as P  # noqa: E402
from tools import nokido_doctor  # noqa: E402


def test_le_registre_couvre_tous_les_exes_declares():
    """Cliquet anti-peremption : aucun executable du TOML sans entree au registre."""
    trous = P.exes_non_couverts()
    assert trous == {}, (
        "des services declarent des executables qu'aucun prerequis ne couvre — "
        "ajouter une entree a PREREQUIS (ou a EXES_NON_TIERS si le depot le produit) : "
        + repr({k: v[:3] for k, v in trous.items()}))


def test_le_cliquet_mord_si_une_entree_disparait(monkeypatch):
    """Sans cette preuve, le test precedent pourrait etre vert par construction."""
    ampute = tuple(e for e in P.PREREQUIS if e["cle"] != "deno")
    monkeypatch.setattr(P, "PREREQUIS", ampute)
    trous = P.exes_non_couverts()
    assert "deno.exe" in trous, (
        "retirer l'entree `deno` doit faire ressortir deno.exe comme non couvert ; "
        "si ce n'est pas le cas, le cliquet ne mord pas et le test jumeau ne prouve rien")


def test_trois_etats_jamais_un_booleen():
    for ligne in P.verifier():
        assert ligne["etat"] in (P.PRESENT, P.ABSENT, P.ILLISIBLE), ligne
        assert not isinstance(ligne["etat"], bool), ligne
        assert ligne["detail"], "un etat sans motif n'est pas exploitable: %r" % (ligne,)


def test_chemin_illisible_n_est_pas_une_absence(monkeypatch, tmp_path):
    """Parent non listable => ILLISIBLE. C'est le faux negatif paye le 2026-09-19."""
    manquant = tmp_path / "nulle_part" / "outil.exe"

    vrai_iterdir = Path.iterdir

    def iterdir_refuse(self):
        if self.name == "nulle_part":
            raise PermissionError("ACL simulee")
        return vrai_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir_refuse)
    assert P._verdict_chemin(manquant) == P.ILLISIBLE

    # ... et le meme chemin, parent LISTABLE, doit rendre ABSENT : sans ce
    # contre-cas, une sonde qui rendrait ILLISIBLE partout passerait le test.
    monkeypatch.setattr(Path, "iterdir", vrai_iterdir)
    lisible = tmp_path / "absent.exe"
    assert P._verdict_chemin(lisible) == P.ABSENT
    lisible.write_text("x", encoding="utf-8")
    assert P._verdict_chemin(lisible) == P.PRESENT


def test_bilan_ne_range_pas_un_illisible_parmi_les_bloquants(monkeypatch):
    """Un doute se nomme `indetermine`, jamais `bloquant` : sinon on fabrique des pannes."""
    faux = [{"cle": "x", "niveau": P.ESSENTIEL, "etat": P.ILLISIBLE, "detail": "d",
             "capacite": "c", "absent_alors": "a", "install": "i"}]
    monkeypatch.setattr(P, "verifier", lambda inclure_optionnels=True: faux)
    monkeypatch.setattr(P, "verifier_modeles", lambda: [])
    b = P.bilan()
    assert b["bloquants"] == []
    assert b["indetermines_critiques"] == ["x"]


def test_les_prerequis_essentiels_du_toml_sont_au_registre():
    """Tout service marque `essential` doit avoir son prerequis nomme.

    Garde contre l'oubli inverse du cliquet : un service essentiel dont le
    binaire est deja couvert, mais dont la DEPENDANCE hors depot ne l'est pas
    (cas mesure : NokidoNetcfgMCP, cwd hors du depot).
    """
    cles = {e["cle"] for e in P.PREREQUIS}
    for attendu in ("deno", "ollama", "netcfg_agent", "python", "git"):
        assert attendu in cles, "prerequis critique absent du registre: " + attendu
    niveaux = {e["cle"]: e["niveau"] for e in P.PREREQUIS}
    assert niveaux["deno"] == P.ESSENTIEL
    assert niveaux["ollama"] == P.ESSENTIEL
    assert niveaux["netcfg_agent"] == P.ESSENTIEL


def test_chaque_entree_dit_ce_qui_s_eteint():
    """`absent_alors` nomme la capacite perdue. « ca ne marchera pas » n'aide personne."""
    for e in P.PREREQUIS:
        assert e.get("capacite"), e["cle"]
        assert e.get("absent_alors"), e["cle"]
        assert e.get("install"), e["cle"]
        assert e["niveau"] in (P.REQUIS, P.ESSENTIEL, P.OPTIONNEL), e["cle"]


def test_le_cli_traverse_et_rend_un_code(capsys):
    """Chemin REEL : `main()`, pas seulement les fonctions internes."""
    code = nokido_doctor.main(["--json"])
    assert code in (0, 1)
    sortie = capsys.readouterr().out
    assert '"bloquants"' in sortie
    assert '"indetermines_critiques"' in sortie

    code_txt = nokido_doctor.main([])
    assert code_txt in (0, 1)
    txt = capsys.readouterr().out
    assert "INSTALLE" in txt, "le rapport doit borner ce qu'il prouve"
    assert "nokido_ensure_service" in txt, "et renvoyer vers qui repond a DEMARRE"


def test_degradation_depuis_une_installation_par_paquet(monkeypatch):
    """La wheel ne contient pas `proxy_deno/` : le doctor doit le DIRE, pas mentir.

    C'est son cas d'usage principal — quelqu'un qui vient d'installer le paquet.
    Trois exigences : l'etat du TOML est rapporte ; l'inventaire LEVE au lieu de
    rendre un dictionnaire vide (un inventaire qui se tait n'est pas un
    inventaire vide) ; un prerequis dont on ne sait plus ou regarder devient
    `ILLISIBLE`, jamais `ABSENT`.
    """
    monkeypatch.setattr(P, "SERVICES_TOML", RACINE / "proxy_deno" / "core" / "_absent_.toml")
    monkeypatch.setattr(P, "_CACHE_VARS", None)

    assert P.etat_toml_services() == P.ABSENT

    with pytest.raises(FileNotFoundError):
        P.exes_declares_dans_services()

    b = P.bilan()
    assert b["toml_services"] == P.ABSENT
    assert "netcfg_agent" in b["indetermines_critiques"], (
        "sans la declaration, on ne sait pas OU chercher le depot voisin : "
        "c'est un indetermine, pas une absence")


def test_le_cli_et_le_test_ne_parlent_pas_forcement_au_meme_module():
    """Fait mesure le 2026-09-19, consigne pour que personne ne le re-paye.

    `app.forge_install_prerequis` et le module resolu par le CLI ne sont PAS la
    meme instance (le depot expose aussi un chemin `nokido_agent/` qui charge
    `app/` a plat). Substituer sur l'une laisse l'autre intacte : c'est le
    faux vert de [[deux_instances_du_meme_module_2026-09-10]]. Tout test visant
    le CLI doit donc patcher `nokido_doctor.P`, resolu a l'appel.
    """
    assert nokido_doctor.P.verifier is not None
    # On n'exige PAS l'identite (elle depend du chemin d'import) : on exige que
    # le test sache LEQUEL il patche.
    assert nokido_doctor.P.__name__.endswith("forge_install_prerequis")


def test_le_cli_survit_a_l_absence_du_toml(monkeypatch, capsys):
    """Chemin reel : l'entrypoint ne doit pas exploser hors du depot.

    Patche l'instance REELLEMENT utilisee par le CLI, pas celle importee ici.
    """
    cible = nokido_doctor.P
    monkeypatch.setattr(cible, "SERVICES_TOML", RACINE / "proxy_deno" / "core" / "_absent_.toml")
    monkeypatch.setattr(cible, "_CACHE_VARS", None)
    # Garde de morsure, pose AVANT toute assertion : une substitution qui rate
    # ne rend pas un faux vert, elle fait juger autre chose que ce qu'on croit.
    assert cible.etat_toml_services() == cible.ABSENT, (
        "la substitution n'a pas mordu : le CLI lit encore le vrai services.toml")
    code = nokido_doctor.main([])
    assert code in (0, 1)
    txt = capsys.readouterr().out
    assert "installation par paquet" in txt, (
        "le rapport doit avertir que, sans la declaration, un binaire hors PATH "
        "peut etre annonce absent a tort")


def test_le_registre_couvre_toutes_les_images_compose():
    """Deuxieme cliquet : une capacite peut arriver par une IMAGE, pas un binaire.

    Trouve le 2026-09-19 en relisant les sources declarantes : `searxng` et
    `crawl4ai` n'existent nulle part comme executable. Une surface derivee des
    seuls `cmd` du TOML les ratait entierement.
    """
    trous = P.images_non_couvertes()
    assert trous == {}, ("des fichiers compose declarent des images qu'aucune entree "
                         "ne documente : " + repr(trous))


def test_le_cliquet_images_mord(monkeypatch):
    ampute = tuple(t for t in P.IMAGES_DOCKER_ATTENDUES if "searxng" not in t[0])
    monkeypatch.setattr(P, "IMAGES_DOCKER_ATTENDUES", ampute)
    assert any("searxng" in k for k in P.images_non_couvertes()), (
        "retirer searxng doit le faire ressortir ; sinon le cliquet ne mord pas")


def test_inventaire_images_leve_s_il_ne_peut_pas_lire(monkeypatch):
    """Aucun compose lisible => INCONNU, jamais un dictionnaire vide."""
    monkeypatch.setattr(P, "COMPOSE_FICHIERS", ("docker/_absent_/nulle-part.yml",))
    with pytest.raises(FileNotFoundError):
        P.images_declarees_dans_compose()


def test_un_compose_illisible_n_est_pas_avale(monkeypatch, tmp_path):
    """Un fichier qui EXISTE et qu'on n'a pas lu doit rompre l'inventaire.

    Sinon une couverture partielle se lit comme une couverture complete, et le
    cliquet des images devient vert pour de mauvaises raisons. C'est le motif
    « ne jamais conclure d'une source qui se tait ».
    """
    # ⚠️ Refuser UN compose, pas tous. Premiere version : le filtre portait sur
    # `endswith("docker-compose.yml")` et attrapait donc TOUS les composes d'un
    # worktree detache, ou un seul existe. L'inventaire levait alors
    # « INCONNU » (aucun fichier lu) et non « PARTIEL », et le test echouait en
    # CI en passant en local. Le sujet du test est la couverture PARTIELLE : il
    # faut donc qu'au moins un fichier reste lisible.
    lisibles = [rel for rel in P.COMPOSE_FICHIERS if (RACINE / rel).exists()]
    if len(lisibles) < 2:
        pytest.skip("moins de deux composes lisibles ici (%s) : la couverture "
                    "PARTIELLE ne peut pas etre mise en scene" % lisibles)

    refuse = lisibles[0]
    vrai_read = Path.read_text

    def read_refuse(self, *a, **k):
        if str(self).replace("\\", "/").endswith(refuse):
            raise PermissionError("ACL simulee")
        return vrai_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", read_refuse)
    with pytest.raises(OSError) as exc:
        P.images_declarees_dans_compose()
    assert "PARTIEL" in str(exc.value), (
        "l'erreur doit nommer la couverture partielle, pas seulement echouer : %s"
        % exc.value)


def test_les_modeles_de_poids_sont_declares():
    """Les GGUF ne sont dans aucun paquet : leur absence doit etre DITE, pas subie."""
    assert P.MODELES_ATTENDUS, "aucun modele declare"
    for rel, usage in P.MODELES_ATTENDUS:
        assert rel.endswith(".gguf"), rel
        assert usage, rel
    for m in P.verifier_modeles():
        assert m["etat"] in (P.PRESENT, P.ABSENT, P.ILLISIBLE), m


# ── profils d'installation (decision owner du 2026-10-07) ────────────────────────────────────
def _ligne(cle, niveau, etat):
    return {"cle": cle, "niveau": niveau, "etat": etat, "detail": "d", "capacite": "c",
            "absent_alors": "a", "install": "i"}


def _machine_vierge_de_dev(monkeypatch, bge_present):
    """Le premier passage sur runner vierge : Ollama et netcfg absents, le reste du profil dev present."""
    faux = [_ligne("python", P.REQUIS, P.PRESENT), _ligne("git", P.REQUIS, P.PRESENT),
            _ligne("deno", P.ESSENTIEL, P.PRESENT), _ligne("llama_server", P.OPTIONNEL, P.PRESENT),
            _ligne("ollama", P.ESSENTIEL, P.ABSENT), _ligne("netcfg_agent", P.ESSENTIEL, P.ABSENT)]
    modeles = [{"cle": "data/llm_models/bge-m3-Q8_0.gguf", "usage": "embeddings :8099", "detail": "",
                "etat": P.PRESENT if bge_present else P.ABSENT},
               {"cle": "data/llm_models/bitnet_b1_58.gguf", "usage": "bitnet", "detail": "", "etat": P.ABSENT}]
    monkeypatch.setattr(P, "verifier", lambda inclure_optionnels=True: faux)
    monkeypatch.setattr(P, "verifier_modeles", lambda: modeles)


def test_profil_dev_ne_bloque_ni_sur_ollama_ni_sur_netcfg(monkeypatch):
    _machine_vierge_de_dev(monkeypatch, bge_present=True)
    b = P.bilan(profil="dev")
    assert b["profil"] == "dev" and b["bloquants"] == []
    assert {"ollama", "netcfg_agent"} <= {l["cle"] for l in b["lignes"] if l["etat"] == P.ABSENT}, (
        "le profil change ce qui BLOQUE, pas ce qui se voit")


def test_profil_dev_bloque_sans_le_modele_des_vecteurs_du_pack(monkeypatch):
    _machine_vierge_de_dev(monkeypatch, bge_present=False)
    assert P.bilan(profil="dev")["bloquants"] == ["modele:bge-m3-Q8_0.gguf"]


def test_profil_complet_garde_le_comportement_d_avant(monkeypatch):
    _machine_vierge_de_dev(monkeypatch, bge_present=True)
    assert P.bilan(profil="complet")["bloquants"] == ["ollama", "netcfg_agent"]
    assert P.bilan()["bloquants"] == ["ollama", "netcfg_agent"], "les autres appelants de bilan() restent en complet"


def test_chaque_modele_dit_ou_le_prendre_depuis_le_manifeste_epingle():
    lignes = {m["cle"].rsplit("/", 1)[-1]: m["telecharger"] for m in P.verifier_modeles()}
    assert "huggingface.co/gpustack/bge-m3-GGUF/resolve/" in lignes["bge-m3-Q8_0.gguf"]
    assert "950f4a8e5e19477a6d3c26d2f162233c20002c601f75e4b002e3239997821167" in lignes["bge-m3-Q8_0.gguf"]
    assert lignes["bitnet_b1_58.gguf"].startswith("NON EPINGLE"), "un modele non epingle n'a pas de lien invente"


def test_chaque_image_dit_comment_l_obtenir():
    assert P.commande_image("ollama/ollama:latest", "tierce") == "docker pull ollama/ollama:latest"
    assert P.commande_image("nokido:latest", "construite", {"nokido:latest": ["docker-compose.yml"]}) == (
        "docker compose -f docker-compose.yml build")
    assert P.commande_image("netcfg-agent-mcp:latest", "construite", {}).startswith("construite hors")


def _hote():
    try:
        from nokido_agent.app import forge_host_capabilities as H
    except ImportError:
        from app import forge_host_capabilities as H
    return H


def test_chaque_modele_suggere_est_epingle_et_permissif():
    import re
    H = _hote()
    assert H.CATALOGUE_SUGGESTIONS, "catalogue vide"
    for m in H.CATALOGUE_SUGGESTIONS:
        assert re.match(r"^https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/[^/]+\.gguf$", m["gguf"]), (
            "revision FIXE, jamais `main` : %s" % m["gguf"])
        assert re.fullmatch(r"[0-9a-f]{64}", m["sha256"]) and m["licence"] == "Apache-2.0"
        assert ":" in m["ollama"] and "/" in m["lmstudio"] and m["role"] in ("code", "chat")


def test_la_suggestion_suit_la_memoire_de_la_machine():
    H = _hote()
    s = H.suggerer_modeles({"effective_inference_ram_gb": 8})
    assert [m["nom"] for m in s["suggestions"]["code"]] == ["Qwen2.5-Coder 7B"]
    assert [m["nom"] for m in s["suggestions"]["chat"]] == ["Qwen3 8B", "Qwen3 4B"], "les plus gros qui tiennent d'abord"
    petite = H.suggerer_modeles({"effective_inference_ram_gb": 2})
    assert petite["trop_petite"] and petite["suggestions"] == {"code": [], "chat": []}


def test_le_cli_modeles_donne_les_trois_commandes(monkeypatch, capsys):
    H = _hote()
    faux = type("H", (), {"suggerer_modeles": staticmethod(lambda: H.suggerer_modeles({"effective_inference_ram_gb": 16}))})
    monkeypatch.setattr(nokido_doctor, "_capacites_hote", lambda: faux)
    assert nokido_doctor.main(["--modeles"]) == 0
    out = capsys.readouterr().out
    assert "ollama pull qwen2.5-coder:14b" in out and "lms get qwen/qwen2.5-coder-14b" in out
    assert "huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/" in out


def test_le_cli_choisit_le_profil_dev_par_defaut(monkeypatch, capsys):
    _machine_vierge_de_dev(monkeypatch, bge_present=True)
    cible = nokido_doctor.P
    monkeypatch.setattr(cible, "verifier", P.verifier)
    monkeypatch.setattr(cible, "verifier_modeles", P.verifier_modeles)
    assert nokido_doctor.main([]) == 0
    assert "PROFIL dev" in capsys.readouterr().out
    assert nokido_doctor.main(["--profil", "complet"]) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
