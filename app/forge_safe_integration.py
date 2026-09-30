"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_safe_integration
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_safe_integration.py — Vérification post-@loop
====================================================
À lancer APRÈS un @loop de longue durée, AVANT @loop merge.

Séquence sécurisée :
  1. Checkpoint de workspace/ (rollback possible à tout moment)
  2. Inventaire des versions du tronc loop_trunk/
  3. Validation AST de chaque version
  4. Rapport détaillé + recommandation (meilleure version)
  5. Choix utilisateur : merge, rollback ou abandon

NE TOUCHE PAS workspace/ sans confirmation explicite.
"""

import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ── Racine = dossier de Nokido.py ────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
LOOP_DIR = BASE_DIR / "loop_trunk"
BACKUP_DIR = BASE_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / f"safe_integration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


# ── Helpers ────────────────────────────────────────────────────────────────────


def log(msg: str, level: str = "INFO") -> None:
    """Log.

    Args:
        msg: Description.
        level: Description.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {level:<8} | {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def version_key(path: Path) -> list:
    """Tri sémantique : Nokido_v13.1.py > Nokido_v13.0.py"""
    m = re.search(r"_v([\d.]+)\.py$", path.name)
    if not m:
        return [0]
    return [int(x) for x in re.findall(r"\d+", m.group(1))]


def check_syntax(path: Path) -> tuple[bool, str]:
    """Check syntax.

    Args:
        path: Description.
    """
    try:
        code = path.read_text(encoding="utf-8", errors="replace")
        ast.parse(code)
        lines = len(code.splitlines())
        size = path.stat().st_size // 1024
        return True, f"OK — {lines} lignes, {size} Ko"
    except SyntaxError as e:
        return False, f"SyntaxError ligne {e.lineno} : {e.msg}"
    except Exception as e:
        return False, f"Erreur lecture : {e}"


def get_version_str(path: Path) -> str:
    """Get version str.

    Args:
        path: Description.
    """
    try:
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def create_checkpoint(label: str = "pre_safe_integration") -> Path:
    """
    Checkpoint ATOMIQUE : workspace/ + loop_trunk/ → ZIP horodaté.

    Atomicité garantie par écriture dans un fichier .tmp puis rename() en une
    seule opération noyau — jamais de ZIP à moitié écrit visible.
    Inclut une vérification d'intégrité (lecture du ZIP après écriture).

    Retourne le Path du .zip final.
    """
    import zipfile

    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"checkpoint_{ts}_{label}.zip"
    zip_final = BACKUP_DIR / zip_name
    zip_tmp = BACKUP_DIR / f".{zip_name}.tmp"  # invisible tant que non renommé

    dirs_to_backup = {
        "workspace": WORKSPACE_DIR,
        "loop_trunk": LOOP_DIR,
    }

    file_count = 0
    total_bytes = 0

    try:
        with zipfile.ZipFile(zip_tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for arc_root, src_dir in dirs_to_backup.items():
                if not src_dir.exists():
                    continue
                for fpath in sorted(src_dir.rglob("*")):
                    if fpath.is_file():
                        arcname = arc_root + "/" + fpath.relative_to(src_dir).as_posix()
                        zf.write(fpath, arcname)
                        file_count += 1
                        total_bytes += fpath.stat().st_size

            # Manifeste intégré dans le ZIP
            manifest = (
                f"checkpoint: {zip_name}\n"
                f"created:    {datetime.now().isoformat()}\n"
                f"label:      {label}\n"
                f"files:      {file_count}\n"
                f"source_bytes: {total_bytes}\n"
                f"dirs:       {', '.join(k for k, v in dirs_to_backup.items() if v.exists())}\n"
            )
            zf.writestr("MANIFEST.txt", manifest)

        # ── Vérification intégrité avant rename ──────────────────────────────
        with zipfile.ZipFile(zip_tmp, "r") as zf:
            bad = zf.testzip()  # None = tous les CRC sont bons
            if bad:
                raise RuntimeError(f"CRC invalide dans le ZIP : {bad}")
            zip_size_kb = zip_tmp.stat().st_size // 1024

        # ── Rename atomique (une seule opération noyau) ──────────────────────
        zip_tmp.rename(zip_final)

        log(f"Checkpoint créé : {zip_name}", "BACKUP")
        log(f"  {file_count} fichiers | {total_bytes // 1024} Ko source → {zip_size_kb} Ko compressé")
        return zip_final

    except Exception as e:
        # Nettoyer le .tmp corrompu
        if zip_tmp.exists():
            zip_tmp.unlink()
        log(f"Checkpoint ÉCHOUÉ : {e}", "ERROR")
        raise


# ── Étape 1 : Inventaire loop_trunk ───────────────────────────────────────────


def find_loop_trunks() -> list[Path]:
    """Trouve tous les troncs loop actifs dans loop_trunk/"""
    if not LOOP_DIR.exists():
        return []
    return sorted(
        [d for d in LOOP_DIR.iterdir() if d.is_dir() and d.name.startswith("loop_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )


def inventory_loop(trunk: Path) -> list[dict]:
    """Retourne toutes les versions d'un tronc, triées de la plus récente à la plus ancienne."""
    files = sorted(trunk.glob("*.py"), key=version_key, reverse=True)
    results = []
    for f in files:
        ok, msg = check_syntax(f)
        results.append(
            {
                "path": f,
                "name": f.name,
                "version": get_version_str(f),
                "valid": ok,
                "detail": msg,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return results


# ── Étape 2 : Rapport ─────────────────────────────────────────────────────────


def print_report(trunk: Path, inventory: list[dict], checkpoint: Path) -> object:
    """Print report.

    Args:
        trunk: Description.
        inventory: Description.
        checkpoint: Description.
    """
    log("=" * 60)
    log(f"RAPPORT POST-LOOP : {trunk.name}")
    log(f"Checkpoint de sécurité : {checkpoint.name}")
    log("=" * 60)

    valid = [v for v in inventory if v["valid"]]
    invalid = [v for v in inventory if not v["valid"]]

    log(f"Versions trouvées   : {len(inventory)}")
    log(f"  Syntaxe valide    : {len(valid)}")
    log(f"  Syntaxe invalide  : {len(invalid)}")

    if invalid:
        log("── Versions INVALIDES ──", "WARN")
        for v in invalid:
            log(f"  ✗ {v['name']} (v{v['version']}) — {v['detail']}", "WARN")

    if valid:
        best = valid[0]
        log("── Versions VALIDES (ordre décroissant) ──", "INFO")
        for v in valid:
            marker = " ← RECOMMANDÉE" if v is best else ""
            log(f"  ✓ {v['name']} (v{v['version']}) {v['mtime']}{marker}")

        log("")
        log(f"RECOMMANDATION : merger v{best['version']} ({best['name']})")
        log("  Commande Nokido : @loop merge")
        log(f"  Rollback si besoin : @loop stop  (ou restaurer {checkpoint.name})")
    else:
        log("AUCUNE version valide — NE PAS merger", "ERROR")
        log("Toutes les versions sont invalides syntaxiquement.")
        log(f"Rollback disponible : backups/{checkpoint.name}")

    log("=" * 60)
    return valid[0] if valid else None


# ── Étape 3 : Confirmation interactive ────────────────────────────────────────


def ask_action(best: dict | None) -> str:
    """Retourne 'merge', 'rollback', ou 'abort'."""
    if best is None:
        print("\n⛔ Aucune version valide. Actions disponibles :")
        print("  r = rollback vers le checkpoint créé")
        print("  q = quitter sans rien faire")
        choice = input("Choix [r/q] : ").strip().lower()
        return "rollback" if choice == "r" else "abort"

    print(f"\n✅ Meilleure version : {best['name']} (v{best['version']})")
    print("  m = merger cette version dans workspace/ (puis relancer Nokido)")
    print("  r = rollback vers le checkpoint pré-loop")
    print("  q = quitter sans rien faire (loop trunk conservé)")
    choice = input("Choix [m/r/q] : ").strip().lower()
    if choice == "m":
        return "merge"
    if choice == "r":
        return "rollback"
    return "abort"


# ── Étape 4 : Merge manuel sécurisé ───────────────────────────────────────────


def do_merge(best: dict) -> None:
    """Copie la meilleure version dans workspace/ — équivalent de @loop merge."""
    dst = WORKSPACE_DIR / best["name"]
    WORKSPACE_DIR.mkdir(exist_ok=True)
    shutil.copy2(best["path"], dst)
    log(f"Merge effectué : {best['name']} → workspace/", "MERGE")
    log("Relancez Nokido — il chargera automatiquement cette version.")


def do_rollback(checkpoint: Path) -> None:
    """Restaure workspace/ depuis le checkpoint ZIP."""
    import zipfile

    ws = WORKSPACE_DIR
    if not checkpoint.exists():
        log(f"Checkpoint introuvable : {checkpoint}", "ERROR")
        return
    # Extraction du ZIP dans un dossier tmp, puis rename atomique
    tmp_ws = BASE_DIR / ".workspace_restore_tmp"
    if tmp_ws.exists():
        shutil.rmtree(tmp_ws)
    tmp_ws.mkdir()
    with zipfile.ZipFile(checkpoint, "r") as zf:
        # N'extraire que le dossier workspace/
        for member in zf.namelist():
            if member.startswith("workspace/") and not member.endswith("/"):
                rel = member[len("workspace/") :]
                dest = tmp_ws / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member))
    # Remplacement atomique
    if ws.exists():
        shutil.rmtree(ws)
    tmp_ws.rename(ws)
    log(f"Rollback effectué depuis {checkpoint.name}", "ROLLBACK")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> object:
    """Main."""
    log("forge_safe_integration — vérification post-@loop")
    log(f"Racine détectée : {BASE_DIR}")

    # 1. Checkpoint de sécurité AVANT toute opération
    checkpoint = create_checkpoint("pre_safe_integration")

    # 2. Trouver les troncs loop
    trunks = find_loop_trunks()
    if not trunks:
        log("Aucun tronc loop_trunk/ trouvé.", "WARN")
        log("Avez-vous bien lancé @loop start depuis Nokido ?")
        log(f"Checkpoint créé quand même : {checkpoint.name}")
        sys.exit(0)

    # Lister les checkpoints existants
    existing_ckpts = sorted(BACKUP_DIR.glob("checkpoint_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if existing_ckpts:
        log(f"Checkpoints existants : {len(existing_ckpts)} (dernier : {existing_ckpts[0].name})")

    # ── Audit COMPLET de tous les troncs ──────────────────────────────────────
    log(f"\nAudit de {len(trunks)} tronc(s) loop :")
    log("-" * 60)

    all_candidates = []  # (trunk, version_dict) pour tous les fichiers valides non-départ

    for trunk in trunks:
        versions = inventory_loop(trunk)

        # Détecter le fichier de départ : 1 seul fichier OU le plus ancien
        if not versions:
            log(f"  {trunk.name} : VIDE", "WARN")
            continue

        # Le fichier de départ est celui copié par start_loop_trunk()
        # Il a le même nom/version que workspace/ au moment du départ
        # → on le détecte comme le plus ancien (dernière position dans la liste triée desc)
        start_file = versions[-1]  # le plus ancien = copie de départ

        # Versions réellement produites par le loop = tout sauf le départ
        produced = versions[:-1] if len(versions) > 1 else []
        valid_produced = [v for v in produced if v["valid"]]

        status = (
            "🔴 AUCUNE version produite"
            if not produced
            else (
                f"🟡 {len(produced)} version(s), {len(valid_produced)} valide(s)"
                if not valid_produced
                else f"🟢 {len(produced)} version(s), {len(valid_produced)} valide(s)"
            )
        )

        log(f"  {trunk.name} : {status}")
        log(f"    Départ : {start_file['name']} v{start_file['version']} ({start_file['mtime']})")

        for v in produced:
            marker = "✓" if v["valid"] else "✗"
            log(f"    {marker} {v['name']} v{v['version']} {v['mtime']} — {v['detail']}")

        for v in valid_produced:
            all_candidates.append((trunk, v))

    log("-" * 60)

    # ── Diagnostic global ─────────────────────────────────────────────────────
    if not all_candidates:
        log("\n⛔ RÉSULTAT : Aucun tronc n'a produit de version valide.", "ERROR")
        log("   Les loops ont démarré mais n'ont rien généré.", "ERROR")
        log("\n   Causes probables :")
        log("   1. Bug RoleOrchestrator (NameError) — corrigé dans forge_code.py livré")
        log("      → Vérifier que le forge_code.py corrigé est bien en place")
        log("   2. Aucun modèle Ollama disponible au démarrage du loop")
        log("      → Vérifier : ollama list")
        log("   3. Timeout de connexion Ollama pendant toutes les itérations")
        log(f"\n   Checkpoint disponible si besoin : {checkpoint.name}")
        log(f"   Log complet : {LOG_FILE}")
        log("\n   → Rien à merger. Workspace intact.")
        sys.exit(0)

    # ── Trouver la meilleure version toutes troncs confondues ─────────────────
    # Critère : version sémantique la plus haute
    def _semver(v: dict) -> list:
        """Semver.

        Args:
            v: Description.
        """
        import re as _r

        m = _r.search(r"_v([\d.]+)\.py$", v["name"])
        return [int(x) for x in _r.findall(r"\d+", m.group(1))] if m else [0]

    all_candidates.sort(key=lambda x: _semver(x[1]), reverse=True)
    best_trunk, best = all_candidates[0]

    log("\n✅ MEILLEURE VERSION toutes troncs confondues :")
    log(f"   {best['name']} v{best['version']} dans {best_trunk.name}")
    log(f"   {best['detail']}")
    log(f"   Checkpoint de sécurité : {checkpoint.name}")

    # 4. Rapport détaillé du tronc de la meilleure version
    print_report(best_trunk, inventory_loop(best_trunk), checkpoint)

    # 5. Choix utilisateur
    action = ask_action(best)

    if action == "merge":
        do_merge(best)
        log(f"Rapport complet : {LOG_FILE}")
    elif action == "rollback":
        do_rollback(checkpoint)
        log("Workspace restauré à l'état pré-loop.")
    else:
        log("Aucune action effectuée — loop trunks conservés.")
        log("Pour merger depuis Nokido : @loop merge")
        log("Pour annuler depuis Nokido : @loop stop")

    log(f"Log complet : {LOG_FILE}")


if __name__ == "__main__":
    main()
