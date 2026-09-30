#!/usr/bin/env python3
"""Patch : second lot des `except` muets de `app/forge_sandbox_exec.py`.

Le premier lot a traite les sites que le gate affichait ; il en restait 13, tous
verifies un par un. Douze sont du nettoyage best-effort dont l'echec n'a aucune
consequence observable -- ils recoivent une etiquette `muet-ok` MOTIVEE, pas
generique : etiqueter en masse reviendrait a desarmer le detecteur, ce qui est
exactement le defaut qu'on corrige.

Le treizieme (creation du cwd de l'enfant) passe en DEBUG : son echec fait rater
le spawn plus loin, avec un message obscur.

Chaque site est cible par sa LIGNE et verifie par un FRAGMENT de contexte : si le
fichier a bouge, le fragment ne correspond plus et on s'arrete sans rien ecrire.
Les sites sont appliques du bas vers le haut pour que les numeros ne se decalent
pas. IDEMPOTENT.
"""

from __future__ import annotations

import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_sandbox_exec.py"

# (ligne du `pass`, fragment attendu dans les 3 lignes precedentes, motif d'etiquette)
MUET_OK: list[tuple[int, str, str]] = [
    (84, '_creds_cache[k] =', "purge best-effort, la valeur est deja hors d'usage"),
    (88, "del _creds_cache[k]", "la cle a pu disparaitre entre-temps"),
    (555, "_p.kill()", "process deja mort"),
    (558, "psutil.wait_procs", "l'attente est un confort, le kill a eu lieu"),
    (567, "win32api.CloseHandle(h)", "handle deja ferme"),
    (718, "win32api.CloseHandle(h)", "handle deja ferme"),
    (825, "return h", "repli explicite sur h_in juste en dessous"),
    (869, "win32api.CloseHandle(h)", "handle deja ferme"),
    (945, "return h", "repli explicite sur h_in juste en dessous"),
    (1050, "return h", "repli explicite sur h_in juste en dessous"),
    (1096, "win32api.CloseHandle(h)", "handle deja ferme"),
    (1225, "win32api.CloseHandle(job)", "le job est deja ferme, ses enfants sont tues"),
]

# (ligne du `pass`, fragment attendu, message de log)
EN_DEBUG: list[tuple[int, str, str]] = [
    (958, "os.makedirs(child_cwd",
     "cwd enfant non cree (%s) — le spawn echouera plus loin"),
]


def _verifie(lignes: list[str], n: int, frag: str) -> str | None:
    if not (1 <= n <= len(lignes)):
        return "ligne %d hors fichier" % n
    if lignes[n - 1].strip() != "pass":
        return "L%d n'est pas un `pass` nu : %r" % (n, lignes[n - 1].strip()[:60])
    fenetre = "\n".join(lignes[max(0, n - 4):n])
    if frag not in fenetre:
        return "L%d : contexte %r absent" % (n, frag)
    return None


def main() -> int:
    if not CIBLE.is_file():
        print("ABSENT : %s" % CIBLE)
        return 2
    lignes = CIBLE.read_text(encoding="utf-8").splitlines(keepends=True)
    nus = [l.rstrip("\r\n") for l in lignes]

    a_faire = [(n, f, m, "muet") for n, f, m in MUET_OK] + \
              [(n, f, m, "debug") for n, f, m in EN_DEBUG]
    deja = sum(1 for n, _f, _m, _k in a_faire
               if 1 <= n <= len(nus) and "muet-ok" in nus[n - 1])
    if deja == len(MUET_OK):
        print("DEJA APPLIQUE — aucune ecriture.")
        return 0

    erreurs = [e for n, f, _m, _k in a_faire if (e := _verifie(nus, n, f))]
    if erreurs:
        for e in erreurs:
            print("STOP : %s" % e)
        return 3

    for n, _frag, motif, genre in sorted(a_faire, key=lambda x: -x[0]):
        indent = nus[n - 1][:len(nus[n - 1]) - len(nus[n - 1].lstrip())]
        if genre == "muet":
            lignes[n - 1] = "%spass  # muet-ok : %s\n" % (indent, motif)
        else:
            # le `except` est juste au-dessus du `pass`
            exc = nus[n - 2]
            noqa = "  # noqa: BLE001" if "noqa" in exc else ""
            ind_exc = exc[:len(exc) - len(exc.lstrip())]
            lignes[n - 2] = "%sexcept Exception as _e:%s\n" % (ind_exc, noqa)
            lignes[n - 1] = ('%simport logging as _lg\n%s_lg.getLogger("Nokido.Sandbox").debug(\n'
                             '%s    "%s", type(_e).__name__)\n' % (indent, indent, indent, motif))

    neuf = "".join(lignes)
    try:
        compile(neuf, str(CIBLE), "exec")
    except SyntaxError as e:
        print("STOP : le resultat ne compile pas (%s ligne %s) — rien ecrit." % (e.msg, e.lineno))
        return 4
    CIBLE.write_text(neuf, encoding="utf-8")
    print("PATCH APPLIQUE : %d etiquette(s) muet-ok, %d passage(s) en DEBUG"
          % (len(MUET_OK), len(EN_DEBUG)))
    print("Le hub doit etre REDEMARRE pour charger le nouveau code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
