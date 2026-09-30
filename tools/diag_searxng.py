#!/usr/bin/env python3
"""Diag SearXNG :8080 — confirme que c'est searxng et pourquoi 0 resultat."""
import json
import urllib.request


def get(url):
    try:
        r = urllib.request.urlopen(url, timeout=8)
        return r.status, r.read()
    except Exception as e:
        return None, str(e).encode()


def main():
    st, body = get("http://127.0.0.1:8080/")
    txt = body.decode("utf-8", "ignore").lower()
    print(f"GET / : status={st} is_searxng={'searxng' in txt or 'searx' in txt}")

    st, body = get("http://127.0.0.1:8080/search?q=juicefs&format=json")
    print(f"GET /search?format=json : status={st} bytes={len(body)}")
    try:
        j = json.loads(body)
        print(f"  results={len(j.get('results', []))} number_of_results={j.get('number_of_results')}")
        print(f"  unresponsive_engines={j.get('unresponsive_engines', [])[:10]}")
    except Exception as e:
        print(f"  parse_fail: {e} | head={body[:220].decode('utf-8','ignore')}")


if __name__ == "__main__":
    main()
