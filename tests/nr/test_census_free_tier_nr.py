"""NR — recensement du palier gratuit et scan HF.

Ce qu'on protege : la distinction entre TROIS choses qu'on confond en
permanence, et dont la confusion a coute la journee du 2026-08-18 —

  DECLARE   le catalogue liste le modele
  GRATUIT   le fournisseur ANNONCE un prix nul
  JOIGNABLE une completion a REPONDU

Compter « payant » un modele dont le prix n'est pas publie donnerait un chiffre
faux ; compter « gratuit » un modele sature (429) aussi. Et un champ `is_free`
present dans un JSON ne prouve rien tant qu'aucun appel n'a abouti.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_free_tier_census as C  # noqa: E402
import forge_hf_free_scan as H  # noqa: E402


# ── gratuite : annoncee, ou inconnue — jamais supposee ───────────────────────

def test_un_prix_nul_est_gratuit():
    assert C.est_gratuit({"id": "x", "pricing": {"prompt": "0", "completion": "0"}}, "openrouter") is True


def test_un_suffixe_free_est_gratuit():
    assert C.est_gratuit({"id": "nvidia/nemotron:free"}, "openrouter") is True


def test_un_prix_non_nul_n_est_pas_gratuit():
    assert C.est_gratuit({"id": "x", "pricing": {"prompt": "0.002", "completion": "0"}}, "openrouter") is False


def test_un_prix_NON_PUBLIE_rend_None_pas_False():
    """Le porter en « payant » donnerait un chiffre faux : 158 modeles deepinfra
    et 130 HF ne publient aucun prix."""
    assert C.est_gratuit({"id": "mistral-small"}, "mistral") is None


def test_un_local_est_toujours_gratuit():
    for local in ("ollama", "lmstudio", "litellm"):
        assert C.est_gratuit({"id": "qwen"}, local) is True


# ── echantillonnage : le plus petit prouve le mieux ──────────────────────────

def test_la_taille_est_lue_dans_le_nom():
    assert C._taille("qwen2.5-coder:1.5b") == 1.5
    assert C._taille("Meta-Llama-3.1-405B-Instruct") == 405.0
    assert C._taille("modele-sans-taille") == 999.0


def test_le_plus_petit_modele_passe_devant():
    """Un 7B a froid ne repond pas en 240 s ; un 1.5B repond en 4 s. On cherche
    une preuve de VIE, pas un banc d'essai."""
    tries = sorted(["a-70b", "b-1.5b", "c-14b"], key=C._taille)
    assert tries[0] == "b-1.5b"


# ── comparaison de passes : le coeur de l'adaptation ─────────────────────────

def test_la_premiere_passe_le_dit_au_lieu_d_inventer():
    assert "premiere passe" in C.comparer({}, [{"fournisseur": "groq"}])[0]


def test_un_catalogue_qui_maigrit_est_signale():
    avant = {"horodatage": "hier", "fournisseurs": [{"fournisseur": "groq", "declares": 16}]}
    lignes = C.comparer(avant, [{"fournisseur": "groq", "declares": 13}])
    assert any("16 -> 13" in ligne for ligne in lignes)


def test_un_fournisseur_qui_devient_muet_est_signale():
    avant = {"fournisseurs": [{"fournisseur": "hf", "declares": 130}]}
    lignes = C.comparer(avant, [{"fournisseur": "hf", "etat": "NON_MESURE", "code": 402}])
    assert any("n'est PLUS mesurable" in ligne for ligne in lignes)


def test_un_fournisseur_disparu_est_signale():
    avant = {"fournisseurs": [{"fournisseur": "together", "declares": 5}]}
    assert any("DISPARU" in ligne for ligne in C.comparer(avant, []))


def test_aucun_changement_se_dit_aussi():
    avant = {"fournisseurs": [{"fournisseur": "groq", "declares": 13, "gratuits_annonces": 0}]}
    lignes = C.comparer(avant, [{"fournisseur": "groq", "declares": 13, "gratuits_annonces": 0}])
    assert any("aucun changement" in ligne for ligne in lignes)


# ── HF : le champ existe, ce qui ne prouve rien ──────────────────────────────

def test_un_champ_is_free_faux_ne_compte_pas():
    """Mesure du 2026-08-18 : le champ EST present chez HF, et zero modele est
    marque. Un champ present n'est pas un modele gratuit."""
    corps = json.dumps({"data": [{"id": "m", "providers": {"groq": {"is_free": False}}}]})
    assert H._marques_gratuites(corps) == []


def test_un_modele_marque_gratuit_est_releve_avec_son_provider():
    corps = json.dumps({"data": [{"id": "openai/gpt-oss-120b",
                                  "providers": {"groq": {"is_free": True}}}]})
    assert H._marques_gratuites(corps) == [("openai/gpt-oss-120b", "groq")]


def test_la_forme_liste_du_mapping_est_acceptee():
    """L'API HF a change de forme : dict de providers OU liste de fiches."""
    corps = json.dumps({"data": [{"modelId": "x",
                                  "inferenceProviderMapping": [
                                      {"provider": "cerebras", "is_free": True}]}]})
    assert H._marques_gratuites(corps) == [("x", "cerebras")]


def test_un_corps_illisible_ne_fait_pas_tomber_le_scan():
    assert H._marques_gratuites("<html>maintenance</html>") == []


# ── socle commun des sondes ─────────────────────────────────────────────────

def test_la_cle_voyage_en_entete_jamais_dans_l_url():
    import forge_endpoint_commun as K

    req = K.requete("https://api.exemple/v1/models", "secret-abc")
    assert req.headers.get("Authorization") == "Bearer secret-abc"
    assert "secret-abc" not in req.full_url


def test_sans_cle_aucun_entete_d_autorisation():
    import forge_endpoint_commun as K

    assert "Authorization" not in K.requete("http://127.0.0.1:11434/v1/models").headers


def test_un_reseau_ferme_rend_moins_un_pas_un_code_http(monkeypatch):
    """-1 doit rester distinct d'un refus : c'est la frontiere entre
    « je n'ai pas su demander » et « on m'a dit non »."""
    import forge_endpoint_commun as K

    monkeypatch.setattr(K.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("10061")))
    code, corps, _ = K.lire("http://127.0.0.1:9/v1/models")
    assert code == -1 and corps == "OSError"


def test_le_catalogue_rend_une_liste_vide_sur_refus(monkeypatch):
    import forge_endpoint_commun as K

    monkeypatch.setattr(K, "lire", lambda *a, **k: (402, '{"error":"credits"}', {}))
    code, modeles, _ = K.catalogue("https://x/v1", "cle")
    assert code == 402 and modeles == []


def test_les_embeddings_et_l_audio_sont_ecartes():
    import forge_endpoint_commun as K

    donnees = [{"id": "qwen-7b"}, {"id": "bge-m3"}, {"id": "whisper-large-v3"},
               {"id": "nomic-embed-text"}]
    assert [m["id"] for m in K.utiles(donnees)] == ["qwen-7b"]


def test_le_socle_prefere_les_petits():
    import forge_endpoint_commun as K

    donnees = [{"id": "a-70b"}, {"id": "b-1.5b"}, {"id": "c-8b"}]
    assert [m["id"] for m in K.plus_petits(donnees, 2)] == ["b-1.5b", "c-8b"]


# ── mise en route locale : trois pannes du 18/08 verrouillees ────────────────

def test_le_modele_choisi_est_le_plus_leger_et_instruct():
    """Deux pieges cumules : `deepseek-r1` (raisonnement) laisse `content` vide,
    et un 7B a froid ne repond pas dans le budget. On veut le petit instruct."""
    import forge_local_llm_bringup as B

    corps = json.dumps({"data": [
        {"id": "deepseek-r1-distill-qwen-14b"},
        {"id": "qwen2.5-coder:7b-instruct"},
        {"id": "nomic-embed-text"},
        {"id": "qwen2.5-coder:1.5b"},
    ]})
    assert B._premier_modele(corps) == "qwen2.5-coder:1.5b"


def test_un_catalogue_sans_modele_utile_rend_quand_meme_quelque_chose():
    import forge_local_llm_bringup as B

    corps = json.dumps({"data": [{"id": "bge-m3"}]})
    assert B._premier_modele(corps) == "bge-m3"


def test_un_corps_vide_ne_leve_pas():
    import forge_local_llm_bringup as B

    assert B._premier_modele("pas du json") == ""


def test_la_taille_apparente_ordonne_les_modeles():
    import forge_local_llm_bringup as B

    assert B._taille_apparente("qwen-1.5b") < B._taille_apparente("qwen-7b")
    assert B._taille_apparente("modele-anonyme") == 999.0
