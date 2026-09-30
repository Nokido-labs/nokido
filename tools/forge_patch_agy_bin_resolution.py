# -*- coding: utf-8 -*-
"""One-shot patcher : resolution du binaire AGY dans app/forge_mcp_registry.py.

DEFAUT MESURE (2026-08-28). `agy_run` echoue en
`[WinError 2] Le fichier specifie est introuvable`, ce qui se lit « AGY n'est pas
installe ». Il l'est : `Test-Path %USERPROFILE%\\AppData\\Local\\agy\\bin\\agy.exe`
rend True sous LaForgeTrusted. La cause est que le handler fait
`shutil.which("agy")`, donc cherche dans le PATH du PROCESS HUB — lequel tourne
sous un compte de service, ou le PATH utilisateur de l'owner n'existe pas.

Un binaire present mais hors PATH et un binaire absent rendent ici le MEME
message : c'est un capteur a deux etats la ou il en faut trois. La resolution
devient donc explicite, du plus intentionnel au plus devine :
  1. `LAFORGE_AGY_BIN` — override, la voie propre ;
  2. `shutil.which("agy")` — le PATH, si l'appelant en a un ;
  3. emplacements connus (%LOCALAPPDATA%, puis un chemin en dur qui le DIT) ;
  4. "agy" nu — dernier recours, laisse l'OS trancher.

CRITICAL_FILE -> applique par trusted_script (chemin officiel), memes garanties
que forge_patch_registry_toolscope : exact-match (count==1), idempotence,
compile() AVANT ecriture, newline preserve, abort sans ecrire au moindre
mismatch. Re-runnable.

PREND EFFET AU PROCHAIN REDEMARRAGE DU HUB : forge_mcp_registry est charge
in-process, editer le fichier ne suffit pas.

Run : run action=trusted_script path=tools/forge_patch_agy_bin_resolution.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

OLD = '        agy_bin = shutil.which("agy") or "agy"\n'
NEW = (
    '        # `which` cherche dans le PATH du PROCESS HUB (compte de service) : le\n'
    '        # PATH utilisateur de l\'owner n\'y est pas, donc `agy` est introuvable et\n'
    '        # l\'appel meurt en WinError 2 — ce qui se lit « AGY n\'est pas installe ».\n'
    '        # Mesure 2026-08-28 : le binaire EXISTE et est lisible. Ordre explicite :\n'
    '        # override, PATH, emplacements connus, puis le nom nu en dernier recours.\n'
    '        _agy_connus = [\n'
    '            os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe"),\n'
    '            r"%USERPROFILE%\\AppData\\Local\\agy\\bin\\agy.exe",\n'
    '        ]\n'
    '        agy_bin = (\n'
    '            os.environ.get("LAFORGE_AGY_BIN")\n'
    '            or shutil.which("agy")\n'
    '            or next((p for p in _agy_connus if p and os.path.exists(p)), None)\n'
    '            or "agy"\n'
    '        )\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "LAFORGE_AGY_BIN" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

n = text.count(OLD)
if n != 1:
    print(f"ABORT: motif trouve {n} fois (attendu exactement 1) -> aucune ecriture")
    sys.exit(2)

text = text.replace(OLD, NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError apres patch -> aucune ecriture: {e}")
    sys.exit(4)

open(TARGET, "wb").write(text.replace("\n", nl).encode("utf-8"))
print(f"OK: resolution agy_bin explicite (env > PATH > connus > nom nu), AST valide. newline={nl!r}")
print("RAPPEL: effectif au prochain redemarrage du hub (registry charge in-process).")
