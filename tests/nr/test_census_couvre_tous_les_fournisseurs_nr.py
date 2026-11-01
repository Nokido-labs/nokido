import json
from pathlib import Path
import sys

# Ensure the tools module is importable
sys.path.append(str(Path(__file__).resolve().parents[2] / "tools"))

import forge_free_tier_census as ftc

def test_census_covers_all_providers(monkeypatch, tmp_path):
    # Monkeypatch SORTIE to a temporary file
    sortie_path = tmp_path / "census_output.json"
    monkeypatch.setattr(ftc, "SORTIE", sortie_path)

    # Mock get_secret in the module where it's defined
    def mock_get_secret(env_key):
        # Return a dummy value if env_key not empty, else empty
        return "dummy-key" if env_key else ""
    monkeypatch.setattr("nokido_agent.app.forge_secrets.get_secret", mock_get_secret)

    # Mock catalogue to return a successful response with at least one model
    def mock_catalogue(base, cle):
        # Return code 200, a list with one model dict, and empty headers, and empty detail
        models = [{"id": "test-model"}]
        return 200, models, {}, ""
    monkeypatch.setattr(ftc, "catalogue", mock_catalogue)

    # Mock est_gratuit to return True for the model
    def mock_est_gratuit(modele, etiquette):
        return True
    monkeypatch.setattr(ftc, "est_gratuit", mock_est_gratuit)

    # Mock joignable to return reachable
    # 31/10 : 640262e9a (30/10) a ajoute `fournisseur=` a joignable (coupe-circuit avant requete) ; la doublure suit.
    def mock_joignable(base, cle, model_id, fournisseur=None):
        return True, ""
    monkeypatch.setattr(ftc, "joignable", mock_joignable)

    # Mock quota to return some dummy quota string
    def mock_quota(etiquette, cle, entetes):
        return "free"
    monkeypatch.setattr(ftc, "quota", mock_quota)

    # Clear any previous argv that might affect main
    monkeypatch.setattr(sys, "argv", ["forge_free_tier_census.py"])

    # Run main
    ftc.main()

    # Load the output JSON
    assert sortie_path.exists(), "Output file was not created"
    data = json.loads(sortie_path.read_text(encoding="utf-8"))
    # Expect a 'fournisseurs' list with entries for each provider in FOURNISSEURS
    fournisseurs = data.get("fournisseurs", [])
    # Build set of provider IDs from FOURNISSEURS
    expected_ids = {prov[0] for prov in ftc.FOURNISSEURS}
    actual_ids = {entry["fournisseur"] for entry in fournisseurs}
    # Ensure all expected providers are present
    missing = expected_ids - actual_ids
    assert not missing, f"Missing providers in census output: {missing}"
    # Ensure each entry has the expected structure
    for entry in fournisseurs:
        # entry should have 'fournisseur', 'etat', and 'motif' (if etat != MESURE)
        assert "fournisseur" in entry
        assert "etat" in entry
        # 30/10 : A_LA_DEMANDE (LM Studio) = catalogue lu, completion non tentee (chargement juste-a-temps hors admission)
        assert entry["etat"] in ("MESURE", "NON_MESURE", "CLE_ABSENTE", "NON_SONDE", "A_LA_DEMANDE"), f"Unexpected etat: {entry['etat']}"
        if entry["etat"] != "MESURE":
            assert "motif" in entry
            assert isinstance(entry["motif"], str)
            assert len(entry["motif"]) > 0, f"Motif should be non-empty for etat {entry['etat']}"
        # For CLE_ABSENTE, we expect a specific motif format (optional to check)
        if entry["etat"] == "CLE_ABSENTE":
            assert "cle manquante:" in entry["motif"]
        # For NON_SONDE, we expect a raison field (but note: the output structure may vary)
        # We'll just ensure the entry is not empty
        assert entry, f"Empty entry for provider {entry.get('fournisseur')}"


# --- Ajouts de l'integrateur (26/10) : exigences de la revue que le test ne verrouillait pas encore ---

def _scene(monkeypatch, tmp_path, cles=None, catalogue=None):
    sortie = tmp_path / "census.json"
    monkeypatch.setattr(ftc, "SORTIE", sortie)
    vides = set(cles or ())
    monkeypatch.setattr("nokido_agent.app.forge_secrets.get_secret",
                        lambda k: "" if k in vides else ("factice" if k else ""))
    monkeypatch.setattr(ftc, "catalogue", catalogue or (lambda base, cle: (200, [{"id": "m"}], {}, "")))
    monkeypatch.setattr(ftc, "est_gratuit", lambda m, e: True)
    sondes = []
    monkeypatch.setattr(ftc, "joignable", lambda base, cle, mid, fournisseur=None: sondes.append((base, mid)) or (True, ""))
    monkeypatch.setattr(ftc, "quota", lambda *a: "free")
    monkeypatch.setattr(sys, "argv", ["forge_free_tier_census.py"])
    ftc.main()
    return {e["fournisseur"]: e for e in json.loads(sortie.read_text(encoding="utf-8"))["fournisseurs"]}, sondes


def test_une_cle_absente_est_dite_avec_son_nom(monkeypatch, tmp_path):
    par, _ = _scene(monkeypatch, tmp_path, cles={"OLLAMA_API_KEY"})
    e = par["ollama_cloud"]
    assert e["etat"] == "CLE_ABSENTE" and "OLLAMA_API_KEY" in e["motif"]


def test_ollama_cloud_ne_sonde_que_le_palier_free(monkeypatch, tmp_path):
    def cat(base, cle):
        if "ollama.com" in base:
            return 200, [{"id": "nemotron-3-super"}, {"id": "kimi-k2:1t"}], {}, ""
        return 200, [{"id": "m"}], {}, ""
    _, sondes = _scene(monkeypatch, tmp_path, catalogue=cat)
    sondes_cloud = {mid for base, mid in sondes if "ollama.com" in base}
    assert "kimi-k2:1t" not in sondes_cloud and sondes_cloud <= {"nemotron-3-super"}


def test_toute_entree_porte_un_etat_et_un_motif_hors_mesure(monkeypatch, tmp_path):
    par, _ = _scene(monkeypatch, tmp_path)
    for nom, e in par.items():
        assert e.get("etat") in ("MESURE", "NON_MESURE", "CLE_ABSENTE", "NON_SONDE", "A_LA_DEMANDE"), (nom, e)
        if e["etat"] != "MESURE":
            assert str(e.get("motif") or "").strip(), (nom, e)


def test_le_corps_d_une_erreur_http_ne_va_jamais_dans_le_motif(monkeypatch):
    """Un 401 renvoie parfois la cle partiellement masquee dans son corps : le motif ne garde que code et raison."""
    import io
    import urllib.error

    def ko(*a, **k):
        raise urllib.error.HTTPError("https://x/models", 401, "Unauthorized", {},
                                     io.BytesIO(b'{"error": "Incorrect API key provided: sk-SECRETabcd"}'))

    monkeypatch.setattr(ftc.urllib.request, "urlopen", ko)
    code, modeles, entetes, detail = ftc.catalogue("https://x", "factice")
    assert code == 401 and modeles == [] and "SECRET" not in detail and "401" in detail
