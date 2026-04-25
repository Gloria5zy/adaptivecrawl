"""App Channel - 流量捕获 + LLM API 分析 + 协议重放"""

from __future__ import annotations
import json
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from ..models import PipelineState
from ..utils import get_llm


API_ANALYSIS_PROMPT = """你是一个 App 协议分析专家。分析以下 HTTP 请求/响应数据，识别 API 结构。

请返回 JSON 格式：
{{
    "apis": [
        {{
            "url": "API 地址",
            "method": "GET/POST",
            "params": {{"参数名": "参数描述"}},
            "auth_type": "none|token|sign|encrypt",
            "auth_details": "认证方式描述",
            "response_format": "json|html|xml|binary",
            "data_fields": ["响应中的数据字段"],
            "difficulty": "easy|medium|hard",
            "notes": "备注"
        }}
    ],
    "encryption_detected": true/false,
    "sign_algorithm_guess": "可能的签名算法",
    "recommended_approach": "direct_replay|need_reverse|need_device",
    "confidence": 0.0-1.0
}}
"""

REPLAY_CODE_PROMPT = """你是一个 Python 爬虫专家。根据以下 API 分析结果，生成可直接运行的协议重放代码。

API 信息：
{api_info}

采集目标：{goal}

要求：
- 使用 httpx 库
- 处理分页（如果有）
- 包含错误重试
- 输出结构化 JSON
- 代码可直接运行

请返回完整的 Python 代码。
"""


class TrafficLog:
    """解析抓包日志（mitmproxy HAR / JSON 格式）。"""

    def __init__(self, data: list[dict[str, Any]]):
        self.entries = data

    @classmethod
    def from_har(cls, har_path: str) -> "TrafficLog":
        """从 HAR 文件加载。"""
        with open(har_path, "r", encoding="utf-8") as f:
            har = json.load(f)
        entries = []
        for entry in har.get("log", {}).get("entries", []):
            req = entry.get("request", {})
            resp = entry.get("response", {})
            entries.append({
                "url": req.get("url", ""),
                "method": req.get("method", "GET"),
                "headers": {h["name"]: h["value"] for h in req.get("headers", [])},
                "query_params": {p["name"]: p["value"] for p in req.get("queryString", [])},
                "post_data": req.get("postData", {}).get("text", ""),
                "status": resp.get("status", 0),
                "response_body": resp.get("content", {}).get("text", "")[:2000],
                "response_mime": resp.get("content", {}).get("mimeType", ""),
            })
        return cls(entries)

    @classmethod
    def from_json_list(cls, data: list[dict]) -> "TrafficLog":
        """从 JSON 列表加载。"""
        return cls(data)

    def filter_api_requests(self) -> list[dict]:
        """过滤出可能的 API 请求（排除静态资源）。"""
        skip_ext = {".js", ".css", ".png", ".jpg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf"}
        skip_domains = {"google", "facebook", "analytics", "doubleclick", "cdn"}

        filtered = []
        for entry in self.entries:
            url = entry.get("url", "")
            if any(url.lower().endswith(ext) for ext in skip_ext):
                continue
            if any(d in url.lower() for d in skip_domains):
                continue
            if entry.get("response_mime", "").startswith(("application/json", "text/json", "text/html")):
                filtered.append(entry)
            elif entry.get("method") == "POST":
                filtered.append(entry)

        return filtered

    def summarize(self, max_entries: int = 20) -> str:
        """生成流量摘要供 LLM 分析。"""
        api_requests = self.filter_api_requests()[:max_entries]
        lines = []
        for i, req in enumerate(api_requests):
            lines.append(f"--- Request {i+1} ---")
            lines.append(f"URL: {req['url']}")
            lines.append(f"Method: {req['method']}")
            if req.get("query_params"):
                lines.append(f"Params: {json.dumps(req['query_params'], ensure_ascii=False)}")
            if req.get("post_data"):
                lines.append(f"Body: {req['post_data'][:500]}")
            lines.append(f"Status: {req['status']}")
            if req.get("response_body"):
                lines.append(f"Response: {req['response_body'][:300]}")
            lines.append("")
        return "\n".join(lines)


def analyze_traffic(traffic_log: TrafficLog, goal: str) -> dict[str, Any]:
    """用 LLM 分析抓包数据，识别 API 结构。"""
    llm = get_llm()
    summary = traffic_log.summarize()

    response = llm.invoke([
        SystemMessage(content=API_ANALYSIS_PROMPT),
        HumanMessage(content=f"采集目标：{goal}\n\n抓包数据：\n{summary}"),
    ])

    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        return {"error": "LLM 返回格式异常", "raw": response.content}


def generate_replay_code(api_info: dict, goal: str) -> str:
    """根据 API 分析结果生成协议重放代码。"""
    llm = get_llm()

    response = llm.invoke([
        SystemMessage(content=REPLAY_CODE_PROMPT.format(
            api_info=json.dumps(api_info, ensure_ascii=False, indent=2),
            goal=goal,
        )),
    ])

    # 提取代码块
    code = response.content
    code_match = re.search(r"```python\n(.*?)```", code, re.DOTALL)
    if code_match:
        code = code_match.group(1)
    return code


def app_channel(state: dict) -> dict:
    """App channel node for LangGraph。

    工作流程：
    1. 加载抓包数据（HAR/JSON）
    2. LLM 分析 API 结构
    3. 根据难度决定：直接重放 or 需要逆向 or 降级到群控
    4. 生成重放代码并执行
    """
    pipeline = PipelineState(**state)

    # 检查是否有抓包数据
    traffic_data = state.get("traffic_data")
    traffic_file = state.get("traffic_file")

    if traffic_file:
        traffic_log = TrafficLog.from_har(traffic_file)
    elif traffic_data:
        traffic_log = TrafficLog.from_json_list(traffic_data)
    else:
        return {
            "error": "App 通道需要提供抓包数据（traffic_data 或 traffic_file）",
            "current_step": "error",
        }

    # LLM 分析 API
    analysis = analyze_traffic(traffic_log, pipeline.request.goal)

    if analysis.get("error"):
        return {"error": analysis["error"], "current_step": "error"}

    # 根据推荐方案决定下一步
    approach = analysis.get("recommended_approach", "direct_replay")

    if approach == "need_device":
        # 降级到群控通道
        return {
            "error": "API 加密复杂，建议降级到群控通道",
            "current_step": "fallback_to_farm",
        }

    # 生成重放代码
    apis = analysis.get("apis", [])
    if apis:
        replay_code = generate_replay_code(apis[0], pipeline.request.goal)
    else:
        replay_code = ""

    # 将分析结果作为 raw_content 传给 Parser
    raw_content = json.dumps({
        "api_analysis": analysis,
        "replay_code": replay_code,
        "api_responses": [e.get("response_body", "") for e in traffic_log.filter_api_requests()[:5]],
    }, ensure_ascii=False)

    return {
        "raw_content": raw_content,
        "current_step": "fetched",
    }
