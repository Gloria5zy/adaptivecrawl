"""App Channel - 流量捕获 + LLM API 分析 + 协议重放 + Frida 集成"""

from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from ..models import PipelineState
from ..utils import get_llm


# ═══════════════════════════════════════════════════════════
#  Prompts
# ═══════════════════════════════════════════════════════════

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
            "encrypted_fields": ["被加密的参数名"],
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

FRIDA_HOOK_PROMPT = """你是一个 Android/iOS 逆向工程专家。根据以下 API 加密信息，生成 Frida hook 脚本。

加密信息：
- 加密字段：{encrypted_fields}
- 可能的算法：{algorithm_guess}
- API URL 模式：{url_pattern}

请生成 Frida JavaScript hook 脚本，目标是：
1. Hook 可能的加密/签名函数
2. 打印函数的输入参数和返回值
3. 尝试 hook 常见的加密库（如 javax.crypto, CryptoJS, CommonCrypto）

返回完整的 Frida 脚本代码。
"""


# ═══════════════════════════════════════════════════════════
#  TrafficLog - 多格式抓包数据解析
# ═══════════════════════════════════════════════════════════

class TrafficLog:
    """解析抓包日志，支持 HAR(mitmproxy/Charles) / Charles JSON Session / 原始 JSON。"""

    def __init__(self, data: list[dict[str, Any]]):
        self.entries = data

    @classmethod
    def from_har(cls, har_path: str) -> "TrafficLog":
        """从 HAR 文件加载（mitmproxy / Charles / Chrome DevTools 通用）。"""
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
    def from_charles_json(cls, path: str) -> "TrafficLog":
        """从 Charles JSON Session (.chlsj) 加载。"""
        with open(path, "r", encoding="utf-8") as f:
            sessions = json.load(f)

        entries = []
        items = sessions if isinstance(sessions, list) else [sessions]
        for item in items:
            url = item.get("scheme", "https") + "://" + item.get("host", "") + item.get("path", "")
            req = item.get("request", {})
            resp = item.get("response", {})

            headers = {}
            if req.get("header") and req["header"].get("headers"):
                headers = {h["name"]: h["value"] for h in req["header"]["headers"]}

            entries.append({
                "url": url,
                "method": item.get("method", "GET"),
                "headers": headers,
                "query_params": {p["name"]: p["value"] for p in item.get("query", [])},
                "post_data": req.get("body", {}).get("text", ""),
                "status": item.get("status", 0),
                "response_body": resp.get("body", {}).get("text", "")[:2000],
                "response_mime": resp.get("header", {}).get("Content-Type", ""),
            })
        return cls(entries)

    @classmethod
    def from_json_list(cls, data: list[dict]) -> "TrafficLog":
        """从 JSON 列表加载。"""
        return cls(data)

    @classmethod
    def auto_load(cls, path: str) -> "TrafficLog":
        """自动检测格式并加载。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # HAR 格式检测
        if isinstance(data, dict) and "log" in data:
            return cls.from_har(path)

        # Charles JSON Session 检测
        if isinstance(data, list) and data and "host" in data[0]:
            return cls.from_charles_json(path)

        # 原始 JSON 列表
        if isinstance(data, list):
            return cls.from_json_list(data)

        raise ValueError(f"无法识别的抓包文件格式: {path}")

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
            if req.get("headers"):
                # 只展示关键 header
                key_headers = {k: v for k, v in req["headers"].items()
                               if k.lower() in ("authorization", "x-sign", "x-token", "cookie", "content-type")}
                if key_headers:
                    lines.append(f"Key Headers: {json.dumps(key_headers, ensure_ascii=False)}")
            lines.append(f"Status: {req['status']}")
            if req.get("response_body"):
                lines.append(f"Response: {req['response_body'][:300]}")
            lines.append("")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  mitmproxy Addon - 实时流量捕获
# ═══════════════════════════════════════════════════════════

MITMPROXY_ADDON_SCRIPT = '''"""
mitmproxy addon: 实时捕获 API 请求并写入 JSON 文件。

使用方式：
    mitmdump -s mitmproxy_addon.py --set output_dir=./traffic_logs

配合 AdaptiveCrawl 使用：
    1. 手机配置代理指向 mitmproxy
    2. 操作 App，addon 自动记录 API 请求
    3. AdaptiveCrawl 读取 traffic_logs/ 下的 JSON 文件进行分析
"""
import json
import time
import os
from mitmproxy import http, ctx

class TrafficCapture:
    def __init__(self):
        self.output_dir = "./traffic_logs"
        self.entries = []
        self.skip_ext = {".js", ".css", ".png", ".jpg", ".gif", ".svg", ".ico", ".woff", ".woff2"}
        self.skip_domains = {"google", "facebook", "analytics", "doubleclick"}

    def load(self, loader):
        loader.add_option("output_dir", str, "./traffic_logs", "Output directory")

    def configure(self, updates):
        self.output_dir = ctx.options.output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def response(self, flow: http.HTTPFlow):
        url = flow.request.pretty_url
        if any(url.lower().endswith(ext) for ext in self.skip_ext):
            return
        if any(d in url.lower() for d in self.skip_domains):
            return

        entry = {
            "url": url,
            "method": flow.request.method,
            "headers": dict(flow.request.headers),
            "query_params": dict(flow.request.query),
            "post_data": flow.request.get_text()[:2000] if flow.request.content else "",
            "status": flow.response.status_code,
            "response_body": flow.response.get_text()[:2000] if flow.response.content else "",
            "response_mime": flow.response.headers.get("content-type", ""),
            "timestamp": time.time(),
        }

        self.entries.append(entry)

        # 每 10 条写一次文件
        if len(self.entries) % 10 == 0:
            self._flush()

    def done(self):
        self._flush()

    def _flush(self):
        if not self.entries:
            return
        ts = int(time.time())
        path = os.path.join(self.output_dir, f"traffic_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)
        ctx.log.info(f"[AdaptiveCrawl] Saved {len(self.entries)} entries to {path}")

addons = [TrafficCapture()]
'''


def export_mitmproxy_addon(output_path: str = "mitmproxy_addon.py"):
    """导出 mitmproxy addon 脚本。"""
    Path(output_path).write_text(MITMPROXY_ADDON_SCRIPT, encoding="utf-8")
    return output_path


# ═══════════════════════════════════════════════════════════
#  Frida 集成 - 自动生成 hook 脚本
# ═══════════════════════════════════════════════════════════

def generate_frida_hook(analysis: dict[str, Any]) -> str:
    """根据 API 分析结果，用 LLM 生成 Frida hook 脚本。"""
    apis = analysis.get("apis", [])
    encrypted_fields = []
    url_patterns = []

    for api in apis:
        encrypted_fields.extend(api.get("encrypted_fields", []))
        url_patterns.append(api.get("url", ""))

    if not encrypted_fields:
        return ""

    llm = get_llm()
    response = llm.invoke([
        SystemMessage(content=FRIDA_HOOK_PROMPT.format(
            encrypted_fields=json.dumps(encrypted_fields),
            algorithm_guess=analysis.get("sign_algorithm_guess", "未知"),
            url_pattern=", ".join(url_patterns[:3]),
        )),
    ])

    code = response.content
    code_match = re.search(r"```(?:javascript|js)?\n(.*?)```", code, re.DOTALL)
    if code_match:
        code = code_match.group(1)
    return code


def parse_frida_output(frida_log: str) -> dict[str, Any]:
    """解析 Frida hook 输出，提取加密函数的输入输出。"""
    results = {
        "hooked_functions": [],
        "captured_calls": [],
    }

    # 简单解析 Frida 输出中的 JSON 行
    for line in frida_log.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                results["captured_calls"].append(data)
            except json.JSONDecodeError:
                continue
        elif "hooked" in line.lower() or "attached" in line.lower():
            results["hooked_functions"].append(line)

    return results


# ═══════════════════════════════════════════════════════════
#  LLM 分析 + 代码生成
# ═══════════════════════════════════════════════════════════

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

    code = response.content
    code_match = re.search(r"```python\n(.*?)```", code, re.DOTALL)
    if code_match:
        code = code_match.group(1)
    return code


# ═══════════════════════════════════════════════════════════
#  App Channel Node
# ═══════════════════════════════════════════════════════════

def app_channel(state: dict) -> dict:
    """App channel node for LangGraph。

    工作流程：
    1. 加载抓包数据（HAR/Charles JSON/原始 JSON）
    2. LLM 分析 API 结构
    3. 如果检测到加密 → 生成 Frida hook 脚本
    4. 根据难度决定：直接重放 / 需要逆向 / 降级到群控
    5. 生成重放代码
    """
    pipeline = PipelineState(**state)

    # 检查抓包数据来源
    traffic_data = state.get("traffic_data")
    traffic_file = state.get("traffic_file")
    traffic_dir = state.get("traffic_dir")  # mitmproxy addon 输出目录

    if traffic_dir:
        # 从 mitmproxy addon 输出目录加载最新的流量文件
        traffic_path = Path(traffic_dir)
        json_files = sorted(traffic_path.glob("traffic_*.json"), reverse=True)
        if json_files:
            all_entries = []
            for f in json_files[:5]:  # 最近 5 个文件
                with open(f, "r", encoding="utf-8") as fh:
                    all_entries.extend(json.load(fh))
            traffic_log = TrafficLog.from_json_list(all_entries)
        else:
            return {"error": "traffic_dir 中没有找到流量文件", "current_step": "error"}
    elif traffic_file:
        traffic_log = TrafficLog.auto_load(traffic_file)
    elif traffic_data:
        traffic_log = TrafficLog.from_json_list(traffic_data)
    else:
        return {
            "error": "App 通道需要提供抓包数据（traffic_data / traffic_file / traffic_dir）",
            "current_step": "error",
        }

    # LLM 分析 API
    analysis = analyze_traffic(traffic_log, pipeline.request.goal)

    if analysis.get("error"):
        return {"error": analysis["error"], "current_step": "error"}

    # 如果检测到加密，生成 Frida hook 脚本
    frida_script = ""
    if analysis.get("encryption_detected"):
        frida_script = generate_frida_hook(analysis)

    # 根据推荐方案决定下一步
    approach = analysis.get("recommended_approach", "direct_replay")

    if approach == "need_device":
        return {
            "error": "API 加密复杂，建议降级到群控通道",
            "current_step": "fallback_to_farm",
        }

    # 生成重放代码
    apis = analysis.get("apis", [])
    replay_code = generate_replay_code(apis[0], pipeline.request.goal) if apis else ""

    # 将分析结果作为 raw_content 传给 Parser
    raw_content = json.dumps({
        "api_analysis": analysis,
        "replay_code": replay_code,
        "frida_script": frida_script,
        "api_responses": [e.get("response_body", "") for e in traffic_log.filter_api_requests()[:5]],
    }, ensure_ascii=False)

    return {
        "raw_content": raw_content,
        "current_step": "fetched",
    }
