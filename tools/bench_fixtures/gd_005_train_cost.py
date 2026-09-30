import sys

sys.path.insert(0, __import__("os").path.expanduser("~/Script python IA/LaForge/tools"))
sys.path.insert(0, __import__("os").path.expanduser("~/Script python IA/LaForge/app"))
from nokido_agent.tools.forge_pytorch_nets import train_cost

r = train_cost(epochs=3, lr=1e-3)
print(r)
