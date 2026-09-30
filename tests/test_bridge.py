"""test_bridge.py — validation ExegolBridge"""
import sys, asyncio
sys.path.insert(0, __import__("os").path.expanduser(r'~\Script python IA\LaForge'))

from forge_exegol_bridge import get_bridge

async def run():
    b = get_bridge()
    
    # containers
    cs = await b.list_containers()
    print("Containers:")
    for c in cs: print(f"  {c['name']} running={c['running']}")
    
    # whoami
    r = await b.run_cmd("tapple", "whoami && uname -r", label="bridge_test")
    print(f"\nExec: rc={r['rc']} dur={r['duration']}s")
    print(f"Output: {r['output'][:120]!r}")
    return True

result = asyncio.run(run())
print(f"\nBridge OK: {result}")
