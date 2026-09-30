"""Aucun module du depot ne LANCE un executable depuis une racine temporaire.

Mandat owner du 2026-09-04 : « une copie figee dans C:\\tmp, il faut auditer, c'est
grave, surtout que je n'en voulais plus ».

CE QUE CE GARDE EMPECHE. Un script lance depuis un chemin hors depot echappe a TOUS
les gardes du projet SIMULTANEMENT : il n'est pas dans git (ni revu, ni versionne, ni
couvert par la CI), le git-gate ne le scanne pas, le gate de secrets non plus, et
`trusted_script` — qui refuse un fichier non suivi au motif que « privilege = code
revu » — ne s'y applique pas davantage. Le code relu et le code execute divergent en
silence.

MESURES QUI JUSTIFIENT LE CABLAGE, et non une note de plus :
  2026-07-30  `forge_local_pool_wake` lancait `C:/tmp/wake_llama_native.py` (4 722 o,
              18 juin) quand le depot en portait 11 825 o (26 juillet) : SIX SEMAINES
              d'ecart. La copie etait anterieure au mecanisme d'intention, donc elle
              allumait un cerveau que la regulation evincait aussitot.
  2026-09-04  Ce reveilleur avait ete corrige — mais `forge_backend_power` lancait
              TOUJOURS la meme copie, alors agee de 77 jours, depuis sa table de
              demarrage. Le meme defaut, non vu pendant cinq semaines de plus.
Une note se re-oublie ; un test echoue.

PAR AST, PAS PAR REGEX. Un balayage textuel de la session a classe « lance » deux
mentions en docstring sur cinq detections. On inspecte donc les appels de sous-process
et leurs arguments LITTERAUX : une chaine citee dans un commentaire ou une docstring
n'est pas un argument d'appel, et ne peut donc pas declencher ce garde.

CE QUI RESTE PERMIS, volontairement : ECRIRE dans une racine temporaire (repli quand
le compte n'a pas les droits sur le depot), lire un artefact, ou citer un chemin en
commentaire. Seul le LANCEMENT est interdit.
"""

import ast
import re
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture +
#   ast (l.66)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]

# Racines temporaires, tous volumes. Ne pas coder `C:` en dur : l'audit initial ne
# regardait que ce volume et aurait rendu un « 0 trouve » rassurant pour `D:\Temp`.
_TEMPORAIRE = re.compile(r"^[A-Za-z]:[\\/]{1,2}te?mp[\\/]", re.I)

# Fonctions qui EXECUTENT. `Popen`, `run`, `call`, `check_output`, `startfile`, `system`.
_EXECUTANTS = {"Popen", "run", "call", "check_call", "check_output", "startfile",
               "system", "execv", "execl", "spawnv"}


def _chaines_litterales(noeud) -> list:
    """Toutes les chaines litterales d'un appel, y compris dans une liste d'args."""
    out = []
    for sub in ast.walk(noeud):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _scanner():
    """Rend (lancements, fichiers_lus, illisibles). Le denominateur est RENDU."""
    lancements, illisibles = [], []
    lus = 0
    for dossier in ("app", "tools"):
        base = ROOT / dossier
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            if "_attic" in f.parts:
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="strict")
                arbre = ast.parse(src, filename=str(f))
            except Exception as exc:
                illisibles.append("%s (%s)" % (f.relative_to(ROOT), type(exc).__name__))
                continue
            lus += 1
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue
                fn = noeud.func
                nom = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if nom not in _EXECUTANTS:
                    continue
                for s in _chaines_litterales(noeud):
                    if _TEMPORAIRE.match(s.replace("\\\\", "\\")):
                        lancements.append(
                            "%s:%d lance %r" % (f.relative_to(ROOT), noeud.lineno, s[:80]))
    return lancements, lus, illisibles


def test_le_balayage_est_representatif():
    """Sans denominateur, « 0 lancement » ne se distingue pas de « je n'ai pas lu »."""
    _, lus, illisibles = _scanner()
    assert lus > 500, "balayage non representatif : %d fichiers seulement" % lus
    assert not illisibles, "fichiers non parsables (couverture surestimee) : %r" % (
        illisibles[:5],)


def test_aucun_lancement_depuis_une_racine_temporaire():
    """Le garde. Un executable hors depot ne doit jamais etre lance par le depot."""
    lancements, _, _ = _scanner()
    assert not lancements, (
        "%d module(s) lancent un executable depuis une racine temporaire. Un tel "
        "chemin echappe a git, a la CI, au git-gate et au gate de secrets, et rien "
        "ne signale quand la copie diverge (mesure : 77 jours d'ecart le 2026-09-04). "
        "Pointer le fichier du DEPOT.\n  %s"
        % (len(lancements), "\n  ".join(lancements)))


def test_le_garde_reconnait_bien_un_lancement(tmp_path):
    """Contre-epreuve : sans elle, un garde qui ne detecte RIEN passerait pour vert.

    C'est le defaut paye toute la session — un capteur muet se lit comme rassurant.
    On verifie donc que la detection FONCTIONNE sur un cas fabrique, et qu'elle
    ignore les formes permises (commentaire, docstring, ecriture).
    """
    piege = tmp_path / "faux_module.py"
    piege.write_text(
        'import subprocess\n'
        '# subprocess.run(["py", "C:/tmp/en_commentaire.py"])  <- doit etre IGNORE\n'
        '"""docstring citant C:/tmp/en_docstring.py — doit etre IGNORE."""\n'
        'open(r"C:\\tmp\\ecriture.py", "w")  # ecriture permise\n'
        'subprocess.run(["py", "C:/tmp/vraiment_lance.py"])\n',
        encoding="utf-8")
    arbre = ast.parse(piege.read_text(encoding="utf-8"))
    trouves = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            nom = getattr(noeud.func, "attr", None) or getattr(noeud.func, "id", None)
            if nom in _EXECUTANTS:
                for s in _chaines_litterales(noeud):
                    if _TEMPORAIRE.match(s.replace("\\\\", "\\")):
                        trouves.append(s)
    assert trouves == ["C:/tmp/vraiment_lance.py"], (
        "la detection ne rend pas exactement le lancement reel : %r — soit elle rate "
        "le vrai cas, soit elle accuse un commentaire, une docstring ou une ecriture"
        % (trouves,))
