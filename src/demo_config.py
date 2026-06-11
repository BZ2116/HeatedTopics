from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"

DAILY_HOT_API_BASES = [
    "https://api-hot.imsyy.top",
    "https://dailyhot.imsyy.top",
]
JINA_READER_PREFIX = "https://r.jina.ai/"
JINA_SEARCH_PREFIX = "https://s.jina.ai/"

PLATFORMS = [
    "weibo",
    "baidu",
    "zhihu",
    "bilibili",
    "36kr",
    "ithome",
]

FALLBACK_PLATFORMS = [
    "weibo",
    "baidu",
    "zhihu",
    "36kr",
]

TOP_N_PER_PLATFORM = 10
TOP_N_FOR_SELECTION = 5
MIN_SELECTED_TOPICS = 5
MAX_SELECTED_TOPICS = 8

HOT_LIST_PATH = DATA_DIR / "hot_list.json"
SELECTED_TOPICS_PATH = DATA_DIR / "selected_topics.json"
TOPIC_SOURCES_PATH = DATA_DIR / "topic_sources.json"
HOT_TOPIC_CARDS_PATH = REPORTS_DIR / "hot_topic_cards.md"
DAILY_DIGEST_PATH = REPORTS_DIR / "daily_digest_demo.md"
DAILY_DIGEST_HTML_PATH = REPORTS_DIR / "daily_digest_demo.html"
