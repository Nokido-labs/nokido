import sys

sys.path.insert(0, __import__("os").path.expanduser("~/Script python IA/LaForge/app"))
from nokido_agent.app.forge_perception_vlm import get_vlm_model

m = get_vlm_model()
print(f"vlm: {m}")
