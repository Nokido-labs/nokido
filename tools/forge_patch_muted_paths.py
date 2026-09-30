# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/chemins-muets"
PATCH : rend visibles les chemins d'erreur muets des FICHIERS CRITIQUES.

POURQUOI UN SCRIPT
==================
`app/forge_mcp_registry.py` et `tools/nokido_hub.py` sont `CRITICAL_FILE` :
`governed_edit` les refuse, et `LAFORGE_ALLOW_CRITICAL_WRITE` vit dans
l'environnement du hub, qui ne se recharge pas a chaud. La voie prevue est donc un
script git-tracke lance en `trusted_script` — doctrine « privilege = code revu ».

CE QU'IL CORRIGE
================
Recensement du 2026-08-05 : **2 349 chemins d'erreur muets** dans le code vivant
(744 fichiers), dont **226** dans des fonctions dont le nom porte une perte. Ce
script traite les plus graves du registre MCP, chacun selon sa nature — le silence
n'est pas supprime partout, il est soit REMPLACE par un message qui dit la
CONSEQUENCE, soit DECLARE `# muet-ok` avec sa raison.

Le pire du lot : `_do_ingest` avalait l'echec de `rebuild_fts_index()`. Le lexical
PRIME dans la recherche ; un index FTS non reconstruit sert l'ANCIEN texte sans
jamais lever d'erreur. Mesure du 2026-07-29 : le lexical etait mort sur 99,5 % du
corpus et personne ne l'avait vu.

GARANTIES
=========
Sentinelle d'idempotence, ancres devant apparaitre EXACTEMENT une fois sinon
abandon, `compile()` avant ecriture, sauvegarde horodatee, relecture verifiee,
dry-run par defaut. L'effet est immediat pour un module importe au prochain
chargement ; le hub doit etre redemarre pour recharger son registre.

    LAFORGE_PYTHON tools/forge_patch_muted_paths.py            # dry-run
    LAFORGE_PYTHON tools/forge_patch_muted_paths.py --apply
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Sentinelle : presente => deja applique. On la choisit dans le PREMIER remplacement.
SENTINELLE = "catalogue dynamique"

BLOCS = [
    # 1. catalogue dynamique incomplet -> un client conclut que l'outil n'existe pas
    (r'''                })
        except Exception:
            pass
        return tools''',
     r'''                })
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[catalogue] outils forges NON ajoutes au catalogue dynamique (%s: %s) "
                "| consequence: un client verra un catalogue INCOMPLET et conclura que "
                "l'outil n'existe pas, alors qu'il est seulement invisible",
                type(e).__name__, str(e)[:100])
        return tools'''),

    # 2. bus audit — chemin CHAUD, donc compteur porte par la fonction elle-meme
    (r'''                publish(kind, data, topic="audit")
            except Exception:
                pass''',
     r'''                publish(kind, data, topic="audit")
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                # Chemin CHAUD : deduplication par compteur porte par la fonction,
                # sinon le remede noierait le journal qu'il repare.
                _n = getattr(_emit, "_pertes", 0) + 1
                _emit._pertes = _n
                if _n == 1 or _n % 200 == 0:
                    _lg.getLogger("Nokido.Registry").warning(
                        "[bus] evenement d'AUDIT non publie (%s: %s) — %d perdu(s) | "
                        "consequence: la piste d'audit a des trous et ne peut pas "
                        "servir de preuve", type(e).__name__, str(e)[:80], _n)'''),

    # 3. bus swarm
    (r'''                publish(kind, data, topic="swarm")
            except Exception:
                pass''',
     r'''                publish(kind, data, topic="swarm")
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _n = getattr(_emit, "_pertes", 0) + 1
                _emit._pertes = _n
                if _n == 1 or _n % 200 == 0:
                    _lg.getLogger("Nokido.Registry").warning(
                        "[bus] evenement SWARM non publie (%s: %s) — %d perdu(s) | "
                        "consequence: /forge/swarm affiche un essaim plus calme qu'il "
                        "ne l'est", type(e).__name__, str(e)[:80], _n)'''),

    # 4. avertissements de qualite detectes PUIS perdus
    (r'''                    print(f"\033[33m[DB_QUALITY] {w}\033[0m", flush=True)
            except Exception:
                pass''',
     r'''                    print(f"\033[33m[DB_QUALITY] {w}\033[0m", flush=True)
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning(
                    "[db_quality] avertissements NON restitues (%s: %s) | consequence: "
                    "des defauts de qualite ont ete detectes puis perdus en chemin",
                    type(e).__name__, str(e)[:100])'''),

    # 5. le VALIDATEUR M2M tombe -> le message part NON valide, gouvernance contournee
    (r'''            if _m2m_v.get("code") not in ("M2M_OK", "M2M_OK_PROSE"):
                _m2m_note = f" [{_m2m_v.get('code')}]"
        except Exception:
            pass''',
     r'''            if _m2m_v.get("code") not in ("M2M_OK", "M2M_OK_PROSE"):
                _m2m_note = f" [{_m2m_v.get('code')}]"
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Un VALIDATEUR qui tombe en silence laisse passer le message NON VALIDE :
            # la gouvernance parait active alors qu'elle est contournee.
            _lg.getLogger("Nokido.Registry").error(
                "[m2m] validation du protocole IMPOSSIBLE (%s: %s) — le message part "
                "SANS avoir ete valide | consequence: la conformite M2M annoncee n'est "
                "pas garantie pour ce message", type(e).__name__, str(e)[:100])'''),

    # 6. reveil du drain postal non tente -> courrier qui dort sans que rien ne le dise
    (r'''                        _th_w.Thread(target=_reveiller_drain, daemon=True).start()
            except Exception:
                pass''',
     r'''                        _th_w.Thread(target=_reveiller_drain, daemon=True).start()
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning(
                    "[postal] reveil du drain NON TENTE (%s: %s) | consequence: le "
                    "courrier est depose mais peut rester 'pending' sans que personne "
                    "ne le signale", type(e).__name__, str(e)[:100])'''),

    # 7. fail-open inbox : l'intention etait DECLAREE, l'evenement ne l'etait pas
    (r'''                _INBOX.push(_frame)
            except Exception:
                pass  # fail-open sur inbox''',
     r'''                _INBOX.push(_frame)
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                # fail-open ASSUME : la notification ne doit pas echouer parce que
                # l'inbox est indisponible. Mais l'assumer n'est pas le taire.
                _lg.getLogger("Nokido.Registry").warning(
                    "[inbox] message NON pousse (%s: %s) — notification maintenue "
                    "(fail-open) | consequence: ce message n'apparaitra pas dans "
                    "l'inbox du destinataire", type(e).__name__, str(e)[:100])'''),

    # 8. journal de requetes -> les statistiques d'usage sous-estiment le trafic
    (r'''            cx.commit()
            cx.close()
        except Exception:
            pass''',
     r'''            cx.commit()
            cx.close()
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _n = getattr(_log_query, "_pertes", 0) + 1
            _log_query._pertes = _n
            if _n == 1 or _n % 200 == 0:
                _lg.getLogger("Nokido.Registry").warning(
                    "[query_log] journalisation de requete PERDUE (%s: %s) — %d au "
                    "total | consequence: les statistiques d'usage sous-estiment le "
                    "trafic reel", type(e).__name__, str(e)[:80], _n)'''),

    # 9. LE PLUS GRAVE : index FTS non reconstruit = recherche sur du texte PERIME
    (r'''                        rebuild_fts_index()
                    except Exception:
                        pass''',
     r'''                        rebuild_fts_index()
                    except Exception as e:  # noqa: BLE001
                        import logging as _lg

                        # LE PLUS GRAVE DE CE FICHIER. Le lexical PRIME dans la
                        # recherche : un index FTS non reconstruit sert l'ANCIEN texte
                        # sans jamais lever d'erreur. Mesure du 2026-07-29 : le lexical
                        # etait mort sur 99,5 % du corpus et personne ne l'a vu.
                        _lg.getLogger("Nokido.Registry").error(
                            "[ingest] reconstruction de l'index FTS ECHOUEE (%s: %s) | "
                            "consequence: la recherche lexicale sert un index PERIME "
                            "sur ce qui vient d'etre ingere, sans erreur visible",
                            type(e).__name__, str(e)[:100])'''),
]

CIBLE = ROOT / "app" / "forge_mcp_registry.py"


def appliquer(cible: Path, sentinelle: str, blocs: list, apply: bool,
              suffixe: str = "muets", note_finale: str = "") -> int:
    """Harnais REUTILISABLE de patch d'un fichier critique.

    Expose separement de `main()` pour que d'autres campagnes (le hub, un futur
    organe) l'importent au lieu de recopier ces garanties : une deuxieme copie
    finirait par diverger, et c'est justement sur les fichiers critiques qu'une
    divergence de harnais coute le plus cher.
    """
    if not cible.exists():
        print("[patch] ABANDON — cible absente : %s" % cible)
        return 1
    src = cible.read_text(encoding="utf-8")
    if sentinelle in src:
        print("[patch] %s : DEJA APPLIQUE (sentinelle presente)" % cible.name)
        return 0

    patche = src
    for i, (avant, apres) in enumerate(blocs, 1):
        n = patche.count(avant)
        if n != 1:
            print("[patch] ABANDON — bloc %d vu %d fois (attendu 1)" % (i, n))
            return 1
        patche = patche.replace(avant, apres, 1)
    try:
        compile(patche, str(cible), "exec")
    except SyntaxError as e:
        print("[patch] ABANDON — le resultat ne compile pas (%s ligne %s)" % (e.msg, e.lineno))
        return 1

    print("[patch] cible   : %s (%d -> %d octets)" % (cible.name, len(src), len(patche)))
    print("[patch] blocs   : %d/%d appliques" % (len(blocs), len(blocs)))
    print("[patch] compile : OK")
    if not apply:
        print("[patch] DRY-RUN — relancer avec --apply pour ecrire")
        return 0

    bak = cible.with_suffix(".py.avant-%s-%s.bak" % (suffixe, time.strftime("%Y%m%d-%H%M%S")))
    bak.write_text(src, encoding="utf-8")
    cible.write_text(patche, encoding="utf-8")
    if cible.read_text(encoding="utf-8") != patche:
        cible.write_text(src, encoding="utf-8")
        print("[patch] ABANDON — relecture differente de l'ecriture, restauration faite")
        return 1
    print("[patch] ECRIT. sauvegarde : %s" % bak.name)
    if note_finale:
        print("[patch] %s" % note_finale)
    return 0


def campagne(cible: Path, sentinelle: str, blocs: list, suffixe: str,
             note_finale: str = "", argv=None) -> int:
    """Point d'entree standard d'une campagne de patch. -> code de sortie.

    Expose parce que `appliquer()` ne suffisait pas : chaque campagne recopiait
    les memes quatre lignes de `main()` (lecture d'argv, detection de `--apply`,
    passage des parametres). Le cliquet de duplication l'a attrape des la deuxieme
    copie — c'est exactement ce qu'il doit faire, et le meme raisonnement que pour
    `appliquer()` : une variante du point d'entree finirait par diverger de l'autre,
    sur des fichiers critiques ou la divergence coute le plus cher.
    """
    import sys  # noqa: PLC0415 — le module ne l'importe pas au niveau global

    argv = sys.argv[1:] if argv is None else argv
    return appliquer(cible, sentinelle, blocs, apply="--apply" in argv,
                     suffixe=suffixe, note_finale=note_finale)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rend visibles les chemins muets critiques")
    ap.add_argument("--apply", action="store_true", help="ecrit reellement (defaut : dry-run)")
    a = ap.parse_args(argv)
    return appliquer(CIBLE, SENTINELLE, BLOCS, a.apply,
                     note_finale="Le hub doit etre redemarre pour recharger son registre.")


if __name__ == "__main__":
    raise SystemExit(main())
