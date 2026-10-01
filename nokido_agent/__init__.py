"""Namespace `nokido_agent` — le meme import, et le MEME OBJET, dans les deux modes.

POURQUOI `nokido_agent` ET PAS `nokido`. Mesure du 2026-09-10 : le nom `nokido`
est deja pris par `tools/nokido.py` (« Entrypoint unifie Nokido, LE script a
executer ») et par `app/Nokido.py`. Comme `sys.path[0]` vaut `tools/` pour un
script lance par chemin, `import nokido` resolvait vers le MODULE et masquait le
paquet dans tout le corps. Decision owner, option E.

DEUX MODES :

    INSTALLE   `nokido_agent/app/` et `nokido_agent/tools/` existent REELLEMENT
               dans la wheel (via `[tool.setuptools.package-dir]`). Aucun frere
               n'est trouve : le pont ci-dessous ne s'active pas.

    CHECKOUT   les fichiers vivent a `app/` et `tools/`, freres de ce paquet.

LE DEFAUT QUE CE PONT CORRIGE — mesure, apres une premiere version naive qui se
contentait de poser `__path__` :

    plat  : forge_db_path                    id=2447687418880
    ns    : nokido_agent.app.forge_db_path   id=2447687423360
    MEME OBJET ? False

DEUX exemplaires du meme fichier, donc deux etats separes : caches, singletons,
connexions, verrous. Consequence mesuree : `test_fts_rattrapage_incremental_nr`
ouvrait DEUX connexions SQLite qui s'attendaient — le gate pytest tombait en
Timeout, sans jamais nommer la cause. Et tout `monkeypatch.setattr` sur une forme
laissait l'autre intacte : des gardes qui ne gardaient plus rien.

Pendant une migration progressive, les deux formes coexistent NECESSAIREMENT.
L'identite n'est donc pas un raffinement : c'est la condition pour que la
coexistence soit sure.

CE QUE LE PONT NE COUVRE PAS, et qui est DIT plutot que suppose : les
sous-paquets (`nokido_agent.app.rag`) passent par le `__path__` normal et peuvent
encore se dedoubler. Les modules a plat — la quasi-totalite du corps — sont
couverts. A instruire si un sous-paquet porte de l'etat partage.

DETTE ASSUMEE. Ce pont disparaitra le jour ou `app/` et `tools/` vivront
physiquement sous le paquet. Ce deplacement casserait aujourd'hui tout ce qui les
adresse par CHEMIN (`run_job script=tools/...`, hooks, `services.toml`, taches
planifiees, workflows CI) : chantier distinct, non ouvert.
"""
from __future__ import annotations

import importlib.util as _iu
import sys as _sys
import types as _types
from importlib.abc import Loader as _Loader
from importlib.abc import MetaPathFinder as _Finder
from pathlib import Path as _Path

__version__ = "0.20.5"

_RACINE = _Path(__file__).resolve().parent.parent
_ZONES = ("app", "tools")


class _PontIdentite(_Finder, _Loader):
    """Fait pointer `nokido_agent.<zone>.<module>` sur l'objet du module PLAT.

    `create_module` a le droit de rendre un module DEJA existant : c'est ce qui
    garantit un exemplaire unique. Python enregistre ensuite le nom complet dans
    `sys.modules`, si bien que les deux clefs designent le meme objet — quel que
    soit l'ordre des imports.
    """

    def find_spec(self, fullname, path=None, target=None):
        prefixe = __name__ + "."
        if not fullname.startswith(prefixe):
            return None
        parties = fullname[len(prefixe):].split(".")
        if len(parties) != 2 or parties[0] not in _ZONES:
            return None                      # sous-paquets : chemin normal
        fichier = _RACINE / parties[0] / (parties[1] + ".py")
        if not fichier.is_file():
            return None                      # mode INSTALLE : rien a ponter
        return _iu.spec_from_loader(fullname, self, origin=str(fichier))

    # Marqueur pose par `create_module` et consomme par `exec_module`. Il
    # distingue les DEUX seuls appelants possibles : `importlib.reload` ne
    # passe JAMAIS par `create_module` (il n'y a rien a creer), il n'appelle
    # que `exec_module`. Sans ce marqueur, les deux chemins sont
    # indiscernables et l'un des deux est forcement mal servi.
    _CREATION = "__pont_identite_creation__"

    def create_module(self, spec):
        zone, nom_plat = spec.name.split(".")[-2:]
        module = _sys.modules.get(nom_plat)
        if module is None:                   # sinon : le plat existe, on le reutilise
            fichier = _RACINE / zone / (nom_plat + ".py")
            interne = _iu.spec_from_file_location(nom_plat, fichier)
            module = _iu.module_from_spec(interne)
            # Enregistre AVANT execution : un import circulaire doit retrouver
            # l'objet en cours de construction, pas en creer un second.
            _sys.modules[nom_plat] = module
            interne.loader.exec_module(module)
        setattr(module, self._CREATION, True)
        return module

    def exec_module(self, module):
        """Inerte a l'import, REEXECUTE au rechargement.

        DEFAUT MESURE le 2026-09-13 : cette methode rendait `None` sans
        condition. Correct pour un import -- le contenu vient d'etre execute
        par `create_module` -- mais pour `importlib.reload` cela faisait un
        NO-OP SILENCIEUX : le fichier n'etait jamais relu, aucune erreur
        n'etait levee, et toute constante calculee au niveau module gardait sa
        valeur d'origine. Un reload inerte est un generateur de FAUX VERTS :
        un test qui recharge pour observer une reconfiguration passe sans rien
        verifier. Contrat : tests/nr/test_namespace_nokido_nr.py.

        LE NOM EST RENDU AU MODULE PLAT, et ce n'est pas cosmetique : avant
        d'appeler cette methode, `_init_module_attrs(override=True)` a reecrit
        `__name__` avec le nom LONG, et `SourceFileLoader` refuse alors de
        travailler -- « loader for forge_access_switches cannot handle
        nokido_agent.app.forge_access_switches » (mesure du 2026-09-13, premiere
        version de ce correctif, attrapee par le NR). Le module reprend donc son
        nom plat, celui sous lequel le corps entier l'adresse. `__spec__` reste
        le spec long : un rechargement suivant repart de `__spec__.name` et
        repasse donc ici. Le NR joue DEUX tours pour le prouver.
        """
        if getattr(module, self._CREATION, False):
            try:
                delattr(module, self._CREATION)
            except AttributeError:
                pass                         # muet-ok : absent = etat voulu
            return None
        origine = getattr(getattr(module, "__spec__", None), "origin", None)
        if not origine:
            return None                      # pas d'origine lisible : ne rien inventer
        nom_plat = module.__name__.split(".")[-1]
        interne = _iu.spec_from_file_location(nom_plat, origine)
        if interne is None or interne.loader is None:
            return None
        module.__name__ = nom_plat           # le loader verifie la correspondance
        interne.loader.exec_module(module)   # reexecution DANS le meme objet
        return None


if any((_RACINE / _z).is_dir() for _z in _ZONES):
    if not any(isinstance(_f, _PontIdentite) for _f in _sys.meta_path):
        _sys.meta_path.insert(0, _PontIdentite())

    for _nom in _ZONES:
        _dossier = _RACINE / _nom
        _cle = f"{__name__}.{_nom}"
        if _dossier.is_dir() and _cle not in _sys.modules:
            _module = _types.ModuleType(_cle)
            _module.__doc__ = f"Rattachement checkout de `{_nom}/` sous nokido_agent."
            _module.__path__ = [str(_dossier)]
            _sys.modules[_cle] = _module
            setattr(_sys.modules[__name__], _nom, _module)

    del _nom, _dossier, _cle
