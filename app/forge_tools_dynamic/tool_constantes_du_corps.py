"""forge_tool_dynamic: constantes_du_corps
Description: Constantes du corps en LECTURE SEULE -- reglages DECLARES (bornes, defaut, valeur du magasin, qui peut
             changer) a cote des constantes OBSERVEES (forge_physiology). N'ecrit rien.
Signature: (section: str = "tout")
Registered: wrapper manuel (decision owner 15/10 : « oui, lecture seule »)
"""
from __future__ import annotations

# Seul chemin d'ECRITURE d'un reglage L1 : l'applicateur arme, dans les bornes declarees. Un outil MCP qui
# pourrait aussi ecrire mettrait l'interrupteur a portee de ce qu'il contraint -- il ne garderait plus rien.
_QUI_CHANGE_L1 = ("owner : cle sandbox/evolution.armed (portee l1) puis forge_proposal_applier, dans les bornes ; "
                  "le frein sandbox/evolution.halt gagne toujours")


def _lire_hote_direct() -> dict:
    """Hors WASM : lecture directe (meme forme que la donnee passee par l'hote sous WASM)."""
    import sys
    from pathlib import Path

    app = Path(__file__).resolve().parent.parent
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    from nokido_agent.app import forge_proposal_applier as fpa

    try:
        magasin, etat = fpa._lire_l1(), "LU"
    except Exception as exc:  # noqa: BLE001 - un magasin illisible se DIT, il ne retombe pas sur le defaut
        magasin, etat = {}, "ILLISIBLE (%s)" % type(exc).__name__
    return {"params": fpa.PARAMS_L1, "magasin": magasin, "etat_magasin": etat, "fichier": fpa.PARAMS_L1_FICHIER.name}


def _reglages_declares(donnees_hote=None) -> dict:
    """PARAMS_L1 + valeur courante du magasin. Magasin illisible = ILLISIBLE, jamais « defaut ».
    Sous WASM l'outil ne peut rien lire : l'hote passe les donnees ; sans elles = INCONNU (via l'exception)."""
    d = donnees_hote if donnees_hote is not None else _lire_hote_direct()
    if "params" not in d:
        raise RuntimeError(d.get("raison", "donnees hote absentes"))
    magasin, etat_magasin = d["magasin"], d["etat_magasin"]
    out = {}
    for nom, decl in d["params"].items():
        entree = magasin.get(nom)
        courante = entree.get("valeur") if isinstance(entree, dict) else entree
        out[nom] = {
            "defaut": decl.get("defaut"), "min": decl.get("min"), "max": decl.get("max"), "type": decl.get("type"),
            "valeur_magasin": courante,
            "effective": (courante if courante is not None else decl.get("defaut")) if etat_magasin == "LU" else None,
            "source": "app/forge_proposal_applier.py PARAMS_L1 + %s" % d["fichier"],
            "magasin": etat_magasin,
            "mesure": decl.get("mesure"),
            "qui_change": _QUI_CHANGE_L1,
            "usage_par_le_consommateur": "NON OBSERVE ici (declare != observe)",
        }
    return out


def _constantes_observees() -> dict:
    """forge_physiology.constantes() ; indisponible = INCONNU, jamais un zero."""
    import sys
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2]
    for p in (str(racine), str(racine / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import forge_physiology

        return forge_physiology.constantes()
    except Exception as exc:  # noqa: BLE001 - INCONNU dit, pas avale
        return {"etat": "INCONNU", "raison": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


def constantes_du_corps(section: str = "tout", _donnees_hote=None) -> dict:
    """Vue LECTURE SEULE des constantes du corps : `declare`, `observe` ou `tout`. N'ecrit rien, nulle part."""
    section = (section or "tout").strip().lower()
    if section not in ("tout", "declare", "observe"):
        return {"erreur": "section inconnue %r (tout | declare | observe)" % section}
    vue = {"lecture_seule": True,
           "ecriture": "aucune par cet outil -- " + _QUI_CHANGE_L1}
    if section in ("tout", "declare"):
        try:
            vue["declare"] = _reglages_declares(_donnees_hote)
        except Exception as exc:  # noqa: BLE001
            vue["declare"] = {"etat": "INCONNU", "raison": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    if section in ("tout", "observe"):
        vue["observe"] = _constantes_observees()
    return vue
