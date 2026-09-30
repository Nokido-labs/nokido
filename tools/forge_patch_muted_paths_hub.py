# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/chemins-muets"
PATCH : chemins d'erreur muets de `tools/nokido_hub.py` (fichier CRITIQUE).

Reutilise le harnais de `forge_patch_muted_paths.appliquer()` — sentinelle
d'idempotence, ancres exactement une fois sinon abandon, `compile()` avant ecriture,
sauvegarde horodatee, relecture verifiee, dry-run par defaut. Une seconde copie du
harnais finirait par diverger, et c'est sur les fichiers critiques qu'une divergence
coute le plus cher.

LES ONZE SITES, ET POURQUOI ILS COMPTENT
========================================
- `_log_network` x2 : le journal du trafic. Une ligne perdue en silence, c'est un
  TROU dans la seule source qui permette de dire qui appelle le hub — celle-la meme
  qui a servi le 2026-08-05 a nommer les emetteurs anonymes.
- `_write_agent_presence` x2 : une presence non ecrite se lit « agent absent ».
- `_write_safe` : `except ImportError: pass` sur le module d'AUTORISATION d'ecriture.
  Si `forge_mcp_security` ne s'importe pas, l'ecriture passe SANS controle et rien
  ne le dit. C'est un contournement de garde, pas une degradation.
- `_ingest_local_dir` x4 : fichiers ignores, illisibles, chunks perdus, et surtout
  la reconstruction FTS. Un filtre qui ecarte des donnees doit le DIRE, sinon la
  couverture est surestimee en silence — et un index FTS non reconstruit sert
  l'ANCIEN texte sans jamais lever d'erreur.
- `api_ingest` : un `except:` NU attrapait aussi KeyboardInterrupt ; typage explicite.
- `_boot_emit_to_analysis` : le rapport de boot perdu.

    LAFORGE_PYTHON tools/forge_patch_muted_paths_hub.py            # dry-run
    LAFORGE_PYTHON tools/forge_patch_muted_paths_hub.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_patch_muted_paths import appliquer  # noqa: E402

CIBLE = ROOT / "tools" / "nokido_hub.py"
SENTINELLE = "trou dans la seule source"

BLOCS = [
    # 1. _log_network : lecture du payload -> compteurs de tokens fausses en silence
    (r'''                _provider = _po.get("provider") or None
        except Exception:
            pass''',
     r'''                _provider = _po.get("provider") or None
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _n = getattr(_log_network, "_pertes_payload", 0) + 1
            _log_network._pertes_payload = _n
            if _n == 1 or _n % 200 == 0:
                _lg.getLogger("forge.hub").warning(
                    "[network_log] payload illisible (%s: %s) — %d fois | consequence: "
                    "tokens, modele et provider restent a leur defaut, la comptabilite "
                    "d'usage SOUS-ESTIME le trafic reel",
                    type(e).__name__, str(e)[:80], _n)'''),

    # 2. _log_network : l'ECRITURE du journal. Le plus grave du fichier.
    (r'''            client_ip=client_ip,
        )
    except Exception:
        pass''',
     r'''            client_ip=client_ip,
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _n = getattr(_log_network, "_pertes", 0) + 1
        _log_network._pertes = _n
        if _n == 1 or _n % 100 == 0:
            _lg.getLogger("forge.hub").error(
                "[network_log] evenement NON journalise (%s: %s) — %d perdu(s) | "
                "consequence: un trou dans la seule source qui dise QUI appelle le "
                "hub ; toute mesure de trafic ou d'identite tiree de ce journal est "
                "alors incomplete", type(e).__name__, str(e)[:80], _n)'''),

    # 3. presence : residu de l'ancien emplacement non retire
    (r'''            (_SANDBOX / f"{agent.lower()}.heartbeat").unlink(missing_ok=True)
        except Exception:
            pass''',
     r'''            (_SANDBOX / f"{agent.lower()}.heartbeat").unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("forge.hub").warning(
                "[presence] ancien heartbeat de %s NON retire (%s: %s) | consequence: "
                "ce residu reste dans le glob de l'anatomie et vieillit en silence "
                "comme un organe mort", agent, type(e).__name__, str(e)[:80])'''),

    # 4. presence : l'ecriture elle-meme -> l'agent parait ABSENT
    (r'''            encoding="utf-8",
        )
    except Exception:
        pass''',
     r'''            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.hub").warning(
            "[presence] presence de %s NON ecrite (%s: %s) | consequence: cet agent "
            "sera lu comme ABSENT alors qu'il vient d'appeler le hub",
            agent, type(e).__name__, str(e)[:80])'''),

    # 5. api_ingest : `except:` NU -> attrapait aussi KeyboardInterrupt
    (r'''                    lf_prio = int(parts[4]) if len(parts) > 4 else 5
                except:
                    pass''',
     r'''                    lf_prio = int(parts[4]) if len(parts) > 4 else 5
                except (ValueError, IndexError):  # muet-ok : priorite malformee ->
                    # on garde le defaut 5, comportement voulu et sans perte. Le
                    # `except:` NU d'avant attrapait aussi KeyboardInterrupt et
                    # SystemExit, donc il pouvait avaler un arret demande.
                    pass'''),

    # 6. SECURITE : le module d'autorisation d'ecriture absent -> ecriture NON gardee
    (r'''                        _acw(str(p.resolve()), "CLAUDE", 0)
                    except ImportError:
                        pass''',
     r'''                        _acw(str(p.resolve()), "CLAUDE", 0)
                    except ImportError as e:
                        import logging as _lg

                        # CONTOURNEMENT DE GARDE, pas une degradation : sans ce
                        # module, l'ecriture se poursuit SANS controle d'autorisation.
                        # Un garde absent qui ne le dit pas est pire qu'un garde
                        # absent : le systeme se relit comme protege.
                        _lg.getLogger("forge.hub").error(
                            "[securite] forge_mcp_security INDISPONIBLE (%s) — "
                            "l'ecriture de %s se poursuit SANS controle "
                            "d'autorisation | consequence: le garde d'ecriture est "
                            "inactif et rien d'autre ne le signale", e, p)'''),

    # 7. ingestion : un fichier ILLISIBLE n'est pas un fichier trop gros. Le premier
    # est un accident a signaler, le second un filtre voulu qui n'a rien a dire.
    (r'''            try:
                if p.stat().st_size > MAX_FILE:
                    continue
            except OSError:
                continue
            files.append(p)''',
     r'''            try:
                if p.stat().st_size > MAX_FILE:
                    continue   # filtre VOULU : au-dela de MAX_FILE on n'ingere pas
            except OSError as e:
                import logging as _lg

                _lg.getLogger("forge.hub").warning(
                    "[ingest] %s non examinable (%s: %s) — ecarte | consequence: ce "
                    "chemin n'est ni ingere ni compte comme refuse, il DISPARAIT du "
                    "perimetre sans laisser de trace", p, type(e).__name__, str(e)[:80])
                continue
            files.append(p)'''),

    (r'''                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue''',
     r'''                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("forge.hub").warning(
                    "[ingest] %s ILLISIBLE (%s: %s) — ecarte | consequence: ce fichier "
                    "n'est PAS dans l'index, et son absence des resultats ne veut pas "
                    "dire qu'il n'existe pas", p, type(e).__name__, str(e)[:80])
                continue'''),

    # 9. chunk perdu a l'insertion
    (r'''                    if cur.rowcount:
                        inserted += 1
                except Exception:
                    pass''',
     r'''                    if cur.rowcount:
                        inserted += 1
                except Exception as e:  # noqa: BLE001
                    import logging as _lg

                    _lg.getLogger("forge.hub").warning(
                        "[ingest] chunk NON insere pour %s (%s: %s) | consequence: ce "
                        "fragment est absent de l'index, la couverture annoncee est "
                        "superieure a la couverture reelle",
                        src, type(e).__name__, str(e)[:80])'''),

    # 10. reconstruction FTS : le lexical sert l'ANCIEN texte, sans erreur visible
    (r'''            cur.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
            con.commit()
        except Exception:
            pass''',
     r'''            cur.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
            con.commit()
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Le lexical PRIME dans la recherche. Un index non reconstruit sert
            # l'ANCIEN texte sans jamais lever d'erreur — mesure du 2026-07-29 :
            # lexical mort sur 99,5 % du corpus, invisible pendant des semaines.
            _lg.getLogger("forge.hub").error(
                "[ingest] reconstruction FTS ECHOUEE (%s: %s) | consequence: la "
                "recherche lexicale sert un index PERIME sur ce qui vient d'etre "
                "ingere, sans erreur visible", type(e).__name__, str(e)[:100])'''),

    # 11. rapport de boot perdu
    (r'''            )
        except Exception:
            pass
        boot_finalize(ring=ring)''',
     r'''            )
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("forge.hub").warning(
                "[boot] rapport d'analyse NON emis (%s: %s) | consequence: ce demarrage "
                "n'apparaitra pas dans l'historique de boot, et son absence se lira "
                "comme un boot qui n'a pas eu lieu", type(e).__name__, str(e)[:80])
        boot_finalize(ring=ring)'''),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Chemins muets du hub souverain")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    return appliquer(CIBLE, SENTINELLE, BLOCS, a.apply, suffixe="muets-hub",
                     note_finale="Effet au prochain REDEMARRAGE du hub.")


if __name__ == "__main__":
    raise SystemExit(main())
