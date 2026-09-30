"""
_recycle.py — Envoi vers la corbeille Windows (pas de suppression définitive)
Utilise PowerShell Shell.Application qui gère la corbeille nativement.
"""

import subprocess
import sys
from pathlib import Path

# Racine DERIVEE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
ROOT_P = Path(__file__).resolve().parent.parent


def recycle(rel_path: str) -> str:
    """Envoie un fichier/dossier vers la corbeille Windows via PowerShell."""
    p = ROOT_P / rel_path
    if not p.exists():
        return f"ABSENT: {rel_path}"

    abs_path = str(p.resolve()).replace("'", "''")

    # PowerShell Shell.Application — méthode native corbeille Windows
    ps_script = f"""
$shell  = New-Object -ComObject Shell.Application
$folder = $shell.NameSpace('{abs_path}' | Split-Path)
$item   = $folder.ParseName(('{abs_path}' | Split-Path -Leaf))
if ($item) {{
    $item.InvokeVerb('delete')
    Write-Output 'RECYCLED'
}} else {{
    Write-Output 'NOT_FOUND'
}}
"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
        timeout=15,
    errors="replace")
    output = r.stdout.strip()
    if "RECYCLED" in output:
        return f"♻️  {rel_path}"
    # Fallback : FileSystem.MoveToRecycleBin via Visual Basic
    ps2 = f"""
Add-Type -AssemblyName Microsoft.VisualBasic
[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
    '{abs_path}',
    'OnlyErrorDialogs',
    'SendToRecycleBin'
)
Write-Output 'RECYCLED'
"""
    if p.is_dir():
        ps2 = f"""
Add-Type -AssemblyName Microsoft.VisualBasic
[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
    '{abs_path}',
    'OnlyErrorDialogs',
    'SendToRecycleBin'
)
Write-Output 'RECYCLED'
"""
    r2 = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps2], capture_output=True, text=True, timeout=15
    , errors="replace")
    if "RECYCLED" in r2.stdout:
        return f"♻️  {rel_path}"
    return f"❌  {rel_path}: {r2.stderr.strip()[:60]}"


def recycle_glob(directory: str, pattern: str) -> str:
    """Envoie vers la corbeille tous les fichiers matchant le pattern."""
    d = ROOT_P / directory
    if not d.exists():
        return f"ABSENT: {directory}"
    files = list(d.glob(pattern))
    if not files:
        return f"0 fichiers trouvés: {directory}/{pattern}"
    results = []
    for f in files:
        results.append(recycle(str(f.relative_to(ROOT_P))))
    return "\n".join(results) + f"\n  → {len(files)} items"


# ═══════════════════════════════════════════════════════════════════════
# PLAN DE NETTOYAGE — avec confirmation avant exécution
# ═══════════════════════════════════════════════════════════════════════

PLAN = [
    # Catégorie, chemin relatif, description
    # ── Gros fichiers obsolètes ──────────────────────────────────────────
    ("FILE", "app/_tmp_lf.py", "Ancienne Nokido.py 12379L — remplacée par refactor"),
    ("FILE", "app/Nokido_tmp.py", "Doublon Nokido.py vide"),
    ("FILE", "db_sync_watcher.py", "Déprécié v17 — DB centralisée"),
    ("FILE", "workspace/Nokido_v13.6.py", "Archive v13 — supersédée par v17"),
    # ── Dossiers obsolètes ───────────────────────────────────────────────
    ("DIR", "dist_build", "Build distribution obsolète — 9MB"),
    ("DIR", "app/backups", "Backups auto — 10 fichiers 5MB"),
    ("DIR", "app/legacy", "Modules legacy remplacés"),
    ("DIR", "logs/LaForge", "Logs anciens sessions — 118MB"),
    # ── Scripts legacy app/_*.py ─────────────────────────────────────────
    ("FILE", "app/_copy_mixins.py", "Script migration one-shot"),
    ("FILE", "app/_release_tmp.py", "Script release temporaire"),
    ("FILE", "app/_sandbox_at.py", "Sandbox expérimental"),
    ("FILE", "app/_sandbox_at_real.py", "Sandbox expérimental"),
    ("FILE", "app/_sandbox_nokido.py", "Sandbox expérimental"),
    ("FILE", "app/_sandbox_nlu.py", "Sandbox expérimental"),
    ("FILE", "app/_sandbox_test.py", "Sandbox expérimental"),
    ("FILE", "app/_test_terminal.py", "Test terminal one-shot"),
    ("FILE", "app/_purge_pyc.py", "Utilitaire one-shot"),
    ("FILE", "app/_launch_brain.py", "Lanceur one-shot"),
    ("FILE", "app/debug.py", "Debug one-shot"),
    # ── Scripts racine orphelins ─────────────────────────────────────────
    ("FILE", "audit_env.py", "Script audit ponctuel"),
    ("FILE", "bunker_check.py", "Script vérification ponctuelle"),
    ("FILE", "cleanup_logs.py", "Remplacé par setup_nokido.py"),
    ("FILE", "db_maintenance.py", "Remplacé par setup_nokido.py"),
    ("FILE", "fix_crash.py", "Correctif one-shot"),
    ("FILE", "init_db.py", "Remplacé par setup_nokido.py"),
    ("FILE", "migrate_db.py", "Migration one-shot terminée"),
    ("FILE", "patch_mcp.py", "Patch one-shot appliqué"),
    ("FILE", "prepare_dist.py", "Build obsolète"),
    ("FILE", "purge_pyc.py", "Remplacé par _purge_pycache dans forge_startup"),
    ("FILE", "push_dist.py", "Build obsolète"),
    ("FILE", "rag_sanitize.py", "Script one-shot terminé"),
    ("FILE", "remove_sources.py", "Script one-shot terminé"),
    ("FILE", "setup_cython.py", "Build Cython obsolète"),
    ("FILE", "super_patch.py", "Remplacé par apply_smart_patch"),
    ("FILE", "version_bump.py", "Remplacé par forge_versioning.py"),
    # ── Sandbox tmp ──────────────────────────────────────────────────────
    ("GLOB", "sandbox:_*.py", "Scripts tmp session"),
    ("GLOB", "sandbox:_*.log", "Logs tmp session"),
    ("GLOB", "sandbox:_*.flag", "Flags tmp session"),
    ("GLOB", "sandbox:_*.json", "JSON tmp session"),
    ("GLOB", "sandbox:*.log", "Logs MCP/Hub session"),
]

if __name__ == "__main__":
    print("=== PLAN DE NETTOYAGE (corbeille Windows) ===\n")

    # Afficher le plan avec tailles
    total_kb = 0
    for kind, path, desc in PLAN:
        if kind == "GLOB":
            d, pat = path.split(":")
            items = list((ROOT_P / d).glob(pat)) if (ROOT_P / d).exists() else []
            kb = sum(f.stat().st_size for f in items) // 1024
        else:
            p = ROOT_P / path
            kb = (
                p.stat().st_size // 1024
                if p.is_file()
                else sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) // 1024
                if p.is_dir()
                else 0
            )
        total_kb += kb
        if kb > 0:
            print(
                f"  {'🗑️ ' if kind == 'FILE' else '📁 ' if kind == 'DIR' else '🧹 '}{path:<45} {kb:>6}KB  {desc}"
            )

    print(f"\n  Total estimé : {total_kb // 1024}MB\n")
    print("Lancer avec: python _recycle.py --execute")

    if "--execute" in sys.argv:
        print("\n=== EXÉCUTION ===\n")
        for kind, path, desc in PLAN:
            if kind == "GLOB":
                d, pat = path.split(":")
                r = recycle_glob(d, pat)
            else:
                r = recycle(path)
            print(r)
        print("\n✅ Nettoyage terminé — fichiers dans la corbeille Windows")
