# -*- coding: utf-8 -*-
"""NR — `@services add` doit construire un service ET le juger avec le bon module.

Deux defauts sur la meme branche de `handle_at_services` :

1. `protocol=Protocol.HTTP` : `Protocol` (enum metier de `forge_services`) n'etait
   importe nulle part -> NameError, rattrape en « ❌ Erreur : name 'Protocol' is
   not defined ». Aucun service ne pouvait etre ajoute.
2. `ServiceEndpoint`, `ServiceType`, `ServiceStatus` venaient de `app.forge_services`
   (import de tete), le registre de `nokido_agent.app.forge_services`. Mesure : ce
   sont DEUX objets module distincts, et `app...ServiceStatus.HEALTHY ==
   nokido_agent...ServiceStatus.HEALTHY` vaut False -- un service sain aurait ete
   affiche « ⚠️ ».

Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).
Test statique : le chemin demande un registre de services vivant.
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import RACINE, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_at_dispatch.py"


def test_protocol_est_lie_dans_services():
    assert "Protocol" not in noms_globaux_non_lies(FICHIER, "handle_at_services")


def test_les_types_du_service_viennent_du_module_du_registre():
    arbre = ast.parse((RACINE / FICHIER).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arbre)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_at_services")
    importes = {a.name for n in ast.walk(fn)
                if isinstance(n, ast.ImportFrom) and n.module == "nokido_agent.app.forge_services"
                for a in n.names}
    assert {"get_registry", "Protocol", "ServiceEndpoint", "ServiceStatus", "ServiceType"} <= importes
