"""Platform providers for V3 hot-list collection."""

from .baidu_hot import BaiduHotProvider
from .common import ProviderCapture
from .juejin import JuejinProvider
from .netease_news import NeteaseNewsProvider
from .sina_news import SinaNewsProvider
from .thepaper import ThePaperProvider
from .toutiao import ToutiaoProvider
from .zhihu_daily import ZhihuDailyProvider
from .zhihu_hot import ZhihuHotProvider

__all__ = [
    "BaiduHotProvider",
    "ProviderCapture",
    "JuejinProvider",
    "NeteaseNewsProvider",
    "SinaNewsProvider",
    "ThePaperProvider",
    "ToutiaoProvider",
    "ZhihuDailyProvider",
    "ZhihuHotProvider",
]