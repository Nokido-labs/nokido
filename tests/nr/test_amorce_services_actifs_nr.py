"""NR 18/10 -- tout service ACTIF lance par chemin amorce la racine du depot (liste DERIVEE de services.toml).

Mesure du 18/10 : NokidoMemoryConsolidator, rallume ce jour par decision owner (f2b8fbac9), crashait
toutes les ~5 min (`ModuleNotFoundError: No module named 'nokido_agent'`, journal superviseur) pendant
que test_amorce_namespace_daemons_nr restait VERT : sa liste DAEMONS est ecrite a la main (« l'oublier
coute dix jours de mort silencieuse » -- c'est arrive). Ici la liste se DERIVE de services.toml : chaque
service non disabled dont le premier argument est un .py du depot ET qui importe nokido_agent au niveau
MODULE est charge PAR SON FICHIER, racine retiree de sys.path, comme le superviseur le lance.
Un fichier introuvable ou un TOML illisible echoue en le disant (jamais un vert par absence).
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
TOML = RACINE / "proxy_deno" / "core" / "services.toml"


def _importe_nokido_agent_au_niveau_module(chemin: Path) -> bool:
    arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    for noeud in arbre.body:  # niveau MODULE seulement : un import paresseux ne casse pas le chargement
        if isinstance(noeud, ast.ImportFrom) and (noeud.module or "").startswith("nokido_agent"):
            return True
        if isinstance(noeud, ast.Import) and any(a.name.startswith("nokido_agent") for a in noeud.names):
            return True
    return False


def _scripts_concernes() -> list[tuple[str, Path]]:
    services = tomllib.loads(TOML.read_text(encoding="utf-8")).get("service", [])
    assert services, "services.toml illisible ou sans [[service]] : rien ne serait verifie"
    out = []
    for s in services:
        args = s.get("args") or []
        if s.get("disabled") or not args or not str(args[0]).endswith(".py"):
            continue
        brut = str(args[0])
        for var in ("${NOKIDO_DEPOT}", "${ROOT}"):  # variables du superviseur qui designent le depot
            brut = brut.replace(var, str(RACINE))
        assert "${" not in brut, "%s : variable non resolue par ce test dans %s" % (s.get("name"), args[0])
        chemin = Path(brut) if Path(brut).is_absolute() else RACINE / brut
        assert chemin.exists(), "%s : script declare introuvable %s" % (s.get("name"), args[0])
        if _importe_nokido_agent_au_niveau_module(chemin):
            out.append((str(s.get("name")), chemin))
    return out


def test_la_liste_derivee_n_est_pas_vide():
    assert _scripts_concernes(), "aucun service actif n'importe nokido_agent au niveau module : instrument a revoir"


def test_chaque_service_actif_par_chemin_charge_sans_la_racine():
    manquants, illisibles = [], []
    for nom, chemin in _scripts_concernes():
        sauvegarde = list(sys.path)
        # Le CACHE ment : un nokido_agent deja importe (par un script charge avant, ou par pytest) ferait
        # passer l'import meme sans amorce -- faux vert mesure au 1er essai de ce test (18/10).
        caches = {k: sys.modules.pop(k) for k in list(sys.modules)
                  if k == "nokido_agent" or k.startswith("nokido_agent.")}
        try:
            sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != RACINE]
            nom_mod = "nr_amorce_" + chemin.stem
            spec = importlib.util.spec_from_file_location(nom_mod, chemin)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[nom_mod] = mod  # comme un vrai chargement : @dataclass relit sys.modules[__module__]
            try:
                spec.loader.exec_module(mod)
            except ModuleNotFoundError as e:
                if "nokido_agent" in str(e):
                    manquants.append("%s (%s) : %s" % (nom, chemin.name, e))
                else:
                    illisibles.append("%s : %s" % (nom, e))
            except Exception as e:  # noqa: BLE001 -- autre echec de chargement : DIT, jamais range sain
                illisibles.append("%s : %s %s" % (nom, type(e).__name__, str(e)[:120]))
        finally:
            sys.modules.pop("nr_amorce_" + chemin.stem, None)
            for k in [k for k in sys.modules if k == "nokido_agent" or k.startswith("nokido_agent.")]:
                sys.modules.pop(k, None)
            sys.modules.update(caches)
            sys.path[:] = sauvegarde
    assert not manquants, "services actifs sans amorce de la racine : %s" % manquants
    assert not illisibles, "chargement par chemin en echec (autre cause, a instruire) : %s" % illisibles
