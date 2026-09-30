import sys

import torch

sys.path.insert(0, __import__("os").path.expanduser("~/Script python IA/LaForge/tools"))
from nokido_agent.tools.forge_pytorch_world_model import TorchNMLP

m = TorchNMLP()
x = torch.randn(4, 768)
y = m(x)
print("shape:", y.shape)
