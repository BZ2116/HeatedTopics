"""登录态管理模块

支持 check 和 login 两个子命令：
  python -m src.browser.session_manager check
  python -m src.browser.session_manager login weibo
  python -m src.browser.session_manager login xiaohongshu
"""
import json
import os
import sys
from pathlib import Path

PLATFORM_LOGIN_URLS = {
    "weibo": "https://login.sina.com.cn/signup/signup.php",
    "xiaohongshu": "https://www.xiaohongshu.com",
}

STATE_DIR = Path("data/browser_state")
STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_state_path(platform: str) -> Path:
    return STATE_DIR / f"{platform}.json"


def check_session(platform: str) -> dict:
    """检查指定平台的登录态文件是否存在且有效

    返回:
        {"status": "valid"|"missing"|"expired", "path": "..."}
    """
    path = get_state_path(platform)
    if not path.exists():
        return {"status": "missing", "path": str(path)}

    try:
        with open(path) as f:
            data = json.load(f)
        # 检查基本结构
        if not isinstance(data, dict):
            return {"status": "expired", "path": str(path)}
        return {"status": "valid", "path": str(path)}
    except (json.JSONDecodeError, IOError):
        return {"status": "expired", "path": str(path)}


def check_all_sessions() -> dict:
    """返回 {platform: status} 字典"""
    return {platform: check_session(platform)["status"] for platform in PLATFORM_LOGIN_URLS}


def login(platform: str) -> bool:
    """打开 Playwright 浏览器，等待用户手动登录，完成后保存 storage_state

    1. 用 playwright.launch PersistentContext
    2. 导航到微博/小红书登录页
    3. 等待用户操作（检测到已登录状态或用户按 Enter 确认）
    4. 保存 storage_state 到 data/browser_state/{platform}.json
    5. 关闭浏览器
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要先安装 Playwright：pip install playwright && playwright install chromium")
        sys.exit(1)

    if platform not in PLATFORM_LOGIN_URLS:
        print(f"未知平台: {platform}，支持的平台: {list(PLATFORM_LOGIN_URLS.keys())}")
        sys.exit(1)

    login_url = PLATFORM_LOGIN_URLS[platform]
    state_path = get_state_path(platform)

    print(f"正在启动浏览器，请手动登录 {platform}...")
    print(f"登录页面: {login_url}")
    print("登录完成后按 Enter 确认保存，或按 Ctrl+C 取消")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(state_path.parent / f"{platform}_browser_data"),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(login_url)

        input("请在浏览器中完成登录，然后按 Enter 保存登录态...")

        # 保存 storage_state
        storage_state = context.storage_state()
        with open(state_path, "w") as f:
            json.dump(storage_state, f)

        print(f"登录态已保存到: {state_path}")
        context.close()

    return True


def main():
    if len(sys.argv) < 2:
        print("用法: python -m src.browser.session_manager <check|login> [platform]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "check":
        results = check_all_sessions()
        for platform, status in results.items():
            print(f"{platform}: {status}")
    elif command == "login":
        if len(sys.argv) < 3:
            print("用法: python -m src.browser.session_manager login <platform>")
            sys.exit(1)
        platform = sys.argv[2]
        login(platform)
    else:
        print(f"未知命令: {command}，支持的命令: check, login")
        sys.exit(1)


if __name__ == "__main__":
    main()