"""Platform providers for V3 hot-list collection."""

from .common import ProviderCapture
from .juejin import JuejinProvider
from .sina_news import SinaNewsProvider
from .thepaper import ThePaperProvider
from .toutiao import ToutiaoProvider

__all__ = [
    "ProviderCapture",
    "JuejinProvider",
    "SinaNewsProvider",
    "ThePaperProvider",
    "ToutiaoProvider",
]
