#!/usr/bin/env python3
"""Patch : rendre parlants les `except` muets de `app/forge_sandbox_exec.py`.

Motif recidivant (74x depuis mai) et paye cher le 2026-09-03 : le `except` du pont
stdio servait un secret revoque en silence, ce qui a coute des heures. Un chemin
d'erreur muet ne se contente pas de cacher une erreur -- il fait passer un garde
DESARME pour un garde qui autorise.

Tri applique ici, en trois classes :
  GARDE     l'echec desarme une protection -> WARNING (il doit crier)
  DEGRADE   l'echec perd de l'information  -> DEBUG   (tracable sans bruit)
  MUET-OK   l'echec n'a aucune consequence -> marque `# muet-ok`, pas de log

On n'ajoute AUCUN import au module (execution privilegiee) : `import logging as _lg`
local, idiome deja utilise dans forge_mcp_registry.

IDEMPOTENT : sort 0 sans rien ecrire si la marque est deja la. Chaque motif doit
apparaitre le nombre EXACT de fois attendu, sinon on s'arrete sans ecrire.
"""

from __future__ import annotations

import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_sandbox_exec.py"
MARQUE = "Nokido.Sandbox"

# (attendu, ancien, nouveau)
BLOCS: list[tuple[int, str, str]] = [
    # ── GARDE : le homeostat RAM. S'il casse, plus personne n'est freine et
    #    l'absence de frein est indiscernable d'un feu vert.
    (1,
     '            return False   # bord de l\'OOM : plus personne ne passe, sonde comprise\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n',
     '            return False   # bord de l\'OOM : plus personne ne passe, sonde comprise\n'
     '    except Exception as _e:  # noqa: BLE001\n'
     '        import logging as _lg\n'
     '        _lg.getLogger("Nokido.Sandbox").warning(\n'
     '            "garde RAM AVEUGLE (%s) — le throttle ne s\'applique pas", type(_e).__name__)\n'),
    # ── GARDE : le throttle lui-meme.
    (1,
     '                        "top_procs": (snap.get("top_procs") or [])[:3],\n'
     '                    }\n'
     '        except Exception:\n'
     '            pass\n',
     '                        "top_procs": (snap.get("top_procs") or [])[:3],\n'
     '                    }\n'
     '        except Exception as _e:\n'
     '            import logging as _lg\n'
     '            _lg.getLogger("Nokido.Sandbox").warning(\n'
     '                "throttle P1 INOPERANT (%s) — spawn autorise sans gate", type(_e).__name__)\n'),
    # ── DEGRADE : l'evenement de throttle n'est pas emis (observabilite).
    (1,
     '                         classe=_classe, cmd=command[:120], ram_pct=snap.get("ram_pct"))\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n',
     '                         classe=_classe, cmd=command[:120], ram_pct=snap.get("ram_pct"))\n'
     '    except Exception as _e:  # noqa: BLE001\n'
     '        import logging as _lg\n'
     '        _lg.getLogger("Nokido.Sandbox").debug(\n'
     '            "evenement de throttle non emis: %s", type(_e).__name__)\n'),
    # ── DEGRADE : effacement du mot de passe en memoire (hygiene).
    (1,
     '            pwd = "\\x00" * len(pwd)  # type: ignore[assignment]\n'
     '        except Exception:\n'
     '            pass\n',
     '            pwd = "\\x00" * len(pwd)  # type: ignore[assignment]\n'
     '        except Exception as _e:\n'
     '            import logging as _lg\n'
     '            _lg.getLogger("Nokido.Sandbox").debug(\n'
     '                "effacement du secret en memoire non confirme: %s", type(_e).__name__)\n'),
    # ── DEGRADE x3 : sans trace_id, la trace de l'enfant ne se correle plus.
    (3,
     '            env["LAFORGE_TRACE_ID"] = get_trace_id()\n'
     '        except Exception:\n'
     '            pass\n',
     '            env["LAFORGE_TRACE_ID"] = get_trace_id()\n'
     '        except Exception as _e:\n'
     '            import logging as _lg\n'
     '            _lg.getLogger("Nokido.Sandbox").debug(\n'
     '                "trace_id non propage a l\'enfant: %s", type(_e).__name__)\n'),
    # ── DEGRADE : « aucune session interactive » et « je n'ai pas pu regarder »
    #    ne doivent pas rendre le meme None.
    (1,
     '                break\n'
     '    except Exception:\n'
     '        pass\n'
     '    if sid is None:\n',
     '                break\n'
     '    except Exception as _e:\n'
     '        import logging as _lg\n'
     '        _lg.getLogger("Nokido.Sandbox").debug(\n'
     '            "enumeration des sessions ILLISIBLE (%s) — sid inconnu, pas absent",\n'
     '            type(_e).__name__)\n'
     '    if sid is None:\n'),
    # ── DEGRADE : sans cwd, le spawn echouera plus loin avec un message obscur.
    (1,
     '            os.makedirs(child_cwd, exist_ok=True)\n'
     '        except Exception:\n'
     '            pass\n',
     '            os.makedirs(child_cwd, exist_ok=True)\n'
     '        except Exception as _e:\n'
     '            import logging as _lg\n'
     '            _lg.getLogger("Nokido.Sandbox").debug(\n'
     '                "cwd enfant non cree (%s) — le spawn echouera plus loin", type(_e).__name__)\n'),
    # ── MUET-OK : menage best-effort, l'echec n'a aucune consequence.
    (1,
     '            f.unlink()\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n',
     '            f.unlink()\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass  # muet-ok : menage best-effort, le fichier temporaire survit au pire\n'),
    (1,
     '            win32api.CloseHandle(proc)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n',
     '            win32api.CloseHandle(proc)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass  # muet-ok : handle deja ferme ou process disparu\n'),
    (1,
     '        out_f.unlink()\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n',
     '        out_f.unlink()\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass  # muet-ok : menage best-effort, la sortie est deja lue\n'),
]


def main() -> int:
    if not CIBLE.is_file():
        print("ABSENT : %s" % CIBLE)
        return 2
    txt = CIBLE.read_text(encoding="utf-8")
    if MARQUE in txt:
        print("DEJA APPLIQUE (marque %s presente) — aucune ecriture." % MARQUE)
        return 0

    for i, (attendu, vieux, _neuf) in enumerate(BLOCS, 1):
        n = txt.count(vieux)
        if n != attendu:
            print("STOP bloc %d : %d occurrence(s), %d attendue(s) — rien ecrit." % (i, n, attendu))
            return 3

    neuf_txt = txt
    for attendu, vieux, neuf in BLOCS:
        neuf_txt = neuf_txt.replace(vieux, neuf, attendu)

    try:
        compile(neuf_txt, str(CIBLE), "exec")
    except SyntaxError as e:
        print("STOP : le resultat ne compile pas (%s ligne %s) — rien ecrit." % (e.msg, e.lineno))
        return 4

    CIBLE.write_text(neuf_txt, encoding="utf-8")
    total = sum(a for a, _v, _n in BLOCS)
    print("PATCH APPLIQUE : %d site(s) sur %d bloc(s), %d -> %d octets"
          % (total, len(BLOCS), len(txt.encode("utf-8")), len(neuf_txt.encode("utf-8"))))
    print("Le hub doit etre REDEMARRE pour charger le nouveau code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
