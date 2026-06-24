from src.core_pipeline.providers.weibo_hot import parse_weibo_hot_text


def test_parse_weibo_hot_text_extracts_rank_title_and_heat():
    records = parse_weibo_hot_text(
        "\n".join(
            [
                "微博热搜",
                "1 河北高考分数线 1720555 新",
                "2 民警称女孩自愿发生关系不属强奸 1719147 新",
                "• 广告话题 重磅",
            ]
        ),
        captured_at="2026-06-24T08:00:00+08:00",
        max_items=1,
    )

    assert len(records) == 1
    assert records[0].platform == "weibo"
    assert records[0].rank == 1
    assert records[0].title == "河北高考分数线"
    assert records[0].hot_value == "1720555"
    assert records[0].url == "https://s.weibo.com/weibo?q=%E6%B2%B3%E5%8C%97%E9%AB%98%E8%80%83%E5%88%86%E6%95%B0%E7%BA%BF"
