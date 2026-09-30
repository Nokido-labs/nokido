import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def check_health(url):
    try:
        urllib.request.urlopen(url, timeout=3)
        return "UP"
    except Exception:
        return "DOWN"


def read_log_file(file_path):
    if file_path.exists():
        with open(file_path, errors="replace") as f:
            return f.readlines()[-20:]
    return []


def grep_brain_ts(file_path):
    if file_path.exists():
        with open(file_path, errors="replace") as f:
            content = f.read()
            return bool(re.search(r"processLLMIntent", content))
    return False


def main():
    health_8000 = check_health("http://localhost:8000/health")
    health_7401 = check_health("http://localhost:7401/health")
    log_file = ROOT / "sandbox" / "deno_proxy.log"
    log_lines = read_log_file(log_file)
    brain_ts_path = ROOT / "proxy_deno" / "core" / "brain.ts"
    nlu_active = grep_brain_ts(brain_ts_path)

    print(f"DenoProxy :8000  : {health_8000}")
    print(f"DenoWebHub :7401 : {health_7401}")
    if log_lines:
        print("-- deno_proxy.log (last 20) --")
        for line in log_lines:
            print(line.rstrip())
    else:
        print("-- deno_proxy.log : absent --")
    print(f"brain.ts NLU (processLLMIntent): {'ACTIVE' if nlu_active else 'BYPASSED/ABSENT'}")


if __name__ == "__main__":
    main()
