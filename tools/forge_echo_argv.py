"""forge_echo_argv.py -- smoke-test pour l'action hub trusted_script.

Affiche sys.argv et le compte d'exécution. Aucun effet de bord. Sert à vérifier
que `script_args` est bien transmis au script et que l'exécution se fait sous
le compte LaForgeTrusted.

Run : run action=trusted_script path=tools/forge_echo_argv.py script_args=["a","b"]
"""

import getpass
import sys

print("argv :", sys.argv[1:])
print("user :", getpass.getuser())
