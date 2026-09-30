"""NR — les trois outils de coffre du 2026-08-18.

Ils manipulent des SECRETS : un `ok:true` de complaisance y coute une valeur
irrecuperable — c'est arrive le matin meme, un PAT ecrase parce que personne
n'avait confronte la cible avant d'ecrire. Ce qu'on protege ici est donc
exactement l'ensemble des REFUS : absence au coffre, valeur divergente,
ecrasement sans motif, doublon incoherent dans le `.env`.

Hermetique : faux coffre injecte dans `sys.modules`, `.env` en `tmp_path`,
aucun appel reseau, aucune valeur de secret dans les assertions.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SECRET = "github_pat_" + "A" * 82          # jamais un vrai jeton
AUTRE = "github_pat_" + "B" * 82


def _faux_coffre(monkeypatch, store: dict) -> dict:
    """Remplace forge_machine_vault ET forge_secrets par un dict."""
    mv = types.ModuleType("forge_machine_vault")
    mv.vault_get = lambda cle: store.get(cle)
    mv.vault_set = lambda cle, val: (store.__setitem__(cle, val), True)[1]
    mv.vault_list = lambda: sorted(store)
    fs = types.ModuleType("forge_secrets")
    fs.get_secret = lambda cle: store.get(cle)
    fs.set_secret = lambda cle, val: (store.__setitem__(cle, val), True)[1]
    monkeypatch.setitem(sys.modules, "forge_machine_vault", mv)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_machine_vault", mv)
    monkeypatch.setitem(sys.modules, "forge_secrets", fs)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", fs)
    return store


def _env(tmp_path: Path, lignes: list[str]) -> Path:
    f = tmp_path / "Nokido.env"
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return f


# ── forge_env_drop_key : retirer une cle du clair ────────────────────────────

def _drop(monkeypatch, fichier: Path, argv: list[str]):
    import forge_env_drop_key as D

    monkeypatch.setattr(D, "_fichier_env", lambda: fichier)
    monkeypatch.setattr(sys, "argv", ["forge_env_drop_key.py", *argv])
    return D.main()


def test_drop_refuse_si_la_cle_est_absente_du_coffre(monkeypatch, tmp_path):
    """Retirer la ligne supprimerait la DERNIERE copie du secret."""
    _faux_coffre(monkeypatch, {})
    f = _env(tmp_path, ["PORT=7400", f"GITHUB_TOKEN={SECRET}"])
    assert _drop(monkeypatch, f, ["GITHUB_TOKEN"]) == 3
    assert SECRET in f.read_text(encoding="utf-8"), "le fichier ne doit PAS bouger"


def test_drop_refuse_si_le_coffre_porte_une_autre_valeur(monkeypatch, tmp_path):
    _faux_coffre(monkeypatch, {"GITHUB_TOKEN": AUTRE})
    f = _env(tmp_path, [f"GITHUB_TOKEN={SECRET}"])
    assert _drop(monkeypatch, f, ["GITHUB_TOKEN"]) == 3
    assert SECRET in f.read_text(encoding="utf-8")


def test_drop_accepte_un_nom_de_coffre_different(monkeypatch, tmp_path):
    """Un secret colle sous un nom approximatif reste le cas frequent."""
    _faux_coffre(monkeypatch, {"GITHUB_MODELS_TOKEN": SECRET})
    f = _env(tmp_path, ["PORT=7400", f"GITHUB_TOKEN={SECRET}", "AUTRE=1"])
    assert _drop(monkeypatch, f, ["GITHUB_TOKEN", "--vault-key", "GITHUB_MODELS_TOKEN"]) == 0
    contenu = f.read_text(encoding="utf-8")
    assert SECRET not in contenu
    assert "PORT=7400" in contenu and "AUTRE=1" in contenu, "les autres lignes restent"
    assert "GITHUB_MODELS_TOKEN" in contenu, "la marque dit ou la valeur est partie"


def test_drop_en_dry_run_n_ecrit_rien(monkeypatch, tmp_path):
    _faux_coffre(monkeypatch, {"GITHUB_TOKEN": SECRET})
    f = _env(tmp_path, [f"GITHUB_TOKEN={SECRET}"])
    avant = f.read_text(encoding="utf-8")
    assert _drop(monkeypatch, f, ["GITHUB_TOKEN", "--dry-run"]) == 0
    assert f.read_text(encoding="utf-8") == avant


def test_drop_refuse_deux_valeurs_differentes_sous_la_meme_cle(monkeypatch, tmp_path):
    _faux_coffre(monkeypatch, {"GITHUB_TOKEN": SECRET})
    f = _env(tmp_path, [f"GITHUB_TOKEN={SECRET}", f"GITHUB_TOKEN={AUTRE}"])
    assert _drop(monkeypatch, f, ["GITHUB_TOKEN"]) == 3
    assert AUTRE in f.read_text(encoding="utf-8")


def test_drop_ignore_les_lignes_commentees(monkeypatch, tmp_path):
    import forge_env_drop_key as D

    lignes = ["# GITHUB_TOKEN=ancien", f"GITHUB_TOKEN={SECRET}"]
    assert D._lignes_de("GITHUB_TOKEN", lignes) == [1]


# ── forge_vault_copy_key : ranger une cle sous un autre nom ──────────────────

def _copy(monkeypatch, argv: list[str]):
    import forge_vault_copy_key as C

    monkeypatch.setattr(sys, "argv", ["forge_vault_copy_key.py", *argv])
    return C.main()


def test_copy_refuse_une_source_absente(monkeypatch):
    store = _faux_coffre(monkeypatch, {"B": SECRET})
    assert _copy(monkeypatch, ["A", "B"]) == 3
    assert store["B"] == SECRET


def test_copy_refuse_d_ecraser_sans_le_dire(monkeypatch):
    """Un vault_set est un ecrasement silencieux : c'est ainsi qu'un PAT a ete perdu."""
    store = _faux_coffre(monkeypatch, {"A": SECRET, "B": AUTRE})
    assert _copy(monkeypatch, ["A", "B"]) == 3
    assert store["B"] == AUTRE, "la destination doit rester intacte"


def test_copy_exige_un_motif_pour_ecraser(monkeypatch):
    store = _faux_coffre(monkeypatch, {"A": SECRET, "B": AUTRE})
    assert _copy(monkeypatch, ["A", "B", "--ecraser"]) == 3
    assert store["B"] == AUTRE


def test_copy_ecrase_quand_le_motif_est_donne(monkeypatch):
    store = _faux_coffre(monkeypatch, {"A": SECRET, "B": AUTRE})
    assert _copy(monkeypatch, ["A", "B", "--ecraser", "--motif", "revoque (401)"]) == 0
    assert store["B"] == SECRET


def test_copy_sur_une_destination_identique_ne_fait_rien(monkeypatch):
    store = _faux_coffre(monkeypatch, {"A": SECRET, "B": SECRET})
    assert _copy(monkeypatch, ["A", "B"]) == 0
    assert store["B"] == SECRET


def test_copy_en_dry_run_n_ecrit_pas(monkeypatch):
    store = _faux_coffre(monkeypatch, {"A": SECRET})
    assert _copy(monkeypatch, ["A", "B", "--dry-run"]) == 0
    assert "B" not in store


# ── forge_token_probe : demander a GitHub, sans rien divulguer ───────────────

def test_probe_lit_le_code_et_l_identite_sans_divulguer_le_jeton(monkeypatch):
    import forge_token_probe as P

    vus = {}

    class _Rep:
        status = 200

        def read(self, _n=None):
            return b'{"login": "user"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _faux_urlopen(req, timeout=None):
        vus["auth"] = req.headers.get("Authorization", "")
        vus["url"] = req.full_url
        return _Rep()

    monkeypatch.setattr(P.urllib.request, "urlopen", _faux_urlopen)
    code, detail = P._appel("https://api.github.com/user", SECRET)
    assert (code, detail) == (200, "user")
    assert vus["auth"].endswith(SECRET), "le jeton voyage en en-tete, pas dans l'URL"
    assert SECRET not in vus["url"]


def test_probe_rend_un_code_sur_erreur_http(monkeypatch):
    import forge_token_probe as P

    def _boom(req, timeout=None):
        raise P.urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(P.urllib.request, "urlopen", _boom)
    assert P._appel("https://api.github.com/user", SECRET) == (401, "Unauthorized")


def test_probe_ne_meurt_pas_quand_le_reseau_est_ferme(monkeypatch):
    """Sandbox offline : un -1 doit se lire comme « non mesure », pas comme un refus."""
    import forge_token_probe as P

    def _boom(req, timeout=None):
        raise OSError("WinError 10013")

    monkeypatch.setattr(P.urllib.request, "urlopen", _boom)
    code, detail = P._appel("https://api.github.com/user", SECRET)
    assert code == -1 and detail == "OSError"


def test_probe_liste_le_coffre_et_le_clair(monkeypatch, tmp_path):
    import forge_token_probe as P

    _faux_coffre(monkeypatch, {"GITHUB_TOKEN": SECRET, "GITHUB_MODELS_TOKEN": AUTRE})
    monkeypatch.setattr(P, "ROOT", tmp_path)
    _env(tmp_path, ["PORT=7400", f"GITHUB_AUTRE_TOKEN={SECRET}", "# GITHUB_VIEUX=x"])
    etiquettes = [e for e, _v in P.sources()]
    assert "coffre:GITHUB_TOKEN" in etiquettes
    assert any("GITHUB_AUTRE_TOKEN" in e for e in etiquettes), "la ligne en clair est testee aussi"
    assert not any("GITHUB_VIEUX" in e for e in etiquettes), "un commentaire n'est pas un jeton"


# ── forge_vault_set_config : de la CONFIG, jamais un secret ──────────────────

def test_un_jeton_en_ligne_de_commande_est_refuse():
    """Une valeur passee en argument se lit dans la table des processus : y
    poser un jeton le divulguerait a tout compte capable de lister les process."""
    import forge_vault_set_config as C

    for valeur in ("github_pat_" + "A" * 82, "sk-" + "B" * 40, "AIza" + "C" * 35,
                   "gsk_" + "D" * 30, "e" * 44):
        assert C.ressemble_a_un_secret("PEU_IMPORTE", valeur), valeur


def test_un_nom_de_cle_sensible_est_refuse_meme_avec_valeur_courte():
    import forge_vault_set_config as C

    assert C.ressemble_a_un_secret("GROQ_API_KEY", "abc")
    assert C.ressemble_a_un_secret("MON_TOKEN", "x")


def test_une_config_legitime_passe():
    """Le garde ne doit pas bloquer ce pour quoi l'outil existe."""
    import forge_vault_set_config as C

    assert C.ressemble_a_un_secret("GEMINI_MODEL", "gemini-pro-latest") == ""
    assert C.ressemble_a_un_secret("OLLAMA_URL", "http://127.0.0.1:11434") == ""
    assert C.ressemble_a_un_secret("LAFORGE_MODE", "local") == ""


def test_le_set_config_verifie_par_relecture(monkeypatch):
    store = _faux_coffre(monkeypatch, {})
    import forge_vault_set_config as C

    monkeypatch.setattr(sys, "argv", ["x", "GEMINI_MODEL", "gemini-pro-latest"])
    assert C.main() == 0
    assert store["GEMINI_MODEL"] == "gemini-pro-latest"


def test_le_set_config_refuse_et_n_ecrit_rien(monkeypatch):
    store = _faux_coffre(monkeypatch, {})
    import forge_vault_set_config as C

    monkeypatch.setattr(sys, "argv", ["x", "GITHUB_TOKEN", SECRET])
    assert C.main() == 3
    assert store == {}


# ── forge_gemini_models_sync : comparer ce qui est comparable ────────────────

def test_les_prefixes_de_fournisseur_sont_normalises():
    """Le routeur prefixe `gemini/`, l'API prefixe `models/`. Comparer les
    formes brutes declarait INTROUVABLE 7 modeles sur 7 alors que 3 existent."""
    import forge_gemini_models_sync as G

    assert G._normaliser("gemini/gemini-2.5-flash") == "gemini-2.5-flash"
    assert G._normaliser("models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert G._normaliser("gemini-2.5-flash") == "gemini-2.5-flash"


def test_la_confrontation_separe_present_et_disparu():
    import forge_gemini_models_sync as G

    lignes = G.confronter({"gemini_pro": ["gemini/gemini-1.5-pro", "gemini/gemini-2.5-pro"]},
                          ["models/gemini-2.5-pro", "models/gemini-flash-latest"])
    etats = {x["modele"]: x["existe"] for x in lignes}
    assert etats == {"gemini-1.5-pro": False, "gemini-2.5-pro": True}


def test_un_catalogue_illisible_ne_condamne_personne(monkeypatch):
    """Ne pas savoir demander n'est pas un verdict : le code de sortie doit
    dire INDETERMINE (3), jamais laisser croire que les modeles sont morts."""
    import forge_gemini_models_sync as G

    monkeypatch.setattr(G, "catalogue", lambda: ([], "cle absente"))
    monkeypatch.setattr(sys, "argv", ["x"])
    assert G.main() == 3


# ── forge_provider_catalogue : la cle ou le modele ? ─────────────────────────

def test_le_catalogue_ne_divulgue_que_le_suffixe():
    import forge_provider_catalogue as P

    assert P._suffixe(SECRET) == "..." + SECRET[-4:]
    assert SECRET not in P._suffixe(SECRET)
    assert P._suffixe("") == "(absente)"


def test_le_catalogue_extrait_les_identifiants_de_modeles(monkeypatch):
    import forge_provider_catalogue as P

    class _Rep:
        status = 200

        def read(self, _n=None):
            return b'{"data": [{"id": "gpt-oss-120b"}, {"id": "compound-mini"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(P.urllib.request, "urlopen", lambda req, timeout=None: _Rep())
    code, ids, _ = P.interroger("https://x/v1/models", SECRET)
    assert code == 200 and ids == ["compound-mini", "gpt-oss-120b"]


def test_le_catalogue_rapporte_le_corps_d_un_refus(monkeypatch):
    """C'est ce corps qui distingue « cle desactivee » de « modele inconnu » :
    le 2026-08-18, il a innocente les cles Groq et Cerebras."""
    import forge_provider_catalogue as P

    def _refus(req, timeout=None):
        raise P.urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {},
            __import__("io").BytesIO(b'{"error":"The API key is disabled"}'))

    monkeypatch.setattr(P.urllib.request, "urlopen", _refus)
    code, ids, detail = P.interroger("https://x/v1/models", SECRET)
    assert code == 403 and ids == []
    assert "disabled" in detail


def test_le_catalogue_regroupe_les_modeles_cables_par_famille():
    import forge_provider_catalogue as P

    par_famille = P.modeles_cables()
    assert "groq" in par_famille and "mistral" in par_famille
    assert any("gpt-oss" in m for m in par_famille["groq"]), par_famille["groq"]


def test_les_empreintes_distinguent_deux_jetons():
    import forge_env_drop_key as D
    import forge_vault_copy_key as C

    assert D._empreinte(SECRET) != D._empreinte(AUTRE)
    assert C.empreinte(SECRET) == D._empreinte(SECRET), "meme convention partout"
    assert len(D._empreinte(SECRET)) == 12
    assert D._empreinte("") == ""


# ---------------------------------------------------------------------------
# OU LE COFFRE EST-IL CHERCHE — le chainon manquant de la CI (2026-09-16)
#
# MESURE. `VAULT_PATH = ROOT / "data" / "machine_vault.dat"` avec
# `ROOT = Path(__file__).resolve().parent.parent` : le coffre est cherche a cote
# du MODULE. En CI le depot est clone dans `C:\laforge-runner\_work\...`, et
# `data/` est `.gitignore:62` — donc le coffre y est ABSENT. `get_secret`
# descend alors ses quatre couches jusqu'a `os.environ`, c'est-a-dire jusqu'au
# secret GitHub `LAFORGE_ADMIN_TOKEN` du 2026-07-03, jamais renouvele. D'ou le
# `TENTE_ET_REFUSE` du gate UI, la ou le meme jeton du coffre ETABLIT le login
# en local.
#
# 🔑 LE POINT QUI REND CE CORRECTIF SUR : le coffre est chiffre avec
# `CRYPTPROTECT_LOCAL_MACHINE`, donc TOUT compte de cette machine le dechiffre,
# y compris celui du runner self-hosted. Ce qui manque n'est PAS un secret,
# c'est un CHEMIN. On ne transporte donc aucune valeur : ni dans le workflow,
# ni dans l'environnement, ni dans les journaux.
#
# ⚠️ ET CE QUE L'OVERRIDE NE DOIT JAMAIS DEVENIR : un chemin d'ECRITURE.
# Pointer le coffre ailleurs pour le LIRE est benin (un mauvais coffre donne un
# mauvais jeton, donc un login refuse, jamais une fuite) ; y ECRIRE deplacerait
# des secrets vers un emplacement dicte par l'environnement. L'override est
# donc en LECTURE SEULE, et il est REFUSE s'il est relatif ou inexistant --
# refuser en le DISANT, plutot que de creer un coffre vide ailleurs.
# ---------------------------------------------------------------------------


def _vault():
    import forge_machine_vault as V
    return V


def test_sans_override_le_chemin_par_defaut_est_garde():
    V = _vault()
    chemin, motif = V.resoudre_chemin_coffre(Path("/d/vault.dat"), "", lambda p: True)
    assert chemin == Path("/d/vault.dat") and motif == "DEFAUT"


def test_un_override_ABSOLU_et_EXISTANT_est_retenu(tmp_path):
    # `tmp_path` et NON un litteral « /ailleurs/... » : sous Windows un chemin
    # sans lettre de lecteur n'est PAS absolu, et ces deux tests sont d'abord
    # sortis rouges pour cette raison — l'instrument etait faux, pas le code.
    V = _vault()
    cible = tmp_path / "machine_vault.dat"
    chemin, motif = V.resoudre_chemin_coffre(
        tmp_path / "defaut.dat", str(cible), lambda p: True)
    assert chemin == cible and motif == "OVERRIDE", (
        "le runner CI ne peut toujours pas trouver le coffre de la machine"
    )


def test_un_override_RELATIF_est_REFUSE_en_le_disant():
    V = _vault()
    chemin, motif = V.resoudre_chemin_coffre(
        Path("/d/vault.dat"), "data/machine_vault.dat", lambda p: True)
    assert chemin == Path("/d/vault.dat"), "un chemin relatif depend du repertoire courant"
    assert motif == "REFUSE_RELATIF"


def test_un_override_INEXISTANT_ne_cree_pas_un_coffre_ailleurs(tmp_path):
    V = _vault()
    defaut = tmp_path / "defaut.dat"
    chemin, motif = V.resoudre_chemin_coffre(
        defaut, str(tmp_path / "nulle_part.dat"), lambda p: False)
    assert chemin == defaut, (
        "un override qui ne designe rien ferait naitre un coffre VIDE ailleurs, "
        "et un coffre vide se lit comme un secret absent"
    )
    assert motif == "REFUSE_ABSENT"


def test_le_motif_ne_porte_JAMAIS_de_valeur_de_secret():
    V = _vault()
    for cas in (("", lambda p: True), ("data/x.dat", lambda p: True),
                (str(Path("/x/y.dat")), lambda p: False)):
        _c, motif = V.resoudre_chemin_coffre(Path("/d/v.dat"), cas[0], cas[1])
        assert motif in {"DEFAUT", "OVERRIDE", "REFUSE_RELATIF", "REFUSE_ABSENT"}, (
            "le motif doit rester un CODE ferme : toute interpolation libre "
            "risquerait d'y faire entrer une valeur"
        )


def test_l_ECRITURE_n_emprunte_jamais_l_override():
    import ast
    import inspect
    V = _vault()
    arbre = ast.parse(inspect.getsource(V))
    sauve = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef) and n.name == "_save"]
    assert sauve, "la fonction d'ecriture du coffre a disparu"
    noms = {n.id for n in ast.walk(sauve[0]) if isinstance(n, ast.Name)}
    assert "VAULT_PATH" in noms, "l'ecriture doit rester sur le chemin canonique"
    assert "chemin_coffre" not in noms, (
        "l'ecriture suit l'override : des secrets partiraient vers un "
        "emplacement dicte par l'environnement"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
