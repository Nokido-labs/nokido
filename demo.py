#!/usr/bin/env python3
"""Nokido end-to-end demo — run: python demo.py"""
import sys, time, json
sys.path.insert(0, "app")

HUB = "http://localhost:8766"

def call(tool, args, label):
    import urllib.request as ur, urllib.error as ue
    body = json.dumps({"method": "tools/call", "params": {"name": tool, "arguments": args}}).encode()
    try:
        req = ur.Request(f"{HUB}/mcp", data=body, headers={"Content-Type": "application/json"}, method="POST")
        resp = json.loads(ur.urlopen(req, timeout=10).read())
        result = resp.get("result", resp.get("error", "?"))
        print(f"  [{label}] OK — {str(result)[:120]}")
        return True
    except ue.URLError:
        print(f"  [{label}] SKIP — hub unreachable on {HUB}")
        return False
    except Exception as e:
        print(f"  [{label}] ERR — {e}")
        return False

def sep(title):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print('─'*50)

print("━"*50)
print("  Nokido — Demo end-to-end")
print("━"*50)

# 1 — Health
sep("1. Hub health check")
call("run", {"action": "shell", "commands": ["echo Nokido OK"]}, "shell")

# 2 — RAG search
sep("2. RAG semantic search")
call("rag", {"query": "SemanticFirewall pre_flight", "top_k": 3}, "rag")

# 3 — LLM ask (local ollama)
sep("3. LLM ask (ollama local)")
call("ask", {"prompt": "Résume Nokido en 1 phrase.", "provider": "ollama"}, "ask")

# 4 — Hub status
sep("4. Hub introspection")
call("hub", {"action": "get_mode"}, "hub.mode")

print("\n━"*50)
print("  Demo terminée. Hub: http://localhost:8766")
print("  Docs: README.md | Config: Nokido.env")
print("━"*50)
