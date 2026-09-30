import subprocess

r = subprocess.run(
    ["git", "-C", __import__("os").path.expanduser("~/Script python IA/LaForge"), "log", "--oneline", "-3"],
    capture_output=True,
    text=True,
errors="replace")
print(r.stdout.strip())
