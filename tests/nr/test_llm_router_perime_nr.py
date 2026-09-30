"""NR — le routeur ne sert plus ce qui n'existe plus.

Motif, mesure le 2026-08-18 : les sept slots `github_*` avaient ete ajoutes en
avril avec la mention « 7 modeles testes OK ». GitHub a retire le backend
depuis (410 Gone sur le catalogue ET sur une inference reelle, avec un PAT
`models:read` valide). Personne ne l'a vu pendant quatre mois, pour une raison
precise : la CLE existait, donc `is_available()` rendait True, donc le slot
passait le preflight — et n'echouait qu'a l'appel. Sur seize chaines d'usage,
SEPT commencaient par un de ces slots.

Ce qu'on protege ici : qu'un slot marque perime ne soit plus JAMAIS servi, et
qu'aucune chaine ne cite un slot qui n'existe pas — le garde qui aurait attrape
le probleme des avril.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_llm_router as R  # noqa: E402

PERIMES = {n for n, f in R.PROVIDERS.items() if f.get("perime")}


def test_les_sept_slots_github_sont_marques_perimes():
    """Anti-resurrection : les redeclarer vivants doit etre un geste EXPLICITE."""
    attendus = {"github_gpt41_mini", "github_gpt4o_mini", "github_llama_70b",
                "github_phi4_mini", "github_deepseek_v3", "github_codestral",
                "github_cohere_rp"}
    assert attendus <= PERIMES, attendus - PERIMES


def test_aucune_chaine_active_ne_sert_un_slot_perime():
    for use_case in R.USE_CASE_CHAINS:
        servis = set(R.chaine_active(use_case))
        assert not (servis & PERIMES), f"{use_case} sert encore {servis & PERIMES}"


def test_aucune_chaine_ne_cite_un_slot_inexistant():
    """Une chaine qui nomme un slot absent de PROVIDERS route vers le vide."""
    for use_case, chaine in R.USE_CASE_CHAINS.items():
        fantomes = [s for s in chaine if s not in R.PROVIDERS]
        assert not fantomes, f"{use_case} cite {fantomes}"


def test_aucune_chaine_active_n_est_vide():
    for use_case in R.USE_CASE_CHAINS:
        assert R.chaine_active(use_case), f"{use_case} n'a plus aucun candidat"


def test_le_filtre_preserve_l_ordre_de_priorite():
    """L'ordre EST la priorite : le filtre retire, il ne reordonne pas."""
    for use_case, chaine in R.USE_CASE_CHAINS.items():
        attendu = [s for s in chaine if s not in PERIMES]
        if attendu:
            assert R.chaine_active(use_case) == attendu


def test_un_use_case_inconnu_retombe_sur_general_filtre():
    assert R.chaine_active("ce_cas_n_existe_pas") == R.chaine_active("general")


def test_une_chaine_entierement_perimee_rend_un_fallback_local(monkeypatch):
    """Rendre une liste vide laisserait le routeur sans candidat du tout."""
    monkeypatch.setitem(R.USE_CASE_CHAINS, "_essai_tout_perime", ["github_gpt41_mini",
                                                                 "github_gpt4o_mini"])
    obtenu = R.chaine_active("_essai_tout_perime")
    assert obtenu, "un fallback local doit rester"
    assert not set(obtenu) & PERIMES


# ── chaines recablees sur mesure (2026-08-18) ───────────────────────────────

ORCHESTRATION = ("orchestration", "tool_call")


def test_l_orchestration_n_appelle_que_des_slots_qui_appellent():
    """L'invariant le plus cher de la journee. Un modele qui IGNORE l'outil
    repond une phrase polie : la chaine echoue EN SILENCE. Mesure du 18/08 :
    `qwen3.6-35b` ANNONCE `tools` et ne les honore pas, `allam-2-7b` les refuse
    (HTTP 400) — et c'etait le plus rapide du parc, donc le candidat naturel."""
    for use_case in ORCHESTRATION:
        for slot in R.chaine_active(use_case):
            fiche = R.PROVIDERS.get(slot) or {}
            assert fiche.get("outils") is True, (
                f"{use_case} contient {slot}, dont `outils` vaut "
                f"{fiche.get('outils')!r} — mesurer avant de router")


def test_les_slots_mesures_portent_leur_date():
    """Une mesure sans date se perime en silence : les catalogues bougent."""
    for nom, fiche in R.PROVIDERS.items():
        if "outils" in fiche:
            assert fiche.get("mesure"), f"{nom} annonce `outils` sans date de mesure"


def test_allam_le_plus_rapide_reste_hors_orchestration():
    """572 tok/s, 0,15 s — et un refus explicite des outils. La vitesse ne
    rachete pas une capacite absente."""
    assert R.PROVIDERS["groq_allam"]["outils"] is False
    for use_case in ORCHESTRATION:
        assert "groq_allam" not in R.chaine_active(use_case)


def test_le_seul_grand_contexte_sert_les_chaines_de_contexte():
    """262 144 tokens : `qwen3.6-35b` est le seul du parc a cette echelle."""
    for use_case in ("context", "synthesis"):
        assert R.chaine_active(use_case)[0] == "openrouter_qwen_coder"


def test_la_chaine_eu_ne_sort_pas_d_europe_ni_du_local():
    """Souverainete : Mistral et local uniquement, aucun autre fournisseur."""
    autorises = {"mistral_small", "mistral_large", "lmstudio_native",
                 "ollama_local", "llamacpp_local"}
    assert set(R.chaine_active("eu")) <= autorises


def test_le_code_commence_en_local():
    """Le code source ne sort pas vers un tiers tant qu'un local repond."""
    assert R.chaine_active("code")[0] == "lmstudio_native"


def test_chaque_chaine_finit_par_un_repli_local():
    """Le dernier maillon doit etre sans quota : sinon une journee de saturation
    cloud laisse Nokido sans aucune reponse."""
    locaux = {"ollama_local", "llamacpp_local", "lmstudio_native"}
    for use_case in R.USE_CASE_CHAINS:
        chaine = R.chaine_active(use_case)
        assert set(chaine) & locaux, f"{use_case} n'a aucun repli local"


# ── la sonde qui a revele tout ca ────────────────────────────────────────────

def test_la_sonde_lit_la_table_du_routeur_pas_une_copie():
    """Une seconde table de slots finirait par diverger de celle qui sert."""
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_router_slots_probe as S

    assert set(S.slots_routeur()) == set(R.PROVIDERS)


def test_un_slot_sans_runtime_est_NON_MESURE_pas_MORT():
    """Confondre « je n'ai pas su demander » et « c'est mort » a fabrique 21 faux
    morts le 2026-08-11. La sonde doit rendre une correspondance VIDE, que
    l'appelant traduit en NON_MESURE."""
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_router_slots_probe as S

    assert S.correspondance("slot_qui_n_existe_nulle_part", {}) == ""


def test_la_correspondance_trouve_le_runtime_exact_puis_la_famille():
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_router_slots_probe as S

    assert S.correspondance("groq_fast", {"groq_fast": object()}) == "groq_fast"
    assert S.correspondance("groq_fast", {"groq": object()}) == "groq"


def test_un_preflight_qui_leve_ne_fait_pas_tomber_la_passe():
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_router_slots_probe as S

    class _Explose:
        def is_available(self):
            raise RuntimeError("boom")

    pret, motif = S._preflight(_Explose())
    assert pret is False and "RuntimeError" in motif


def test_un_preflight_negatif_rapporte_le_motif():
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_router_slots_probe as S

    class _Ferme:
        def is_available(self):
            return False

        def unavailable_reason(self):
            return "cle GROQ_API_KEY ECARTEE par la rotation"

    pret, motif = S._preflight(_Ferme())
    assert pret is False and "ECARTEE" in motif


def test_un_slot_marque_perime_disparait_des_chaines(monkeypatch):
    """Le marqueur AGIT — sans quoi il ne serait qu'un commentaire decoratif."""
    vivant = next(n for n in R.chaine_active("general") if n not in PERIMES)
    avant = R.chaine_active("general")
    assert vivant in avant
    monkeypatch.setitem(R.PROVIDERS, vivant, {**R.PROVIDERS[vivant], "perime": "essai"})
    assert vivant not in R.chaine_active("general")
