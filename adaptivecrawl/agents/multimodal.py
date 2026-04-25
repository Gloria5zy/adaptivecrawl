"""Multimodal Parsers - PDF / Table / Image / Video 统一解析"""

from __future__ import annotations
import base64
import json
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from ..utils import get_llm


# ── PDF Parser ──────────────────────────────────────────────

PDF_PROMPT = """你是一个 PDF 文档解析专家。请从以下 PDF 文本内容中，根据采集目标提取结构化数据。

采集目标：{goal}

请返回 JSON 格式：
{{
    "fields": {{"字段名": "字段描述"}},
    "data": [{{"字段名": "值"}}],
    "tables": [
        {{"title": "表格标题", "headers": ["列1", "列2"], "rows": [["值1", "值2"]]}}
    ],
    "confidence": 0.0-1.0
}}
"""


def parse_pdf(content: bytes, goal: str) -> dict[str, Any]:
    """解析 PDF 文件，提取文本和表格。"""
    try:
        import pdfplumber
        import io

        text_parts = []
        tables = []

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

                for table in page.extract_tables():
                    if table and len(table) > 1:
                        headers = [str(h or "") for h in table[0]]
                        rows = [[str(c or "") for c in row] for row in table[1:]]
                        tables.append({"headers": headers, "rows": rows})

        full_text = "\n".join(text_parts)

        llm = get_llm()
        response = llm.invoke([
            SystemMessage(content=PDF_PROMPT.format(goal=goal)),
            HumanMessage(content=f"PDF 文本内容：\n{full_text[:10000]}"),
        ])

        result = json.loads(response.content)
        if tables and not result.get("tables"):
            result["tables"] = tables
        return result

    except ImportError:
        return {"error": "需要安装 pdfplumber: pip install pdfplumber", "data": []}
    except Exception as e:
        return {"error": str(e), "data": []}


# ── Table Parser ────────────────────────────────────────────

TABLE_PROMPT = """你是一个表格数据解析专家。请分析以下 HTML 表格，根据采集目标提取结构化数据。

采集目标：{goal}

HTML 表格：
{table_html}

请返回 JSON 格式：
{{
    "title": "表格标题（推断）",
    "headers": ["列名1", "列名2"],
    "rows": [["值1", "值2"]],
    "summary": "表格内容摘要",
    "confidence": 0.0-1.0
}}
"""


def parse_tables_from_html(html: str, goal: str) -> list[dict[str, Any]]:
    """从 HTML 中提取所有表格并结构化。"""
    table_pattern = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
    tables_html = table_pattern.findall(html)

    if not tables_html:
        return []

    results = []
    llm = get_llm()

    for i, table_html in enumerate(tables_html[:5]):
        if len(table_html) > 8000:
            table_html = table_html[:8000] + "...</table>"

        try:
            response = llm.invoke([
                SystemMessage(content=TABLE_PROMPT.format(goal=goal, table_html=table_html)),
            ])
            parsed = json.loads(response.content)
            parsed["table_index"] = i
            results.append(parsed)
        except Exception:
            continue

    return results


# ── Image Parser ────────────────────────────────────────────

IMAGE_PROMPT = """你是一个图片内容分析专家。请分析这张图片，根据采集目标提取信息。

采集目标：{goal}

请返回 JSON 格式：
{{
    "description": "图片内容描述",
    "text_content": "图片中的文字（OCR）",
    "data": [{{"字段名": "值"}}],
    "image_type": "photo|chart|table|diagram|screenshot|other",
    "confidence": 0.0-1.0
}}
"""


def parse_image(image_b64: str, goal: str) -> dict[str, Any]:
    """用多模态 LLM 解析图片内容。"""
    llm = get_llm(model="gpt-4o")

    try:
        response = llm.invoke([
            SystemMessage(content=IMAGE_PROMPT.format(goal=goal)),
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]),
        ])
        return json.loads(response.content)
    except Exception as e:
        return {"error": str(e), "data": []}


def extract_images_from_html(html: str) -> list[str]:
    """从 HTML 中提取图片 URL。"""
    img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
    return img_pattern.findall(html)


# ── Video/Subtitle Parser ──────────────────────────────────

def parse_video_subtitles(video_url: str) -> dict[str, Any]:
    """提取视频字幕。"""
    try:
        import subprocess
        result = subprocess.run(
            ["yt-dlp", "--write-auto-sub", "--sub-lang", "zh,en",
             "--skip-download", "--print-json", video_url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            subtitles = info.get("subtitles", {}) or info.get("automatic_captions", {})
            return {"subtitles": subtitles, "title": info.get("title", "")}
    except Exception:
        pass

    return {"error": "字幕提取失败，需要安装 yt-dlp", "subtitles": {}}


# ── Content Type Detector ───────────────────────────────────

def detect_content_types(url: str, html: str) -> dict[str, Any]:
    """自动检测页面中包含的内容类型。"""
    result = {
        "content_types": ["html"],
        "has_pdf_links": False,
        "has_tables": False,
        "has_images": False,
        "has_video": False,
        "pdf_urls": [],
        "video_urls": [],
    }

    # PDF 链接
    pdf_pattern = re.compile(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', re.IGNORECASE)
    pdf_urls = pdf_pattern.findall(html)
    if pdf_urls:
        result["has_pdf_links"] = True
        result["pdf_urls"] = pdf_urls[:10]
        result["content_types"].append("pdf")

    # 表格
    if re.search(r"<table[\s>]", html, re.IGNORECASE):
        result["has_tables"] = True
        result["content_types"].append("table")

    # 图片
    images = extract_images_from_html(html)
    if images:
        result["has_images"] = True
        result["content_types"].append("image")

    # 视频
    video_pattern = re.compile(
        r'(youtube\.com/watch|youtu\.be/|<video[\s>]|<iframe[^>]*(?:youtube|vimeo|bilibili))',
        re.IGNORECASE,
    )
    if video_pattern.search(html):
        result["has_video"] = True
        result["content_types"].append("video")

    return result
