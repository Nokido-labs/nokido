"""NR 2026-10-01 : tools/forge_logboot.py -- un service ecrit LUI-MEME son journal horodate, sans pipe
vers le superviseur (le pool bloquant Deno, plafonne a 4 x coeurs, livrait 51 journaux sur 56 par
paquets). Chemin REEL : un vrai process Python lance par l'amorceur, comme le ferait le superviseur.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGBOOT = ROOT / "tools" / "forge_logboot.py"
HORODATE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")

CIBLE = '''
import os, subprocess, sys
print("ligne-print")
sys.stderr.write("ligne-stderr\\n")
os.write(1, b"ligne-fd-brut\\n")
subprocess.call([sys.executable, "-c", "print('ligne-enfant')"])
raise ValueError("boom-final")
'''


def _lancer(tmp_path, cible_args, contenu=CIBLE):
    script = tmp_path / "service_factice.py"
    script.write_text(contenu, encoding="utf-8")
    journal = tmp_path / "Service.log"
    rc = subprocess.run([sys.executable, str(LOGBOOT), "--journal", str(journal), "--", *cible_args(script)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60).returncode
    return rc, journal.read_text(encoding="utf-8", errors="replace").splitlines()


def test_toutes_les_sorties_arrivent_horodatees_et_le_code_de_sortie_passe(tmp_path):
    rc, lignes = _lancer(tmp_path, lambda s: [str(s)])
    texte = "\n".join(lignes)
    for attendu in ("ligne-print", "ligne-stderr", "ligne-fd-brut", "ligne-enfant", "ValueError: boom-final"):
        assert attendu in texte, "%s absent du journal :\n%s" % (attendu, texte)
    assert rc == 1, "une exception non rattrapee doit sortir en code 1 (rc=%s)" % rc
    assert lignes and all(HORODATE.match(l) for l in lignes), "ligne non horodatee :\n%s" % texte


def test_un_service_qui_reemballe_stdout_ne_casse_pas(tmp_path):
    """Regression du 2026-10-01 en PRODUCTION (NokidoHomeostasis, ligne 834 de son orchestrateur) :
    `sys.stdout = TextIOWrapper(sys.stdout.buffer, ...)` partageait notre tampon ; notre enveloppe,
    plus referencee, etait detruite par le ramasse-miettes et FERMAIT ce tampon -> `ValueError: I/O
    operation on closed file` au print suivant, code 1 en 3 s, en boucle."""
    contenu = ("import gc, io, sys\n"
               "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
               "sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')\n"
               "gc.collect()\n"
               "print('apres-reemballage', flush=True)\n")
    rc, lignes = _lancer(tmp_path, lambda s: [str(s)], contenu=contenu)
    texte = "\n".join(lignes)
    assert rc == 0 and "apres-reemballage" in texte, (rc, texte)


def test_le_mode_module_et_le_code_de_sortie_explicite(tmp_path):
    paquet = tmp_path / "paquet_factice"
    paquet.mkdir()
    (paquet / "__init__.py").write_text("", encoding="utf-8")
    (paquet / "__main__.py").write_text("import sys\nprint('via-module', sys.argv[1:])\nsys.exit(3)\n",
                                        encoding="utf-8")
    journal = tmp_path / "Mod.log"
    rc = subprocess.run([sys.executable, str(LOGBOOT), "--journal", str(journal), "--", "-m", "paquet_factice", "x"],
                        cwd=str(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60).returncode
    texte = journal.read_text(encoding="utf-8", errors="replace")
    assert rc == 3 and "via-module ['x']" in texte, (rc, texte)


def test_le_journal_est_taille_comme_par_le_superviseur(tmp_path):
    journal = tmp_path / "Gros.log"
    journal.write_bytes(b"x" * (6 * 1024 * 1024))
    script = tmp_path / "rien.py"
    script.write_text("print('apres-taille')\n", encoding="utf-8")
    subprocess.run([sys.executable, str(LOGBOOT), "--journal", str(journal), "--", str(script)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    assert journal.stat().st_size < 2_100_000, "le journal de 6 Mo n'a pas ete taille a ~2 Mo"
    assert "apres-taille" in journal.read_text(encoding="utf-8", errors="replace")


def test_une_forme_d_appel_invalide_est_refusee(tmp_path):
    p = subprocess.run([sys.executable, str(LOGBOOT), "--journal", str(tmp_path / "x.log")],
                       capture_output=True, text=True, errors="replace", timeout=60)
    assert p.returncode != 0 and "usage" in (p.stdout + p.stderr)
