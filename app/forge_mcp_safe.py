"""forge_mcp_safe.py — execution du code Python recu par MCP.

/!\\ LE NOM DE CE MODULE ET CELUI DE `safe_exec` SONT TROMPEURS. Rien ici n'est
« safe » : aucune validation, aucune denylist, aucun bac a sable. Ce fichier
execute le code qu'on lui donne. Les gardes qui protegent reellement ce chemin
(ring, `WORKSPACE_GUARD`, refus de `subprocess`) vivent AILLEURS, en amont —
mesure du 2026-09-19 : un audit delegue a attribue a ce fichier un « RBAC
Ring 2 + _sandbox_decision » qui ne s'y trouve pas. Un nom rassurant a suffi a
faire croire a une protection locale.

CHAINE D'ATTEIGNABILITE, mesuree le 2026-09-19 (AST, 1884 fichiers, 0 illisible) :

    forge_mcp_registry (l.4114, 4263)   <- surface MCP
      -> forge_python_runner
        -> forge_python_worker          <- lance en SUBPROCESS, pas importe :
                                           un scan d'imports le rate
          -> safe_exec                  <- compile puis execute, sans filtre

Executer du Python est une capacite ASSUMEE de Nokido, pas un defaut. Ce qui
demande de la vigilance, c'est que le code y arrive parfois d'un texte que
personne n'a ecrit (cf. la chaine provenance -> prompt systeme -> bloc de code,
fermee le 2026-09-18).

DEUX FONCTIONS ORPHELINES, ET ELLES DOIVENT LE RESTER :

- `run_b64` decode du base64 puis l'execute. Lui donner un appelant rendrait
  TOUTE inspection textuelle en amont inoperante — un filtre ne peut pas lire
  ce qu'il ne voit pas.
- `mcp_safe` est un decorateur qui execute son premier argument.

Elles ne sont pas supprimees (on gele, on n'enterre pas), mais
`tests/nr/test_exec_dynamique_orphelins_nr.py` echoue si l'une d'elles acquiert
un appelant : ce serait un changement de surface d'attaque, pas un detail
d'implementation, et il doit etre decide, pas subi.

Enfin `_run_tmp` ecrit un `.py` et le lance avec `sys.executable`, c'est-a-dire
l'interpreteur du hub — meme motif que le correctif `pip install` du
2026-09-18. Le fichier temporaire est partage (`nokido_task.py`), donc deux
appels concurrents s'ecrasent.
"""
import subprocess, sys, os, tempfile

THRESH = 600
TMP = os.path.join(tempfile.gettempdir(), "nokido_task.py")


def _run_tmp(c, timeout=30):
    open(TMP, "wb").write(c.encode("utf-8"))
    r = subprocess.run([sys.executable, TMP], capture_output=True, text=True, timeout=timeout, errors="replace")
    return (r.stdout + (r.stderr[:300] if r.stderr else "")).strip()


def safe_exec(c, timeout=30):
    if len(c) > THRESH:
        return _run_tmp(c, timeout=timeout)
    ns = {}
    try:
        exec(compile(c, "<mcp>", "exec"), ns)
        return str(ns.get("_result", "ok"))
    except Exception as e:
        return "ERR:" + str(e)[:200]


def run_b64(b):
    import base64

    return safe_exec(base64.b64decode(b).decode("utf-8"))


def mcp_safe(fn):
    def wrap(*a, **k):
        code = k.get("code") or (a[0] if a else "")
        return safe_exec(code)

    return wrap
