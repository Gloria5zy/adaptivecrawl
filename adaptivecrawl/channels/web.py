"""Web Channel - Playwright 浏览器自动化采集（增强版）"""

from __future__ import annotations
import asyncio
import base64
import random
from playwright.async_api import async_playwright

from ..models import PipelineState

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


async def _fetch_page(
    url: str,
    proxy: str | None = None,
    delay: float = 0.0,
    wait_for_spa: bool = True,
) -> tuple[str, str | None]:
    """使用 Playwright 获取页面内容和截图。"""
    if delay > 0:
        await asyncio.sleep(delay)

    launch_opts: dict = {"headless": True}
    if proxy:
        launch_opts["proxy"] = {"server": proxy}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_opts)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            if wait_for_spa:
                await _wait_for_spa_render(page)

            html = await page.content()
            screenshot_bytes = await page.screenshot(full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
            return html, screenshot_b64
        except Exception as e:
            try:
                html = await page.content()
                return html, None
            except Exception:
                return f"<error>{str(e)}</error>", None
        finally:
            await browser.close()


async def _wait_for_spa_render(page, timeout_ms: int = 10000):
    """智能等待 SPA 渲染完成：networkidle + DOM 稳定 + 懒加载触发。"""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass

    # DOM 稳定检测：连续 500ms 无变化
    try:
        await page.evaluate("""
            () => new Promise((resolve) => {
                let timer;
                const observer = new MutationObserver(() => {
                    clearTimeout(timer);
                    timer = setTimeout(() => { observer.disconnect(); resolve(); }, 500);
                });
                observer.observe(document.body, { childList: true, subtree: true });
                timer = setTimeout(() => { observer.disconnect(); resolve(); }, 3000);
            })
        """)
    except Exception:
        pass

    # 滚动触发懒加载
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await asyncio.sleep(0.5)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


def web_channel(state: dict) -> dict:
    """Web channel node for LangGraph."""
    pipeline = PipelineState(**state)
    url = pipeline.request.url

    if not url:
        return {"error": "Web 通道需要提供 URL", "current_step": "error"}

    html, screenshot_b64 = asyncio.run(_fetch_page(
        url=url,
        wait_for_spa=True,
        delay=random.uniform(0.5, 1.5),
    ))

    return {
        "raw_content": html,
        "screenshot_b64": screenshot_b64,
        "current_step": "fetched",
    }
