"""Le garde refuse TOUJOURS un sous-processus -- et il dit desormais par ou passer.

CE QUI A ETE PAYE (2026-09-14). `action=python` interdit `subprocess`, et le message
disait seulement « interdit pour agent zone-restreint ». En mesurant un chemin qui
lance `git`, j'ai donc lu une chaine VIDE et j'ai failli conclure que la capture de
generation etait morte en production -- alors que c'etait mon instrument qui ne
pouvait pas voir. La capacite existait, sous un autre chemin.

    PermissionError: WORKSPACE_GUARD: subprocess.Popen interdit
      -> « le systeme ne peut pas »          (faux, et couteux)
      -> « pas par ICI ; par la, la, ou la »  (vrai, et actionnable)

CE FICHIER NE DESSERRE RIEN, ET C'EST SA PREMIERE FONCTION. Un sous-processus sort
de la portee d'un audit hook : des qu'un binaire externe demarre, plus aucun
confinement applicatif ne s'applique. Le refus est donc BINAIRE par nature, et les
tests ci-dessous existent d'abord pour prouver qu'il le reste. Le message change,
le comportement non.

MISE A JOUR 2026-09-28 (go owner, parite shell). Le refus reste le DEFAUT du header
(`sous_processus=False`) et ces tests le verrouillent. Il ne vaut plus « toujours » :
quand le hub fait tourner le code sous le compte bac a sable -- le meme que
`run action=shell`, qui n'applique aucun filtre de contenu -- il fige la parite dans
le hook et l'enfant est permis. Contrat de la parite :
tests/nr/test_garde_python_parite_shell_nr.py.

On eprouve le comportement dans un SOUS-PROCESSUS, jamais dans le process de test :
`sys.addaudithook` est irreversible, l'installer ici contaminerait toute la session.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.56)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "app") not in sys.path:
    sys.path.insert(0, str(RACINE / "app"))


@pytest.fixture()
def fwg():
    try:
        import forge_workspace_guard
    except Exception as exc:  # noqa: BLE001
        pytest.fail("forge_workspace_guard ne s'importe pas : %s: %s"
                    % (type(exc).__name__, exc))
    return forge_workspace_guard


def _sous_garde(fwg, code: str, zones) -> tuple:
    """Execute `code` precede du header reel, dans un interpreteur neuf."""
    src = fwg.build_run_guard_header([str(z) for z in zones]) + "\n" + code
    p = subprocess.run([sys.executable, "-c", src], capture_output=True,
                       text=True, errors="replace", timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# --------------------------------------------------------------------------
# Le comportement -- inchange, et c'est ce qu'on verifie en premier
# --------------------------------------------------------------------------

def test_le_garde_REFUSE_toujours_un_sous_processus(fwg, tmp_path):
    """La regle de fond : un sous-processus echappe a l'audit hook."""
    rc, sortie = _sous_garde(fwg, "import subprocess, sys\n"
                                  "subprocess.Popen([sys.executable, '-c', 'pass'])\n",
                             [tmp_path])
    assert rc != 0, "le garde a laisse passer un sous-processus"
    assert "WORKSPACE_GUARD" in sortie, sortie[-400:]


def test_l_ecriture_hors_zone_reste_refusee(fwg, tmp_path):
    """L'autre branche du garde ne bouge pas non plus."""
    hors = tmp_path.parent / ("hors_zone_%d.txt" % id(tmp_path))
    rc, sortie = _sous_garde(fwg, "open(%r, 'w').write('x')\n" % str(hors), [tmp_path])
    assert rc != 0 and "WORKSPACE_GUARD" in sortie, sortie[-400:]


def test_l_ecriture_DANS_la_zone_reste_permise(fwg, tmp_path):
    """CONTRE-EPREUVE. Sans elle, un garde qui refuserait TOUT passerait les deux
    tests precedents en ayant casse la capacite qu'il est cense encadrer."""
    dedans = tmp_path / "dedans.txt"
    rc, sortie = _sous_garde(fwg, "open(%r, 'w').write('x')\n" % str(dedans), [tmp_path])
    assert rc == 0, "le garde refuse une ecriture DANS sa zone : %s" % sortie[-400:]
    assert dedans.is_file()


# --------------------------------------------------------------------------
# Le message -- la seule chose qui change
# --------------------------------------------------------------------------

def test_le_refus_NOMME_les_chemins_gouvernes(fwg, tmp_path):
    """Un refus qui ne dit pas par ou passer se lit « le systeme ne peut pas ».

    Les trois chemins existent et portent un confinement PLUS fort (processus
    separe, compte distinct) : le refus doit y renvoyer."""
    _rc, sortie = _sous_garde(fwg, "import subprocess, sys\n"
                                   "subprocess.Popen([sys.executable, '-c', 'pass'])\n",
                              [tmp_path])
    bas = sortie.lower()
    for attendu in ("shell", "run_job", "trusted_script"):
        assert attendu in bas, (
            "le refus ne nomme pas %r : %s" % (attendu, sortie[-500:]))


def test_le_refus_dit_POURQUOI_et_pas_seulement_NON(fwg, tmp_path):
    """Le motif doit etre la raison TECHNIQUE, pas une etiquette de role.

    « zone-restreint » dit qui je suis ; ce qu'il faut savoir, c'est qu'un
    sous-processus SORT de la portee du garde -- sinon on cherche a elever ses
    droits au lieu de changer de chemin."""
    _rc, sortie = _sous_garde(fwg, "import subprocess, sys\n"
                                   "subprocess.Popen([sys.executable, '-c', 'pass'])\n",
                              [tmp_path])
    assert "portee" in sortie.lower() or "echappe" in sortie.lower(), sortie[-500:]
