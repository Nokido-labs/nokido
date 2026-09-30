"""forge_js_endpoint_extractor.py — Extract hidden API endpoints from JS bundles."""

import re

import requests as _req


def extract_endpoints(js_content: str, use_llm: bool = False) -> list:
    patterns = [
        r'(?<=["\'])(/api/[^\s"\'<>]+)',
        r'(?<=["\'])(/v\d/[^\s"\'<>]+)',
        r'fetch\(\s*["\']([^"\']+)["\']',
        r'axios\.\w+\(\s*["\']([^"\']+)["\']',
        r'\.open\(\s*["\'][A-Z]+["\'],\s*["\']([^"\']+)["\']',
        r'(?<=["\'])(https?://[^\s"\'<>]+/(?:api|v\d)/[^\s"\'<>]+)',
    ]

    endpoints: set = set()
    for pattern in patterns:
        for match in re.findall(pattern, js_content):
            endpoint = re.sub(r"[,\)\s]+$", "", match).strip()
            if endpoint:
                endpoints.add(endpoint)

    if use_llm and endpoints:
        classified = set()
        prompt = (
            "From this list of candidate API endpoints, keep only real REST API paths (remove JS method calls, asset URLs, etc). Return one per line:\n"
            + "\n".join(sorted(endpoints))
        )
        try:
            r = _req.post(
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": "laforge-qwen:latest",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": 300},
                },
                timeout=30,
            )
            text = r.json().get("message", {}).get("content", "")
            for line in text.splitlines():
                line = line.strip().lstrip("- ")
                if line.startswith("/") or line.startswith("http"):
                    classified.add(line)
        except Exception:
            classified = endpoints
        return sorted(classified)

    return sorted(endpoints)


if __name__ == "__main__":
    import sys

    content = open(sys.argv[1]).read() if len(sys.argv) > 1 else ""
    for ep in extract_endpoints(content, use_llm="--llm" in sys.argv):
        print(ep)
