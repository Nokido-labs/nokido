import os
import subprocess
import sys
from pathlib import Path

def check_permissions(path):
    print(f"Checking permissions for {path}...")
    try:
        test_file = Path(path) / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()
        print(f"SUCCESS: Write permission OK for {path}")
        return True
    except Exception as e:
        print(f"ERROR: Permission denied for {path}: {e}")
        return False

def fix_permissions(path):
    print(f"Attempting to fix permissions for {path}...")
    try:
        username = os.environ.get('USERNAME')
        subprocess.run(['icacls', str(path), '/grant', f'{username}:(OI)(CI)M', '/T'], check=True)
        print(f"SUCCESS: Permissions updated for {path}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to fix permissions: {e}")
        return False

def check_logs(log_dir):
    print(f"Scanning logs in {log_dir}...")
    log_dir = Path(log_dir)
    errors_found = False
    if not log_dir.exists():
        print(f"ERROR: Log directory {log_dir} does not exist.")
        return False
    
    for log_file in log_dir.glob("*.err.log"):
        content = log_file.read_text(errors='replace')
        if "PermissionError" in content:
            print(f"CRITICAL: PermissionError found in {log_file.name}")
            errors_found = True
    return errors_found

def measure_pacing():
    import time
    start = time.time()
    # Test léger de calcul
    sum(range(1000000))
    end = time.time()
    latency = end - start
    print(f"Cognitive Pacing (Latency Probe): {latency:.4f}s")
    return latency

def main():
    root_dir = Path(__import__("os").path.expanduser(r"~\Script python IA"))
    log_dir = root_dir / "logs"
    
    print("--- NOKIDO RESCUE DIAGNOSTIC ---")
    pacing = measure_pacing()
    
    log_errors = check_logs(log_dir)
    write_ok = check_permissions(log_dir)
    
    if not write_ok or log_errors:
        print("\nAction required: Fixing permissions...")
        fix_permissions(log_dir)
    else:
        print("\nSystem seems healthy regarding file permissions.")
    
    print("\n--- DIAGNOSTIC COMPLETE ---")

if __name__ == "__main__":
    main()
