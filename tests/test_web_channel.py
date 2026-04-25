"""测试：Web Channel Playwright 端到端（需要网络）"""

import asyncio
from adaptivecrawl.channels.web import _fetch_page


def test_fetch_static_page():
    """抓取静态页面。"""
    html, screenshot = asyncio.run(_fetch_page(
        "https://example.com",
        wait_for_spa=False,
        delay=0,
    ))
    assert "Example Domain" in html
    assert screenshot is not None
    assert len(screenshot) > 100  # base64 截图不为空
    print(f"✅ 静态页面抓取：HTML {len(html)} chars, 截图 {len(screenshot)} chars")


def test_fetch_with_spa_wait():
    """抓取页面并等待 SPA 渲染。"""
    html, screenshot = asyncio.run(_fetch_page(
        "https://quotes.toscrape.com/",
        wait_for_spa=True,
        delay=0.5,
    ))
    assert "quote" in html.lower() or "Quotes" in html
    print(f"✅ SPA 等待抓取：HTML {len(html)} chars")


if __name__ == "__main__":
    test_fetch_static_page()
    test_fetch_with_spa_wait()
    print("\n🎉 Web Channel 测试通过！")
