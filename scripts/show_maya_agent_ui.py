"""Open the original Maya Agent panel and report only non-secret model settings."""
import importlib
import maya_agent
from maya_agent.utils.config import get_config

importlib.invalidate_caches()
maya_agent.bootstrap()
window = maya_agent.launch()
cfg = get_config()
provider = cfg.get("llm.active_provider", "deepseek")
result = {"window": str(window), "provider": provider,
          "provider_label": cfg.get("providers." + provider + ".label", provider),
          "model": cfg.get("providers." + provider + ".default_model", ""),
          "has_api_key": bool(cfg.get_api_key(provider))}
