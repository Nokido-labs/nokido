import ast
import os
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def parse_constitution() -> dict:
    import toml
    const_path = ROOT / "config" / "constitution.toml"
    if not const_path.exists():
        return {}
    return toml.loads(const_path.read_text(encoding="utf-8"))

def check_code_violations(file_path: Path, code_content: str) -> list[str]:
    violations = []
    const = parse_constitution()
    if not const:
        return ["Constitution file missing"]
        
    rules = const.get("rules", {})
    
    # 1. Vérification des fichiers immuables
    try:
        rel_path = file_path.relative_to(ROOT).as_posix()
    except ValueError:
        rel_path = file_path.as_posix()
        
    if rel_path in rules.get("immutable_files", []):
        violations.append(f"Immutable file violation: {rel_path} cannot be modified by autonomous agents.")
        
    # 2. Vérification des chemins autorisés
    allowed_dirs = rules.get("write_allowed_paths", [])
    path_allowed = False
    for allowed in allowed_dirs:
        if rel_path.startswith(allowed):
            path_allowed = True
            break
    if not path_allowed and not any(rel_path.endswith(f) for f in ["check_db_entries.py", "check_watch_job.py", "test_mutation.py"]):
        violations.append(f"Out-of-bounds write: {rel_path} is outside allowed autonomous write areas.")
        
    # 3. Analyse AST pour repérer les nœuds interdits
    try:
        tree = ast.parse(code_content)
        forbidden = rules.get("forbidden_ast_nodes", [])
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    parts = []
                    curr = node.func
                    while isinstance(curr, ast.Attribute):
                        parts.append(curr.attr)
                        curr = curr.value
                    if isinstance(curr, ast.Name):
                        parts.append(curr.id)
                    func_name = ".".join(reversed(parts))
                
                if func_name in forbidden:
                    violations.append(f"Forbidden node in AST: Call to '{func_name}' is prohibited by the constitution.")
    except SyntaxError as e:
        violations.append(f"AST SyntaxError: Cannot parse {rel_path} - {e}")
        
    return violations

def _log(msg: str, level: str = "INFO"):
    line = f"[mutation_loop:{level}] {msg}"
    print(line.encode("ascii", "replace").decode("ascii"), flush=True)

def run_cmd(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        res = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT), timeout=timeout, errors="replace")
        if res.returncode == 0:
            return True, res.stdout
        return False, res.stderr
    except Exception as e:
        return False, str(e)



def calculate_tests_hash() -> str:
    """Calcule le hash SHA-256 global du dossier tests/ pour la protection Ring 0."""
    import hashlib
    test_dir = ROOT / "tests"
    if not test_dir.exists():
        return ""
    hasher = hashlib.sha256()
    for root, _, files in os.walk(test_dir):
        for file in sorted(files):
            fp = Path(root) / file
            if fp.suffix == ".py":
                hasher.update(fp.relative_to(ROOT).as_posix().encode("utf-8"))
                hasher.update(fp.read_bytes())
    return hasher.hexdigest()

def apply_mutation_with_git_guard(file_path: Path, new_code: str, commit_msg: str) -> bool:
    """
    Applique une modification de code avec double ceinture de sécurité :
    1. Validation AST constitutionnelle.
    2. Tests unitaires (healthcheck).
    En cas de succès : Commit Git + Redémarrage du service.
    En cas d'échec : Rollback au commit Git précédent.
    """
    label = f"mutation:{file_path.name}"
    _log(f"Starting mutation guard for {file_path.name}...")
    
    # Ring 0 : Calcul du hash initial de la suite de tests
    initial_test_hash = calculate_tests_hash()
    
    # Étape 0 : ZONE DE L'ÉVALUATEUR (2026-10-01). L'empreinte de la suite de tests (plus bas)
    # ne couvre ni la CI, ni la configuration pytest, ni le juge : une mutation de
    # tools/ci_local.py ou de pyproject.toml passait. Même règle unique que mutable() et le
    # merge gate (forge_mutation_judge.zone_evaluateur_touchee).
    try:
        from nokido_agent.app.forge_mutation_judge import evolution_autorisee, zone_evaluateur_touchee

        # PORTE DE L'EVOLUTION (2026-10-01) : armement owner, frein, verrou humain.
        _porte = evolution_autorisee()
        if not _porte["autorisee"]:
            _log(f"HALTED ({_porte['etat']}) : {_porte['motif']} -- aucune ecriture", "WARN")
            return False
        _rel = Path(file_path).resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, ImportError) as e:   # zone illisible ou hors depot : on REFUSE (fail-closed)
        _log(f"ABORTED: zone de l'evaluateur non verifiable pour {file_path} ({type(e).__name__}) "
             "-- mutation refusee", "ERROR")
        return False
    if zone_evaluateur_touchee([_rel]):
        _log(f"ABORTED: {_rel} est dans la zone de l'evaluateur -- une mutation ne touche "
             "jamais ce qui la juge", "ERROR")
        return False

    # Étape 1 : Vérification AST pré-écriture
    _log("Phase 1: Validating AST rules against constitution...")
    violations = check_code_violations(file_path, new_code)
    if violations:
        _log(f"ABORTED: Constitutional violations detected: {violations}", "ERROR")
        return False
        
    # Étape 2 : Écriture du code temporaire
    _log("Phase 2: Writing temporary mutation...")
    old_code = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    try:
        file_path.write_text(new_code, encoding="utf-8")
    except Exception as e:
        _log(f"Write failed: {e}", "ERROR")
        return False
        
    # Ring 0 / Cheater Detector : Vérifier que les tests n'ont pas été modifiés
    current_test_hash = calculate_tests_hash()
    if initial_test_hash != current_test_hash:
        _log("SECURITY ALERT: Mutation attempted to modify the tests suite! Rollback forced.", "CRITICAL")
        run_cmd(["git", "restore", str(file_path)])
        return False
        
    # Étape 3 : Exécution des tests unitaires
    _log("Phase 3: Running health checks and tests...")
    # Dériver le fichier de test de la mutation (ou tests/test_<name>.py)
    test_file = ROOT / "tests" / f"test_{file_path.name}"
    if not test_file.exists():
        test_file = ROOT / "tests" / f"test_{file_path.stem}.py"
        
    if not test_file.exists():
        _log(f"ABORTED: No test coverage file found for {file_path.name} (checked tests/test_{file_path.name} and tests/test_{file_path.stem}.py).", "ERROR")
        run_cmd(["git", "restore", str(file_path)])
        return False
        
    # FIX faille de consolidation (AGY 2026-08-28) : jouer la suite d'INVARIANTS
    # tests/nr EN PLUS du test dedie -- sinon une mutation passe SON seul test et
    # casse un autre module EN SILENCE (regression inter-modules non detectee).
    _suite = ["pytest", str(test_file), "-q", "--continue-on-collection-errors"]
    if (ROOT / "tests" / "nr").exists():
        _suite.insert(2, "tests/nr")
    test_ok, test_output = run_cmd(_suite, timeout=600)
    
    if not test_ok:
        _log(f"TESTS FAILED: Rolling back to previous Git commit...", "ERROR")
        # Rollback Git physique (restore le fichier à son état git précédent)
        run_cmd(["git", "restore", str(file_path)])
        _log("Rollback completed successfully.", "WARN")
        
        # Enregistrement de l'incident d'apprentissage
        try:
            from nokido_agent.app.forge_self_correction import anchor_error
            anchor_error(
                error_msg=f"Regression in autonomous mutation: {file_path.name}",
                context=f"Tests failed during mutation:\n{test_output[:1000]}",
                solution="Restored to last git commit automatically.",
                domain="systeme"
            )
        except Exception as ae:
            _log(f"Failed to anchor incident: {ae}", "WARN")
            
        return False
        
    # Étape 4 : Succès total -> Commit & Restart
    _log("Phase 4: Tests passed. Committing modifications...")
    run_cmd(["git", "add", str(file_path)])
    commit_ok, commit_out = run_cmd([
        "git", "commit",
        "-m", commit_msg,
        "-m", "LaForge-Agent-Name: ANTIGRAVITY"
    ])
    
    if commit_ok:
        _log("Commit created successfully.")
        return True
    else:
        _log(f"Commit failed (rolling back): {commit_out}", "ERROR")
        run_cmd(["git", "restore", str(file_path)])
        return False

if __name__ == "__main__":
    # Test à vide
    target = ROOT / "sandbox" / "test_mutation.py"
    dummy_code = "print('Hello world from mutation')"
    apply_mutation_with_git_guard(target, dummy_code, "chore(test): test mutation logic")
