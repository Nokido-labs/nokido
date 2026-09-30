# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/chemins-muets"
PATCH : les chemins muets de `app/forge_mcp_registry.py` qui DESARMENT UN GARDE.

Le module compte 47 `except`/`pass` ; le depot en recense 2 349 sur 744 fichiers.
Les etiqueter en masse reviendrait a desarmer le detecteur — c'est le defaut meme
qu'on corrige. On ne traite donc ici QUE les sites ou le silence supprime un
controle ou perd un etat de coordination. Les nettoyages best-effort restent.

Harnais REUTILISE : `forge_patch_muted_paths.appliquer()` (idempotence par
sentinelle, ancre exigee exactement une fois sinon abandon, `compile()` avant
ecriture, sauvegarde horodatee, relecture verifiee).

LES SEPT SITES
==============
- `filter_tools_payload` : FAIL-OPEN sur le controle d'acces. Si le filtrage RBAC
  leve, le payload part COMPLET et l'agent voit des outils que son role masque.
  Le plus grave du lot.
- `min_ring` depuis la base : l'echec bascule sur un barreme code en dur SANS le
  dire — la politique servie n'est plus celle de la base.
- `_lane_acq` : bail non pris => le job tourne HORS admission, un second job peut
  demarrer sur la meme lane (anti-stacking desarme).
- `_lane_rel` : bail non rendu => bail ORPHELIN, toute reprise refusee 2 h en
  designant un detenteur mort. Incident deja paye.
- jeton du superviseur : lu a vide => appel non authentifie plus loin, avec un
  message obscur. Mesure 2026-09-03 : un jeton vide se diagnostique tres mal.
- octroi de privilege (`dev_token`) : l'echec retombe sur `sandboxed`, donc
  fail-CLOSED — DEBUG suffit, mais un dev_token qui ne marche pas doit se voir.
- jeton netcfg depuis fichier : un repli existe juste apres — DEBUG.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_patch_muted_paths import campagne  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"
SENTINELLE = "[rbac] filtrage des outils NON applique"

BLOCS = [
    # 1. RBAC — FAIL-OPEN sur le controle d'acces
    (r'''            if "tools" in payload:
                payload = get_rbac().filter_tools_payload(payload, entity_id, token=token)
        except Exception:
            pass''',
     r'''            if "tools" in payload:
                payload = get_rbac().filter_tools_payload(payload, entity_id, token=token)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[rbac] filtrage des outils NON applique (%s: %s) | consequence: le "
                "payload part COMPLET, l'agent voit des outils que son role devrait "
                "masquer — fail-OPEN sur le controle d'acces",
                type(e).__name__, str(e)[:100])'''),

    # 2. min_ring : la politique servie n'est plus celle de la base
    (r'''                return row[0]  # min_ring depuis DB
        except Exception:
            pass''',
     r'''                return row[0]  # min_ring depuis DB
        except Exception as e:
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[ring] barreme lu en base INDISPONIBLE (%s) | consequence: repli sur "
                "les valeurs codees en dur, la politique appliquee n'est plus celle "
                "de la base", type(e).__name__)'''),

    # 3. bail de lane non pris -> anti-stacking desarme
    (r'''                    _lane_acq(_lane, res["job_id"])
                except Exception:
                    pass''',
     r'''                    _lane_acq(_lane, res["job_id"])
                except Exception as e:
                    import logging as _lg

                    _lg.getLogger("Nokido.Registry").warning(
                        "[lane] bail NON pris sur %s (%s) | consequence: le job tourne "
                        "hors admission, un second job peut demarrer sur la meme lane",
                        _lane, type(e).__name__)'''),

    # 4. bail non rendu -> bail orphelin, reprise refusee 2 h
    (r'''                            _lane_rel(lane, jid)
                        except Exception:
                            pass''',
     r'''                            _lane_rel(lane, jid)
                        except Exception as e:
                            import logging as _lg

                            _lg.getLogger("Nokido.Registry").warning(
                                "[lane] bail NON rendu sur %s (%s) | consequence: bail "
                                "ORPHELIN, toute reprise refusee jusqu'au TTL en "
                                "designant un detenteur mort", lane, type(e).__name__)'''),

    # 5. jeton superviseur lu a vide -> appel non authentifie plus loin
    (r'''                                    _tok_w = _gs_w("LAFORGE_SUPERVISOR_TOKEN") or ""
                                except Exception:  # noqa: BLE001
                                    pass''',
     r'''                                    _tok_w = _gs_w("LAFORGE_SUPERVISOR_TOKEN") or ""
                                except Exception as e:  # noqa: BLE001
                                    import logging as _lg

                                    _lg.getLogger("Nokido.Registry").warning(
                                        "[superviseur] jeton illisible (%s) | consequence: "
                                        "appel NON authentifie, refus obscur en aval",
                                        type(e).__name__)'''),

    # 6. octroi de privilege : fail-CLOSED, mais doit se voir
    (r'''                        return False, online, "privileged-granted"
            except Exception:  # noqa: BLE001
                pass''',
     r'''                        return False, online, "privileged-granted"
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").debug(
                    "[privilege] octroi dev_token non evalue (%s) — repli fail-CLOSED "
                    "sur sandboxed", type(e).__name__)'''),

    # 7. jeton netcfg depuis fichier : un repli suit
    (r'''                    token = _tf.read_text().strip()
                except Exception:
                    pass''',
     r'''                    token = _tf.read_text().strip()
                except Exception as e:
                    import logging as _lg

                    _lg.getLogger("Nokido.Registry").debug(
                        "[netcfg] jeton fichier illisible (%s) — repli sur Nokido.env",
                        type(e).__name__)'''),
]


def main(argv=None) -> int:
    return campagne(CIBLE, SENTINELLE, BLOCS, suffixe="gardes-muets",
                    note_finale="Le hub doit etre REDEMARRE pour charger ce code.",
                    argv=argv)


if __name__ == "__main__":
    sys.exit(main())
