"""Adaptive Parser Agent - LLM 智能页面解析 + 多模态统一提取"""

from __future__ import annotations
import json
import httpx
import base64
from langchain_core.messages import SystemMessage, HumanMessage

from ..models import PipelineState, ParseRule, CrawlResult, ChannelType
from ..utils import get_llm
from .multimodal import (
    detect_content_types,
    parse_tables_from_html,
    parse_pdf,
    parse_image,
    extract_images_from_html,
    parse_video_subtitles,
)

PARSER_PROMPT = """你是一个智能页面解析 Agent。根据页面内容和采集目标，自动识别数据结构并提取信息。

采集目标：{goal}

请分析页面内容，返回 JSON 格式：
{{
    "fields": {{"字段名": "字段描述", ...}},
    "data": [
        {{"字段名": "提取的值", ...}},
        ...
    ],
    "confidence": 0.0-1.0
}}

注意：
- 自动识别页面中与目标相关的数据
- 如果页面是列表页，提取所有条目
- 如果页面是详情页，提取关键信息
- confidence 表示你对提取结果的信心
"""


def _fetch_pdf(url: str) -> bytes | None:
    """下载 PDF 文件。"""
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        if resp.status_code == 200 and b"%PDF" in resp.content[:10]:
            return resp.content
    except Exception:
        pass
    return None


def _fetch_image_b64(url: str) -> str | None:
    """下载图片并转为 base64。"""
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        if resp.status_code == 200:
            return base64.b64encode(resp.content).decode()
    except Exception:
        pass
    return None


def parser_agent(state: dict) -> dict:
    """Adaptive Parser Agent - 支持多模态统一提取。"""
    pipeline = PipelineState(**state)
    llm = get_llm()

    goal = pipeline.request.goal
    content = pipeline.raw_content
    url = pipeline.request.url or ""

    all_extracted = []
    all_tables = []
    all_images_data = []
    all_pdf_data = []
    overall_confidence = 0.0

    # ── Step 1: 检测内容类型 ──
    content_info = detect_content_types(url, content)

    # ── Step 2: HTML 文本解析（始终执行）──
    truncated = content[:15000] if len(content) > 15000 else content
    messages = [
        SystemMessage(content=PARSER_PROMPT.format(goal=goal)),
        HumanMessage(content=f"页面内容：\n{truncated}"),
    ]

    if pipeline.screenshot_b64:
        messages.append(HumanMessage(content=[
            {"type": "text", "text": "页面截图，请结合截图和 HTML 分析："},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{pipeline.screenshot_b64}"}},
        ]))

    try:
        response = llm.invoke(messages)
        parsed = json.loads(response.content)
        all_extracted.extend(parsed.get("data", []))
        overall_confidence = max(overall_confidence, parsed.get("confidence", 0.5))
    except Exception:
        pass

    # ── Step 3: 表格提取 ──
    if content_info["has_tables"]:
        tables = parse_tables_from_html(content, goal)
        all_tables.extend(tables)
        for t in tables:
            overall_confidence = max(overall_confidence, t.get("confidence", 0.5))

    # ── Step 4: PDF 提取 ──
    if content_info["has_pdf_links"]:
        for pdf_url in content_info["pdf_urls"][:3]:  # 最多处理 3 个 PDF
            if not pdf_url.startswith("http"):
                # 相对路径转绝对路径
                from urllib.parse import urljoin
                pdf_url = urljoin(url, pdf_url)

            pdf_bytes = _fetch_pdf(pdf_url)
            if pdf_bytes:
                pdf_result = parse_pdf(pdf_bytes, goal)
                if pdf_result.get("data"):
                    all_pdf_data.append({"url": pdf_url, **pdf_result})
                    all_extracted.extend(pdf_result["data"])

    # ── Step 5: 关键图片解析 ──
    if content_info["has_images"]:
        image_urls = extract_images_from_html(content)
        # 只解析可能包含数据的图片（过滤小图标）
        for img_url in image_urls[:3]:
            if any(skip in img_url.lower() for skip in ["icon", "logo", "avatar", "emoji", "1x1"]):
                continue
            if not img_url.startswith("http"):
                from urllib.parse import urljoin
                img_url = urljoin(url, img_url)

            img_b64 = _fetch_image_b64(img_url)
            if img_b64 and len(img_b64) > 1000:  # 跳过太小的图片
                img_result = parse_image(img_b64, goal)
                if img_result.get("data"):
                    all_images_data.append({"url": img_url, **img_result})
                    all_extracted.extend(img_result["data"])

    # ── Step 6: 汇总结果 ──
    parse_rule = ParseRule(
        fields=parsed.get("fields", {}) if "parsed" in dir() else {},
        confidence=overall_confidence,
    )

    # 构建完整结果
    result_metrics = {
        "confidence": overall_confidence,
        "record_count": len(all_extracted),
        "content_types": content_info["content_types"],
        "tables_found": len(all_tables),
        "pdfs_parsed": len(all_pdf_data),
        "images_parsed": len(all_images_data),
    }

    result = CrawlResult(
        url=url,
        channel=pipeline.plan.channel if pipeline.plan else ChannelType.WEB,
        raw_html=content[:1000],
        extracted_data=all_extracted,
        parse_rule=parse_rule,
        success=len(all_extracted) > 0,
        metrics=result_metrics,
    )

    # 附加多模态数据到 metrics
    if all_tables:
        result.metrics["tables"] = all_tables
    if all_pdf_data:
        result.metrics["pdf_data"] = all_pdf_data
    if all_images_data:
        result.metrics["image_data"] = all_images_data

    results = pipeline.results + [result]
    return {
        "results": results,
        "parse_rule": parse_rule if result.success else None,
        "current_step": "parsed",
    }
