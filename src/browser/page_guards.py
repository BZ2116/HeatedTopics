"""检测登录页、验证码、滑块、风控页"""
from playwright.sync_api import Page


def detect_page_guard(page: Page) -> str | None:
    """检测当前页面是否需要停止采集

    返回:
        None: 正常页面
        "login_required": 需要登录
        "captcha_required": 需要验证码
        "slider_detected": 检测到滑块验证
        "risk_control": 风控拦截页
    """
    url = page.url.lower()
    title = page.title().lower()

    # 登录页：URL 含 login、sign，页面标题含登录/注册
    if "login" in url or "sign" in url:
        if "登录" in title or "注册" in title or "login" in title or "sign" in title:
            return "login_required"

    # 风控页：URL 含 risk、security，页面标题含风控/安全验证
    if "risk" in url or "security" in url:
        if "风控" in title or "安全验证" in title or "risk" in title:
            return "risk_control"

    # 验证码：页面元素含 验证码/captcha/验证/安全验证
    captcha_keywords = ["验证码", "captcha", "安全验证", "请拖动", "验证完成"]
    for keyword in captcha_keywords:
        if keyword in title:
            return "captcha_required"

    # 滑块：页面元素含 滑块/验证/拼图
    slider_keywords = ["滑块", "拼图", "拖动", "完成验证", "slider"]
    for keyword in slider_keywords:
        if keyword in title:
            return "slider_detected"

    return None