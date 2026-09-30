"""(a) supprime D:/Docker_Backup (110MB, perime). (b) audit docker reclaimable
(system df + df -v). Trusted (host) : acces D: + docker CLI."""
import os
import shutil
import subprocess

print("=== (a) supprimer D:/Docker_Backup ===")
try:
    if os.path.isdir(r"D:/Docker_Backup"):
        shutil.rmtree(r"D:/Docker_Backup")
        print("DELETED D:/Docker_Backup (110MB libere)")
    else:
        print("deja absent")
except Exception as e:
    print("DELETE ERR:", type(e).__name__, e)

print("\n=== (b) docker reclaimable ===")
DOCKER = "docker"
if not shutil.which("docker"):
    cand = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if os.path.exists(cand):
        DOCKER = cand
try:
    r = subprocess.run([DOCKER, "system", "df"], capture_output=True, text=True, timeout=60, errors="replace")
    print("rc", r.returncode)
    print(r.stdout or "")
    if r.stderr:
        print("STDERR:", r.stderr[:600])
    if r.returncode == 0:
        r2 = subprocess.run([DOCKER, "system", "df", "-v"], capture_output=True, text=True, timeout=90, errors="replace")
        print("\n--- detail (-v, top) ---")
        print((r2.stdout or "")[:2800])
except Exception as e:
    print("docker exec err:", type(e).__name__, e)
