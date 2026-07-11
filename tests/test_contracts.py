from heated_topics_v3.contracts import HeatMetrics, HotItem, TopicCluster


def test_hot_item_keeps_heat_metrics_and_raw_payload():
    item = HotItem(
        item_id="juejin_7659763781161730102",
        platform="juejin",
        item_type="article",
        title="React Fiber runtime",
        url="https://juejin.cn/post/7659763781161730102",
        rank=1,
        heat=HeatMetrics(
            value=5886,
            label="5886",
            metric_name="hot_rank",
            metrics={"views": 12525, "likes": 18},
        ),
        summary="",
        category="tech_article",
        matched_query_ids=("tech_ai_creator_q_001_core_hot",),
        fetched_at="2026-07-11T13:28:53+08:00",
        fetch_status="success",
        raw_payload={"content_id": "7659763781161730102"},
    )

    assert item.heat.value == 5886
    assert item.raw_payload["content_id"] == "7659763781161730102"


def test_topic_cluster_groups_hot_items_for_downstream_use():
    cluster = TopicCluster(
        topic_id="topic_react_fiber_runtime",
        canonical_title="React Fiber runtime",
        source_item_ids=("juejin_7659763781161730102",),
        platforms=("juejin",),
        matched_profile_ids=("tech_ai_creator",),
        summary="A technical topic about React internals.",
        is_usable=True,
        confidence="medium",
    )

    assert cluster.is_usable is True
    assert cluster.platforms == ("juejin",)
