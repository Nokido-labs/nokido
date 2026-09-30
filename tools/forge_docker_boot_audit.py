"""Réveille le daemon docker (trigger keeper docker.wanted) puis audite le reclaimable
(system df + df -v). Trusted (host). Cap ~95s."""
import os
import shutil
import subprocess
import time

# Racine DERIVEE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
ROOT = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
trig = os.path.join(ROOT, "sandbox", "docker.wanted")
try:
    with open(trig, "w", encoding="utf-8") as f:
        f.write(str(time.time()))
    print("triggered sandbox/docker.wanted (keeper -> boot docker)")
except Exception as e:
    print("trigger ERR:", e)

DOCKER = "docker"
if not shutil.which("docker"):
    cand = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if os.path.exists(cand):
        DOCKER = cand

ok = False
for i in range(17):  # ~85s
    time.sleep(5)
    try:
        r = subprocess.run([DOCKER, "system", "df"], capture_output=True, text=True, timeout=20, errors="replace")
    except Exception:
        continue
    if r.returncode == 0:
        print(f"\ndaemon UP apres ~{(i + 1) * 5}s\n")
        print(r.stdout)
        try:
            r2 = subprocess.run([DOCKER, "system", "df", "-v"], capture_output=True, text=True, timeout=60, errors="replace")
            print("\n--- detail -v (top 3000c) ---\n" + (r2.stdout or "")[:3000])
        except Exception as e:
            print("df -v err:", e)
        ok = True
        break
if not ok:
    print("daemon PAS up apres ~85s (keeper absent/lent ?) -> relancer l'audit plus tard")
