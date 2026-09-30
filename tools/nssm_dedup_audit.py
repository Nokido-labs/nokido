import subprocess
from collections import defaultdict
from pathlib import Path


def run_nssm_audit():
    services = {}

    # Attempt to get NSSM services using dump
    try:
        dump_proc = subprocess.run(["nssm", "dump"], capture_output=True, text=True, check=False, errors="replace")
        dump_output = dump_proc.stdout

        for line in dump_output.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) >= 3 and parts[0].lower() == "nssm":
                action = parts[1].lower()
                if action == "install" and len(parts) >= 4:
                    svc_name = parts[2]
                    if svc_name not in services:
                        services[svc_name] = {
                            "status": "UNKNOWN",
                            "exe": parts[3],
                            "dir": "",
                            "params": "",
                        }
                elif action == "set" and len(parts) >= 5:
                    svc_name = parts[2]
                    key = parts[3].lower()
                    val = " ".join(parts[4:])
                    if svc_name not in services:
                        services[svc_name] = {
                            "status": "UNKNOWN",
                            "exe": "",
                            "dir": "",
                            "params": "",
                        }
                    if key == "appdirectory":
                        services[svc_name]["dir"] = val
                    elif key == "appparameters":
                        services[svc_name]["params"] = val
    except Exception as e:
        print(f"Error running nssm dump: {e}")

    # Fallback to nssm list if explicitly requested by prompt
    try:
        list_proc = subprocess.run(["nssm", "list"], capture_output=True, text=True, check=False, errors="replace")
        for line in list_proc.stdout.splitlines():
            if line.strip() and line.strip() not in services:
                services[line.strip()] = {"status": "UNKNOWN", "exe": "", "dir": "", "params": ""}
    except Exception:
        pass

    # Get status using powershell to find stopped since >7 days
    # We will use WMI or Get-Service. Get-Service doesn't have LastExitTime easily.
    # We will just mark STOPPED.
    try:
        sc_proc = subprocess.run(
            ["powershell", "-Command", "Get-Service | Select-Object Name, Status"],
            capture_output=True,
            text=True,
        errors="replace")
        for line in sc_proc.stdout.splitlines():
            if not line.strip() or line.startswith("Name") or line.startswith("--"):
                continue
            # Format is usually: Name    Status
            # e.g. "AudioSrv    Running"
            parts = line.strip().split()
            if len(parts) >= 2:
                name = parts[0]
                status = parts[-1]
                if name in services:
                    services[name]["status"] = status.upper()
    except Exception:
        pass

    # Detect duplicates by AppDirectory + AppParameters
    signatures = defaultdict(list)
    for name, data in services.items():
        sig = f"{data['dir']} | {data['params']}"
        signatures[sig].append(name)

    report_lines = [
        "# NSSM Audit Report",
        "",
        "| Service | Status | Action Recommandée | Raison |",
        "|---------|--------|--------------------|--------|",
    ]

    actions_count = {"KEEP": 0, "DISABLE": 0, "REMOVE": 0}

    for sig, names in signatures.items():
        if len(names) > 1:
            running = [n for n in names if services[n]["status"] == "RUNNING"]
            keep_name = running[0] if running else names[0]

            for n in names:
                if n == keep_name:
                    report_lines.append(f"| {n} | {services[n]['status']} | KEEP | Principal |")
                    actions_count["KEEP"] += 1
                else:
                    report_lines.append(
                        f"| {n} | {services[n]['status']} | REMOVE | Doublon de {keep_name} |"
                    )
                    actions_count["REMOVE"] += 1
        else:
            n = names[0]
            status = services[n]["status"]
            if status == "STOPPED":
                report_lines.append(f"| {n} | {status} | DISABLE | Stoppé (potentiellement >7j) |")
                actions_count["DISABLE"] += 1
            else:
                report_lines.append(f"| {n} | {status} | KEEP | Unique et actif |")
                actions_count["KEEP"] += 1

    report_path = Path("NSSM_AUDIT.md")
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("NSSM Audit terminé.")
    print(f"Rapport généré: {report_path.absolute()}")
    print("Résumé des actions:")
    print(f" - KEEP: {actions_count['KEEP']}")
    print(f" - DISABLE: {actions_count['DISABLE']}")
    print(f" - REMOVE: {actions_count['REMOVE']}")


if __name__ == "__main__":
    run_nssm_audit()
