"""forge_rename_debt_inventory.py — INVENTAIRE READ-ONLY de la dette du renommage
LaForge -> Nokido. N'ecrit RIEN, ne renomme RIEN.

POURQUOI
  Le rename du 2026-07-08 a balaye LE DEPOT. Les references vivent AUSSI hors depot :
  C:\\tmp, registre NSSM, taches planifiees, hooks ~/.claude, vault. Mesure du
  2026-07-17 : C:\\tmp\\wake_llama_native.py:83 cherchait encore le service
  "LaForgeLlamaNative" alors que services.toml declare "NokidoLlamaNative" -> rc=2 ->
  fallback SILENCIEUX 9 jours -> ~5 GB de RAM jamais rendus (fixe par d615c910).
  Personne n'avait jamais liste cette dette. Ce script la liste.

CE QU'IL CHERCHE (cible, pas un grep generique qui noierait le signal)
  A. LOOKUPS DE SERVICE MORTS = le defaut qui a mordu. Tout litteral ressemblant a un
     nom de service (LaForgeXxx / NokidoXxx) qui n'est PAS declare dans services.toml.
     C'est LA classe de bug : muet, sans exception, fallback silencieux.
  B. DETTE ENV (prerequis des SHIMS) : les LAFORGE_* lus par le code
     (os.environ.get("LAFORGE_...")) vs ceux SETES dans les env de services.toml.
     Un rename d'env sans shim dual-read = config silencieusement ignoree.
  C. SERVICES NSSM enregistres vs declares.
  D. PORTEURS HORS DEPOT : fichiers de C:\\tmp reference depuis le code du depot
     (un organe du boot ne doit pas dependre d'un scratch que rien ne balaie).

Usage : run action=trusted_script path=tools/forge_rename_debt_inventory.py
"""

__FORGE_COLOR__ = "qualite/quality : inventaire lecture seule de la dette du renommage"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOML = ROOT / "proxy_deno" / "core" / "services.toml"
TMP = Path(r"C:/tmp")
CLAUDE_DIR = Path(os.path.expanduser("~/.claude"))

# 2026-07-17 : la v1 lisait INTEGRALEMENT 42869 fichiers / 2.0 Go -- dont un JSON de
# 264 Mo, rockyou.txt (133 Mo) et ~500 Mo de dumps gitingest. Le walk coute 2.3s ; c'est
# la LECTURE qui plombait. Un inventaire de CODE n'a rien a faire dans les zones de
# DONNEES : on les exclut, et on cappe la taille (aucun source legitime > 2 Mo).
SKIP_DIRS = {".git", "node_modules", "miniforge3", "inspirations", "_mcp_repos",
             "backups", "refacto_backups", "archive", "__pycache__", ".venv",
             "RAG_plain_bak", "nokido_persist", "pytest-of-user",
             "data", "RAG", "datasets", "gitingest", "longmemeval", "workspace"}
EXTS = {".py", ".ts", ".toml", ".json", ".bat", ".ps1", ".md", ".txt", ".env"}
MAX_BYTES = 2 * 1024 * 1024

# Un nom de service = LaForge/Nokido suivi d'un CamelCase. Volontairement etroit.
SVC_RE = re.compile(r"\b((?:LaForge|Nokido)[A-Z][A-Za-z0-9]{2,})\b")
ENV_GET_RE = re.compile(r"""environ(?:\.get)?\(\s*["'](LAFORGE_[A-Z0-9_]+)["']""")
TMP_REF_RE = re.compile(r"""["']([A-Za-z]:[\\/]{1,2}tmp[\\/][^"']+)["']""")


def walk(root: Path):
    if not root.exists():
        return
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fn:
            p = Path(dp) / f
            if p.suffix.lower() not in EXTS:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue  # dataset/dump : jamais du code
            except OSError:
                continue
            yield p


def read(p: Path):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def rel(p: Path):
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def main() -> int:
    data = tomllib.loads(TOML.read_text(encoding="utf-8"))
    declared = {s["name"] for s in data.get("service", []) if s.get("name")}
    # Les env SETES par services.toml = la verite de ce que le code peut lire.
    set_env = set()
    for s in data.get("service", []):
        set_env |= set((s.get("env") or {}).keys())

    print("services.toml : %d services declares, %d noms d'env setes" % (len(declared), len(set_env)))
    print()

    scopes = [("depot", ROOT), ("C:/tmp", TMP), ("~/.claude", CLAUDE_DIR)]
    dead_lookups, env_read, tmp_refs = {}, {}, {}

    for label, root in scopes:
        for p in walk(root):
            txt = read(p)
            if not txt:
                continue
            for n, line in enumerate(txt.splitlines(), 1):
                for m in SVC_RE.finditer(line):
                    nm = m.group(1)
                    if nm in declared:
                        continue
                    # ignore les mentions purement narratives d'un doc
                    dead_lookups.setdefault(nm, []).append("%s:%d [%s]" % (rel(p), n, label))
                for m in ENV_GET_RE.finditer(line):
                    env_read.setdefault(m.group(1), []).append("%s:%d" % (rel(p), n))
                if label == "depot":
                    for m in TMP_REF_RE.finditer(line):
                        tmp_refs.setdefault(m.group(1), []).append("%s:%d" % (rel(p), n))

    print("=" * 78)
    print("A. LOOKUPS DE SERVICE QUI N'EXISTENT PLUS  (la classe de bug du jour)")
    print("=" * 78)
    # Un nom LaForge* dont l'equivalent Nokido* EXISTE = rename rate, priorite haute.
    hot = {k: v for k, v in dead_lookups.items()
           if k.startswith("LaForge") and ("Nokido" + k[len("LaForge"):]) in declared}
    cold = {k: v for k, v in dead_lookups.items() if k not in hot}
    print("\n>>> CRITIQUE : le service a ete RENOMME, le lookup est reste (= panne muette)")
    if not hot:
        print("    aucun")
    for k in sorted(hot):
        print("  %-28s -> devrait etre 'Nokido%s'  (%d refs)" % (k, k[len("LaForge"):], len(hot[k])))
        for loc in hot[k][:6]:
            print("        %s" % loc)
    print("\n>>> AUTRES noms non declares (peut etre du texte, un service mort, un typo)")
    for k in sorted(cold):
        kind = "hors-toml"
        print("  %-28s %-10s %d refs   ex: %s" % (k, kind, len(cold[k]), cold[k][0]))

    print()
    print("=" * 78)
    print("B. DETTE ENV  (prerequis des SHIMS dual-read)")
    print("=" * 78)
    orphan = {k: v for k, v in env_read.items() if k not in set_env}
    print("LAFORGE_* LUS par le code      : %d" % len(env_read))
    print("...dont JAMAIS setes en toml   : %d (defaut applique en silence)" % len(orphan))
    for k in sorted(orphan)[:25]:
        print("  %-42s ex: %s" % (k, orphan[k][0]))
    if len(orphan) > 25:
        print("  ... +%d autres" % (len(orphan) - 25))

    print()
    print("=" * 78)
    print("C. SERVICES NSSM enregistres vs declares")
    print("=" * 78)
    try:
        r = subprocess.run(["sc", "query", "type=", "service", "state=", "all"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        got = sorted(set(re.findall(r"SERVICE_NAME:\s*((?:LaForge|Nokido)\S*)", r.stdout)))
        for s in got:
            mark = "" if s in declared else "   <-- PAS dans services.toml"
            print("  %-32s%s" % (s, mark))
        if not got:
            print("  aucun service LaForge*/Nokido* enregistre (ou sc sans droits)")
    except Exception as e:
        print("  sc query indisponible : %r" % (e,))

    print()
    print("=" * 78)
    print("D. PORTEURS HORS DEPOT  (C:/tmp reference depuis le code)")
    print("=" * 78)
    print("Un organe du boot ne doit pas dependre d'un scratch que rien ne balaie.")
    for k in sorted(tmp_refs):
        exists = "OK" if Path(k.replace("\\\\", "\\")).exists() else "ABSENT"
        print("  [%-6s] %-52s  <- %s" % (exists, k, tmp_refs[k][0]))

    print()
    print("=" * 78)
    print("ORDRE RECOMMANDE : (1) fixer les lookups CRITIQUES, (2) SHIMS dual-read "
          "LAFORGE_/NOKIDO_, (3) alias service NSSM, (4) SEULEMENT ENSUITE le rename.")
    print("Cf memoire nokido_rename_project_2026-07-08. Rien n'a ete modifie.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
