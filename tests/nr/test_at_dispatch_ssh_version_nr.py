# -*- coding: utf-8 -*-
"""NR — une reconnexion `@ssh` REUSSIE ne doit pas finir sur un message d'erreur.

Apres la connexion, `_reconnect` met a jour le sous-titre avec `__version__`,
global du monolithe `Nokido.py` que l'extrait `forge_at_dispatch` ne definit pas.
NameError en toute fin de `try` : l'utilisateur lisait « ❌ SSH <hote> : name
'__version__' is not defined » juste apres une connexion reussie, et le
sous-titre n'etait jamais mis a jour. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Le correctif lit la version du monolithe par `forge_app_context._from_main`,
comme le font deja les autres accesseurs du module. Test statique : le chemin
demande un vrai serveur SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_version_du_sous_titre_est_liee():
    assert "__version__" not in noms_globaux_non_lies(
        "app/forge_at_dispatch.py", "handle_at_ssh")
