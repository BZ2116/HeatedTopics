import json
from pathlib import Path


REQUIRED_SESSION_FILES = {
    "weibo": "weibo.json",
    "xiaohongshu": "xiaohongshu.json",
}


def _state_file_has_cookies(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    cookies = data.get("cookies", [])
    return isinstance(cookies, list) and len(cookies) > 0


def check_required_sessions(browser_state_dir: str | Path = "data/browser_state") -> dict[str, str]:
    root = Path(browser_state_dir)
    return {
        platform: "ok" if _state_file_has_cookies(root / file_name) else "login_required"
        for platform, file_name in REQUIRED_SESSION_FILES.items()
    }


def summarize_session_status(status: dict[str, str]) -> dict[str, list[str]]:
    ok = [platform for platform, value in status.items() if value == "ok"]
    missing = [platform for platform, value in status.items() if value != "ok"]
    commands = [f"uv run python -m src.browser.session_manager login {platform}" for platform in missing]
    return {
        "ok": ok,
        "missing": missing,
        "login_commands": commands,
    }
