"""Test BAML appel réel sur llama.cpp local + Schema-Aligned Parsing."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from baml_client import b

code = """
def transfer_funds(account_from, account_to, amount):
    sql = f"UPDATE accounts SET balance = balance - {amount} WHERE id = {account_from}"
    cursor.execute(sql)
    cursor.execute(f"UPDATE accounts SET balance = balance + {amount} WHERE id = {account_to}")
    return True
"""

t0 = time.monotonic()
try:
    result = b.AnalyzeCode(code=code, context="Backend API banking")
    elapsed = time.monotonic() - t0
    print(f"=== BAML AnalyzeCode (qwen2.5-coder local) — {elapsed:.2f}s ===")
    print(f"language          : {result.language}")
    print(f"complexity_score  : {result.complexity_score}")
    print(f"refactor_priority : {result.refactor_priority}")
    print(f"issues            : {len(result.issues)}")
    for i, issue in enumerate(result.issues[:5], 1):
        print(f"  [{i}] L{issue.line} {issue.severity}/{issue.category}: {issue.message}")
        if issue.fix_hint:
            print(f"      fix: {issue.fix_hint}")
    print(f"suggestions       : {len(result.suggestions)}")
    for s in result.suggestions[:3]:
        print(f"  - {s}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
