"""Static contract assertions for the anonymous news providers.

These tests guard the class-level attributes (`platform`, `weights`,
`absolute_floors`) that `_collect_news_platform` and `discover_platform_articles`
read from each provider instance.
"""

from __future__ import annotations

import httpx

from heated_topics_v3.providers.baidu_hot import (
    BAIDU_ABSOLUTE_FLOORS,
    BAIDU_WEIGHTS,
    BaiduHotProvider,
)
from heated_topics_v3.providers.netease_news import (
    NETEASE_ABSOLUTE_FLOORS,
    NETEASE_WEIGHTS,
    NeteaseNewsProvider,
)
from heated_topics_v3.providers.sina_news import (
    SINA_ABSOLUTE_FLOORS,
    SINA_WEIGHTS,
    SinaNewsProvider,
)
from heated_topics_v3.providers.thepaper import (
    THEPAPER_ABSOLUTE_FLOORS,
    THEPAPER_WEIGHTS,
    ThePaperProvider,
)
from heated_topics_v3.providers.zhihu_daily import (
    ZHIHU_DAILY_ABSOLUTE_FLOORS,
    ZHIHU_DAILY_WEIGHTS,
    ZhihuDailyProvider,
)


def _instantiate(cls):
    """Instantiate with an unused httpx client; the providers do not touch it
    during the static attribute checks performed here."""
    return cls(httpx.Client())


def test_sina_news_provider_attributes_match_spec():
    provider = _instantiate(SinaNewsProvider)
    assert provider.platform == "sina_news"
    assert dict(provider.weights) == SINA_WEIGHTS
    assert dict(provider.absolute_floors) == SINA_ABSOLUTE_FLOORS
    assert provider.weights == {"top_num": 0.70, "comments": 0.30}
    assert provider.absolute_floors == {"comments": 10.0}


def test_thepaper_provider_attributes_match_spec():
    provider = _instantiate(ThePaperProvider)
    assert provider.platform == "thepaper"
    assert dict(provider.weights) == THEPAPER_WEIGHTS
    assert dict(provider.absolute_floors) == THEPAPER_ABSOLUTE_FLOORS
    assert provider.weights == {"interaction_num": 0.60, "praise_times": 0.40}
    assert provider.absolute_floors == {
        "interaction_num": 1.0,
        "praise_times": 10.0,
    }


def test_netease_news_provider_attributes_match_spec():
    provider = _instantiate(NeteaseNewsProvider)
    assert provider.platform == "netease_news"
    assert dict(provider.weights) == NETEASE_WEIGHTS
    assert dict(provider.absolute_floors) == NETEASE_ABSOLUTE_FLOORS
    assert provider.weights == {
        "hot_value": 0.40,
        "click": 0.30,
        "comments": 0.15,
        "votes": 0.10,
        "thread_votes": 0.05,
    }
    assert provider.absolute_floors == {"comments": 10.0}
    assert abs(sum(provider.weights.values()) - 1.0) < 1e-9


def test_baidu_hot_provider_attributes_match_spec():
    provider = _instantiate(BaiduHotProvider)
    assert provider.platform == "baidu_hot"
    assert dict(provider.weights) == BAIDU_WEIGHTS
    assert dict(provider.absolute_floors) == BAIDU_ABSOLUTE_FLOORS
    assert provider.weights == {"hot_score": 1.0}
    assert provider.absolute_floors == {"hot_score": 1.0}


def test_zhihu_daily_provider_attributes_match_spec():
    provider = _instantiate(ZhihuDailyProvider)
    assert provider.platform == "zhihu_daily"
    assert dict(provider.weights) == ZHIHU_DAILY_WEIGHTS
    assert dict(provider.absolute_floors) == ZHIHU_DAILY_ABSOLUTE_FLOORS
    assert provider.weights == {}
    assert provider.absolute_floors == {}