"""NR — le cloud d'Ollama est coupe a la source (veille lot_B_23, 24/09).

Ollama sait router vers SON cloud (modeles `-cloud`, recherche web ; `internal/cloud/policy.go`).
L'Ollama installe affichait `OLLAMA_NO_CLOUD:false`. Or `SemanticFirewall.pre_flight` classe le
fournisseur « ollama » comme LOCAL et ne lui applique pas la DLP : un modele cloud tire par Ollama
sortirait sans passer le pare-feu. La coupure se fait a la source : `OLLAMA_NO_CLOUD=1` dans
l'environnement DECLARE du service (un service n'herite du TOML que lance par le superviseur).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def test_nokido_ollama_declare_pas_de_cloud():
    d = tomllib.loads((RACINE / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8"))
    services = {s["name"]: s for s in d.get("service", [])}
    assert "NokidoOllama" in services, "service NokidoOllama introuvable dans services.toml"
    env = services["NokidoOllama"].get("env") or {}
    assert str(env.get("OLLAMA_NO_CLOUD")) == "1", (
        "OLLAMA_NO_CLOUD absent ou different de 1 : Ollama peut sortir vers son cloud sans DLP")
