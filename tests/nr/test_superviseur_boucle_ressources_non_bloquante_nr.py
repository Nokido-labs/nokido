"""NR -- la boucle de ressources du superviseur ne s'accroche a aucune promesse sans borne.

Mesure du 2026-09-24 (journal laforge-master.log) : un seul passage de vitalite
(« PID ... INTROUVABLE ... respawn ») en 18 min pour une boucle cadencee a 60 s, 0 ligne de
regulation RAM interne, pendant que deux PID enregistres `running` n'existaient plus (psutil
NoSuchProcess) -> jamais relances. Cause : `livingPids` et `memUsagePct` attendaient un
`Deno.Command(...).output()` asynchrone ; son pipe se lit sur le pool bloquant, sature par les
~67 enfants (un thread par pipe lu), et la promesse ne se resolvait jamais.
Regle : dans `resourceLoop`, tout `await` vise une fonction BORNEE (liste blanche ci-dessous) ;
les deux sondes lisent en `outputSync` (ou sans sous-processus).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"
PLAT = ROOT / "proxy_deno" / "core" / "platform.ts"
# Chaque entree a ete LUE : delay = minuterie ; fetchTelemetry = AbortController 1,5 s ;
# livingPids / getMemUsagePct = synchrones depuis le 2026-09-24. Ajouter un nom = prouver sa borne.
BORNEES = {"delay", "livingPids", "getMemUsagePct", "fetchTelemetry"}


def _corps(src: str, entete: str) -> str:
    """Corps de la fonction, SANS les commentaires `//` : le commentaire qui explique le
    correctif cite `.output()` -- un instrument ne lit pas son propre vocabulaire (1er rouge)."""
    i = src.index(entete)
    j = src.index("\n}", i)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", src[i:j])


def test_boucle_ressources_n_attend_que_des_fonctions_bornees():
    corps = _corps(SUP.read_text(encoding="utf-8"), "async function resourceLoop()")
    attendus = re.findall(r"await\s+([A-Za-z_]\w*)\s*\(", corps)
    assert attendus, "aucun await lu dans resourceLoop : le lecteur ne voit plus la boucle"
    inconnus = sorted(set(attendus) - BORNEES)
    assert not inconnus, ("await sur une fonction dont la BORNE n'est pas prouvee dans resourceLoop : %s "
                          "(une promesse qui ne se resout pas fige vitalite ET regulation RAM)" % inconnus)
    assert "await new Deno.Command" not in corps


def test_vitalite_lit_tasklist_en_synchrone():
    corps = _corps(SUP.read_text(encoding="utf-8"), "async function livingPids()")
    assert ".outputSync()" in corps and ".output()" not in corps, (
        "livingPids doit lire tasklist en outputSync : l'asynchrone pend sur le pool bloquant sature")
    assert "alive.size > 10 ? alive : null" in corps, "la garde « je n'ai pas pu voir » != « tous morts » a disparu"


def test_ram_windows_sans_pipe_asynchrone():
    src = PLAT.read_text(encoding="utf-8")
    win = re.sub(r"(?m)^\s*//.*$", "", src[src.index('if (OS === "windows")'):src.index('if (OS === "linux")')])
    assert ".output()" not in win and "await new Deno.Command" not in win, (
        "memUsagePct/Windows attend de nouveau un pipe asynchrone")
    assert "systemMemoryInfo" in win and 'typeof d.systemMemoryInfo === "function"' in win, (
        "l'acces a systemMemoryInfo doit rester optionnel (version de Deno non lisible depuis le hub)")
    assert ".outputSync()" in win, "le repli powershell doit rester synchrone"


def test_pouls_de_boucle_et_illisible_dits():
    corps = _corps(SUP.read_text(encoding="utf-8"), "async function resourceLoop()")
    assert "vitalite: passage #" in corps, "la boucle n'a plus de pouls : son blocage redevient invisible"
    assert "tasklist ILLISIBLE" in corps, "un tasklist illisible redevient muet (null lu comme « aucun mort »)"


def test_garde_du_garde():
    faux = ("async function resourceLoop() {\n  // await commentee(1);\n  await delay(1);\n"
            "  await sondeLente(); // x.output()\n}\n")
    corps = _corps(faux, "async function resourceLoop()")
    assert set(re.findall(r"await\s+([A-Za-z_]\w*)\s*\(", corps)) - BORNEES == {"sondeLente"}
    assert ".output()" not in corps, "les commentaires ne sont plus retires : faux rouge garanti"
