#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/patch_reflex_gate.py — le garde anti-reinvention, en AVERTISSEMENT.

Sans prefixe `forge_` : patcher ONE-SHOT, pas un organe (le cliquet de
couverture NR ne surveille que les `forge_*`, et un script jetable n'a pas a
reclamer un test permanent).

DEUX GREFFES dans `app/forge_mcp_registry.py`, qui est un CRITICAL_FILE :
`governed_edit` le refuse, et `allow_critical` avait coupe le hub le 2026-08-27.
La voie est donc un patcher git-tracke lance en `trusted_script`, hors du
process du hub — meme montage que `patch_introspect_tool.py`.

  1. `handle_introspect` NOTE la consultation (qui, quand, quelle question).
  2. `handle_governed_edit` regarde s'il y en a eu une recemment, COMPTE les
     deux cas, et ajoute un avertissement au verdict quand il n'y en a pas.

POURQUOI AVERTIR ET NON REFUSER, POUR L'INSTANT. Piege consigne le 2026-08-01
sur ce site exact : « un garde qui crie a faux se fait desarmer ». On ne connait
pas encore le taux d'editions legitimes sans consultation prealable. On le
MESURE (`forge_introspect --taux`), et le refus se decidera sur ce chiffre.

Le garde n'agit que sur une ecriture REUSSIE : avertir sur un refus ajouterait
du bruit a une erreur, et c'est exactement ainsi qu'un garde devient du bruit.

IDEMPOTENT, ancres verifiees uniques, resultat COMPILE avant ecriture, ecriture
atomique.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

NOTE_ANCRE = '''        try:
            res = await _aio.to_thread(_intro, q, budget)
        except Exception as e:  # noqa: BLE001
            return f"ERR: {type(e).__name__}: {e}"
        return _json.dumps(res, ensure_ascii=False)
'''
NOTE_AJOUT = '''        try:
            res = await _aio.to_thread(_intro, q, budget)
        except Exception as e:  # noqa: BLE001
            return f"ERR: {type(e).__name__}: {e}"
        try:
            from forge_introspect import noter_consultation as _noter

            _noter(agent, q)
        except Exception:  # noqa: BLE001 - muet-ok : la trace ne casse jamais l'appel
            pass
        return _json.dumps(res, ensure_ascii=False)
'''

GARDE_ANCRE = '''        self.state_mgr.add_notification(f"governed_edit: {path.name}", source=agent)
        import json as _j

        return _j.dumps(verdict, ensure_ascii=False)
'''
GARDE_AJOUT = '''        self.state_mgr.add_notification(f"governed_edit: {path.name}", source=agent)
        import json as _j

        # GARDE ANTI-REINVENTION, en AVERTISSEMENT (2026-08-31). On MESURE avant
        # de refuser : un garde pose sans connaitre son taux de fausse alerte se
        # fait desarmer au premier cri a faux -- piege consigne sur CE site le
        # 2026-08-01. N'agit que sur une ecriture REUSSIE : avertir sur un refus
        # ajouterait du bruit a une erreur.
        try:
            from forge_introspect import consultation_recente, noter_edition

            _c = consultation_recente(agent)
            noter_edition(agent, _c["vu"])
            if not _c["vu"]:
                verdict["avertissement_reflexe"] = (
                    "aucune consultation `introspect` %s avant cette ecriture. "
                    "Nokido a peut-etre deja une procedure pour ce probleme : "
                    "l'interroger AVANT d'ecrire evite de reinventer."
                    % ("recente (%s s)" % _c["age_s"] if _c["etat"] == "PERIMEE"
                       else "sur cette session"))
        except Exception as _e:  # noqa: BLE001 - la trace ne casse jamais l'edition
            verdict["avertissement_reflexe_indisponible"] = type(_e).__name__

        return _j.dumps(verdict, ensure_ascii=False)
'''

# Troisieme greffe (2026-08-31, question Q1) : sans le RESULTAT cote
# consultation et le CHEMIN cote ecriture, on ne peut pas distinguer « l'agent
# a consulte » de « l'agent a REUTILISE ce qu'on lui a propose ». Les deux
# ancres sont les lignes posees par les greffes precedentes.
LIEN_ANCRE = "            _noter(agent, q)\n"
LIEN_AJOUT = "            _noter(agent, q, res)\n"

CHEMIN_ANCRE = '            noter_edition(agent, _c["vu"])\n'
CHEMIN_AJOUT = '            noter_edition(agent, _c["vu"], str(path))\n'

# Cinquieme greffe (question Q3) : une capacite PROUVEE est un invariant. La
# toucher doit etre signale AU MOMENT de l'ecriture, avec le test qui permet de
# verifier qu'elle tient encore -- sinon la preuve existe et ne sert a personne.
INVARIANT_ANCRE = ('        except Exception as _e:  # noqa: BLE001 - la trace ne '
                   'casse jamais l\'edition\n'
                   '            verdict["avertissement_reflexe_indisponible"] = '
                   'type(_e).__name__\n')
INVARIANT_AJOUT = ('        except Exception as _e:  # noqa: BLE001 - la trace ne '
                   'casse jamais l\'edition\n'
                   '            verdict["avertissement_reflexe_indisponible"] = '
                   'type(_e).__name__\n'
                   '''
        # INVARIANT HISTORIQUE. On SAIT que cette capacite marchait, et on sait
        # avec quel test le verifier. Ne pas le dire ici reviendrait a posseder
        # la preuve sans jamais s'en servir.
        try:
            from forge_success_oplog import capacites_touchees

            _cap = capacites_touchees([str(path)])
            if _cap:
                _tests = sorted({t for c in _cap for t in c["tests"]})
                verdict["capacites_prouvees_touchees"] = _cap[:3]
                verdict["avertissement_invariant"] = (
                    "cette ecriture touche le perimetre de %d capacite(s) PROUVEE(s). "
                    "Ce n'est pas un changement ordinaire : rejouer %s avant de "
                    "committer." % (len(_cap), ", ".join(_tests) or "leurs tests"))
        except Exception as _e:  # noqa: BLE001 - jamais bloquer une edition
            verdict["invariant_indisponible"] = type(_e).__name__
''')

GREFFES = [
    ("noter_consultation as _noter", NOTE_ANCRE, NOTE_AJOUT),
    ("avertissement_reflexe", GARDE_ANCRE, GARDE_AJOUT),
    ("_noter(agent, q, res)", LIEN_ANCRE, LIEN_AJOUT),
    ('noter_edition(agent, _c["vu"], str(path))', CHEMIN_ANCRE, CHEMIN_AJOUT),
    ("avertissement_invariant", INVARIANT_ANCRE, INVARIANT_AJOUT),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # muet-ok : sortie non reconfigurable
        pass
    if not CIBLE.exists():
        print("ERR cible introuvable:", CIBLE)
        return 2
    texte = origine = CIBLE.read_text(encoding="utf-8")
    faits, deja, rates = 0, 0, []

    for marque, ancre, ajout in GREFFES:
        if marque in texte:
            deja += 1
            continue
        n = texte.count(ancre)
        if n != 1:
            # 0 = l'ancre a bouge ; >1 = on greffe au hasard. Un patch pose au
            # mauvais endroit dans le registre coute plus cher qu'un patch non
            # pose : on refuse, on ne devine pas.
            rates.append("%s: ancre vue %d fois" % (marque, n))
            continue
        texte = texte.replace(ancre, ajout)
        faits += 1

    if rates:
        print("REFUS - ancres non fiables :")
        for r in rates:
            print("   ", r)
        return 3
    if not faits:
        print("rien a faire : %d greffe(s) deja presente(s)" % deja)
        return 0
    try:
        compile(texte, str(CIBLE), "exec")
    except SyntaxError as exc:  # muet-ok : la raison est imprimee, puis rc=4
        print("REFUS - le resultat ne compile pas : %s" % exc)
        return 4

    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), prefix=CIBLE.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(texte)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, CIBLE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # muet-ok : temporaire deja disparu
        raise
    print("OK %d greffe(s), %d deja presente(s) | %d -> %d octets"
          % (faits, deja, len(origine), len(texte)))
    print("Redemarrer le hub pour charger le garde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
