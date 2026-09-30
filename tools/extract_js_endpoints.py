#!/usr/bin/env python
"""extract_js_endpoints.py — Extrait endpoints depuis bundles JS webpack/vite.

Usage:
    %USERPROFILE%/miniforge3/python.exe tools/extract_js_endpoints.py <file.js>
"""

__FORGE_COLOR__ = "digestif/web : extrait les endpoints de bundles JS webpack/vite"  # organe declare le 2026-09-06 (audit de raccordement)

import re
import sys
from pathlib import Path


def extract_js_endpoints(js_content: str) -> list[str]:
    """Extrait URLs/paths depuis bundle JS webpack/vite."""
    found: set[str] = set()

    patterns = [
        r'["\'](/api/[a-zA-Z0-9/_\-\.]+)["\']',  # /api/...
        r'(?:fetch|axios\.(?:get|post|put|patch|delete))\(["\']([^"\']+)["\']',  # fetch/axios
        r'path:\s*["\']([/][^"\']{2,})["\']',  # route defs
        r'"(?:url|endpoint|path|route)":\s*"(/[^"]{2,})"',  # object keys
        r"'(?:url|endpoint|path|route)':\s*'(/[^']{2,})'",
        r'(?:baseURL|BASE_URL)\s*[=:]\s*["\']([^"\']+)["\']',  # baseURL
    ]
    for pat in patterns:
        found.update(re.findall(pat, js_content))

    # Filtrer faux positifs
    clean = [
        e
        for e in found
        if len(e) >= 3
        and not e.endswith((".js", ".css", ".png", ".svg", ".woff", ".map"))
        and "node_modules" not in e
        and not e.startswith("//")
    ]
    return sorted(set(clean))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Demo
        sample = """
        fetch('/api/users/profile', {method:'GET'})
        axios.post('/api/auth/login', data)
        path: '/dashboard/settings'
        "endpoint": "/graphql"
        """
        print("\n".join(extract_js_endpoints(sample)))
    else:
        content = Path(sys.argv[1]).read_text("utf-8", errors="replace")
        for ep in extract_js_endpoints(content):
            print(ep)
