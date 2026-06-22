#!/usr/bin/env python3
"""采集多平台热点标题到 data/raw/hot_records.json"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.demo_config import DAILY_HOT_API_BASES
from src.hot_topic_types import HotRecord
from src.fetch_hot_lists import fetch_platform, daily_hot_api_bases, extract_items
from urllib.error import URLError


PLATFORMS = [
    "weibo", "baidu", "zhihu", "bilibili",  # 国内大众
    "36kr", "ithome", "juejin", "csdn",      # 国内科技商业
    "github", "v2ex", "hellogithub",         # 国外/技术社区
]

TOP_N_PER_PLATFORM = 20  # 每个平台采集 10-20 条


def fetch_platform_raw(platform: str, limit: int = TOP_N_PER_PLATFORM) -> dict:
    """采集单个平台，返回原始数据用于 raw_payload"""
    # 优先使用本地 API
    bases = ["http://localhost:6688"] + daily_hot_api_bases()
    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for base in bases:
        url = f"{base.rstrip('/')}/{platform}"
        try:
            from urllib.request import urlopen
            with urlopen(url, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return {
                "success": False,
                "platform": platform,
                "url": url,
                "error": str(exc),
                "raw_payload": None,
                "records": []
            }

        records = []
        items = extract_items(payload)
        for index, item in enumerate(items[:limit]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or item.get("word") or "").strip()
            if not title:
                continue
            records.append({
                "title": title,
                "rank": int(item.get("rank") or index + 1),
                "hot_value": str(item.get("hot") or item.get("desc") or item.get("heat") or item.get("views") or ""),
                "url": str(item.get("url") or item.get("mobilUrl") or item.get("mobileUrl") or item.get("link") or ""),
            })

        if records:
            return {
                "success": True,
                "platform": platform,
                "url": url,
                "error": None,
                "raw_payload": payload,
                "records": records
            }

    return {
        "success": False,
        "platform": platform,
        "url": url if 'url' in locals() else "",
        "error": "empty data",
        "raw_payload": None,
        "records": []
    }


def get_category(platform: str) -> str:
    """根据平台返回分类"""
    categories = {
        "weibo": "social",
        "baidu": "search",
        "zhihu": "q&a",
        "bilibili": "video",
        "36kr": "tech_business",
        "ithome": "tech",
        "juejin": "tech",
        "csdn": "tech",
        "github": "code",
        "v2ex": "tech",
        "hellogithub": "code",
    }
    return categories.get(platform, "unknown")


def main():
    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_records = []
    record_id = 1
    success_count = 0
    fail_count = 0

    for platform in PLATFORMS:
        print(f"采集 {platform}...", end=" ")
        result = fetch_platform_raw(platform)

        if result["success"]:
            success_count += 1
            for item in result["records"]:
                all_records.append({
                    "id": f"hot_{record_id:03d}",
                    "source": platform,
                    "platform": platform,
                    "category": get_category(platform),
                    "title": item["title"],
                    "rank": item["rank"],
                    "hot_value": item["hot_value"],
                    "url": item["url"],
                    "captured_at": captured_at,
                    "raw_payload": result["raw_payload"],
                    "fetch_status": "success",
                    "error": None
                })
                record_id += 1
            print(f"OK ({len(result['records'])} 条)")
        else:
            fail_count += 1
            all_records.append({
                "id": f"hot_{record_id:03d}",
                "source": platform,
                "platform": platform,
                "category": get_category(platform),
                "title": "",
                "rank": 0,
                "hot_value": "",
                "url": result["url"],
                "captured_at": captured_at,
                "raw_payload": result["raw_payload"],
                "fetch_status": "failed",
                "error": result["error"]
            })
            record_id += 1
            print(f"失败 ({result['error']})")

    # 写入文件
    output_path = Path("/Users/BZ/code/heatedTopics/data/raw/hot_records.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 输出摘要
    total_records = len(all_records)
    print(f"\n采集摘要：共采集 {total_records} 条，来自 {success_count} 个平台。")
    if fail_count > 0:
        print(f"失败平台数：{fail_count}，错误详情已记录在文件中。")


if __name__ == "__main__":
    main()