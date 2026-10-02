"""NR 2026-10-01 : les journaux de service du superviseur Deno n'empruntent plus le pool BLOQUANT.

Le pool bloquant de Deno est sature par les pipes des enfants (un thread par pipe lu, mesure du 24/09) :
toute E/S asynchrone y attend sans fin. Mesure du 01/10 : 53 services en marche, aucun journal de service
ecrit depuis > 10 min, tous figes juste apres le redemarrage de la pile, pendant que le journal du
superviseur (console.log, synchrone) continuait. Garde textuel sur les deux fonctions concernees.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8")


def _corps(nom):
    m = re.search(r"\n(?:async\s+)?function\s+%s\b" % nom, SRC)
    assert m, "fonction %s introuvable dans supervisor.ts" % nom
    suite = SRC[m.end():]
    fin = re.search(r"\n(?:async\s+)?function\s+\w+", suite)
    return suite[: fin.start() if fin else len(suite)]


def _code(corps):
    # le code seulement : les commentaires CITENT l'ancienne forme
    return "\n".join(l for l in corps.splitlines() if not l.strip().startswith("//"))


def test_openlog_n_a_plus_d_e_s_asynchrone():
    code = _code(_corps("openLog"))
    assert not re.search(r"await\s+(Deno\.|fr\.)", code), "openLog attend encore le pool bloquant"
    assert "Deno.openSync" in code


def test_un_service_logboot_est_lance_sans_pipe():
    """Lecture pipee = un thread du pool bloquant Deno (plafond 4 x coeurs) : 114 lectures pour 64
    threads mesurees le 01/10. Un service logboot tient son journal lui-meme et n'est PAS pipe."""
    corps = _code(_corps("_argsLogboot"))
    assert "forge_logboot" in SRC and "--journal" in corps
    assert "_EST_PYTHON" in corps, "une commande non Python doit etre ecartee, pas amorcee"
    assert re.search(r'stdout:\s*sansPipe\s*\?\s*"null"\s*:\s*"piped"', SRC)
    assert re.search(r'stderr:\s*sansPipe\s*\?\s*"null"\s*:\s*"piped"', SRC)
    assert re.search(r"sansPipe\s*\?\s*null\s*:\s*await openLog", SRC), "Deno ne doit pas ouvrir le journal"


def test_le_chargeur_lit_le_drapeau_logboot():
    loader = (ROOT / "proxy_deno" / "core" / "service_loader.ts").read_text(encoding="utf-8")
    assert "logboot?: boolean" in loader and "svc.logboot = true" in loader


def test_pipetolog_ecrit_en_synchrone_jusqu_au_dernier_octet():
    code = _code(_corps("pipeToLog"))
    assert "await file.write" not in code, "pipeToLog ecrit encore par le pool bloquant"
    assert "writeSync" in code and "while" in code, "ecriture synchrone sans boucle : fin de ligne perdue"
