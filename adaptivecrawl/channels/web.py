"""Web Channel - Playwright 浏览器自动化采集"""

from __future__ import annotations
import asyncio
import base64
from playwright.async_api import async_playwright

from ..models import PipelineState


async def _fetch_page(url: str, wait_for: str = "networkidle") -> tuple[str, str | None]:
    """使用 Playwright 获取页面内容和截图。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # 等待页面稳定（处理动态渲染）
            try:
                await page.wait_for_load_state(wait_for, timeout=10000)
            except Exception:
                pass  # 超时也继续，页面可能已经够用了

            # 获取页面内容
            html = await page.content()

            # 截图（用于多模态 LLM 分析）
            screenshot_bytes = await page.screenshot(full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

            return html, screenshot_b64
        except Exception as e:
            return f"<error>{str(e)}</error>", None
        finally:
            await browser.close()


def web_channel(state: dict) -> dict:
    """Web channel node for LangGraph."""
    pipeline = PipelineState(**state)
    url = pipeline.request.url

    if not url:
        return {"error": "Web 通道需要提供 URL", "current_step": "error"}

    html, screenshot_b64 = asyncio.run(_fetch_page(url))

    return {
        "raw_content": html,
        "screenshot_b64": screenshot_b64,
        "current_step": "fetched",
    }
