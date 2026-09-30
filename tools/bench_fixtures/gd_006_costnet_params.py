import sys

sys.path.insert(0, __import__("os").path.expanduser("~/Script python IA/LaForge/tools"))
from nokido_agent.tools.forge_pytorch_nets import CostNetPT

m = CostNetPT()
print("CostNetPT params:", sum(p.numel() for p in m.parameters()))
