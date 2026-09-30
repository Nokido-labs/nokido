import subprocess

r = subprocess.run(["sc", "query", "NokidoNightTrainer"], capture_output=True, text=True, errors="replace")
print("registered" if "NokidoNightTrainer" in r.stdout else "missing")
