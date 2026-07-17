"""Persona slug + user_id assignment (single source of truth).

`LEVEL2_SLUG` and `FALLBACK_KEYWORDS` used to live only in the gitignored
`tmp_3users_test/build_personas_from_xlsx.py`; they are hoisted here so any
version-controlled caller (e.g. `persona_intake.register_persona`) and the
batch script share one copy.

`assign_user_id` allocates the next free `{slug}_{NNN}` for a level2 by
scanning existing profile files. It always returns a *new* id — same-level2
users get distinct ids (licai_001, licai_002, ...).
"""
from __future__ import annotations

from pathlib import Path


LEVEL2_SLUG: dict[str, str] = {
    "应届生求职": "yingjie",
    "大学生效率": "xuesheng",
    "普通人理财": "licai",
    "城市漫游": "manbu",
    "AI工具应用": "zhao",
    "一人食日常": "yiren",
    "低能量自救": "zijiu",
    "社科通识": "tongshi",
    "普通男生改造": "nanshigaizao",
    "穷游周末": "qiongyou",
    "宏观经济解读": "hongguan",
    "公司研究": "gongsi",
    "消费观察": "xiaofei",
    "产业链分析": "chanyelian",
    "普通人财富管理": "caifu",
    "产业分析与股票投资": "gushi",
    "足球战术解读": "zhanlue",
    "球星故事": "qiuxing",
    "古典文学轻解读": "gudian",
    "非遗与民俗": "feiyi",
    "两性议题": "liangxing",
}

FALLBACK_KEYWORDS: dict[str, list[str]] = {
    "应届生求职": ["简历", "面试", "校招"],
    "大学生效率": ["论文", "备考", "科研"],
    "普通人理财": ["基金", "存款", "理财"],
    "城市漫游": ["博物馆", "城市漫步", "在地文化"],
    "AI工具应用": ["AI工具", "AI写作", "AI办公"],
    "一人食日常": ["一人食", "快手菜", "省钱食谱"],
    "低能量自救": ["情绪自救", "低能量", "自我修复"],
    "社科通识": ["社会学", "经济学", "通识"],
    "普通男生改造": ["男生穿搭", "学生党穿搭", "通勤穿搭"],
    "穷游周末": ["穷游", "周末游", "学生党旅行"],
    "宏观经济解读": ["宏观经济", "利率", "就业"],
    "公司研究": ["财报分析", "商业模式", "行业研究"],
    "消费观察": ["消费趋势", "新品牌", "消费观察"],
    "产业链分析": ["新能源", "AI硬件", "产业链"],
    "普通人财富管理": ["记账", "存钱", "基金"],
    "产业分析与股票投资": ["TMT", "人形机器人", "产业投资"],
    "足球战术解读": ["足球战术", "阵型", "跑位"],
    "球星故事": ["球星故事", "转会", "高光时刻"],
    "古典文学轻解读": ["古诗词", "文言文", "古典文学"],
    "非遗与民俗": ["非遗", "节气", "民俗"],
    "两性议题": ["亲密关系", "性别沟通", "两性议题"],
}

DEFAULT_SLUG = "persona"


def slug_for_level2(level2: str) -> str:
    """Return the slug for a level2 label, falling back to `persona`."""
    return LEVEL2_SLUG.get(level2, DEFAULT_SLUG)


def assign_user_id(level2: str, profiles_dir: str | Path) -> str:
    """Allocate the next free `{slug}_{NNN}` user_id for this level2.

    Scans `profiles_dir` for existing `{slug}_NNN.json` files and returns the
    lowest unused counter (fills gaps). A missing directory yields `_001`.
    """
    slug = slug_for_level2(level2)
    directory = Path(profiles_dir)
    existing = {p.stem for p in directory.glob("*.json")} if directory.is_dir() else set()
    counter = 1
    user_id = f"{slug}_{counter:03d}"
    while user_id in existing:
        counter += 1
        user_id = f"{slug}_{counter:03d}"
    return user_id
