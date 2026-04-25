"""Planning Agent - 需求理解 + 采集策略规划"""

from __future__ import annotations
from langchain_core.messages import SystemMessage, HumanMessage

from ..models import PipelineState, CrawlPlan, ChannelType
from ..utils import get_llm

PLANNING_PROMPT = """你是一个智能采集系统的规划 Agent。根据用户的采集需求，生成采集计划。

你需要决定：
1. 使用哪个采集通道（web/app/farm）
2. 具体的采集策略
3. 执行步骤
4. 备选通道（如果首选失败）

决策规则：
- 如果提供了 URL 且是网页，优先使用 web 通道
- 如果提供了 app_name，优先使用 app 通道（协议分析）
- 如果目标需要模拟真实用户操作（如登录、滑动），考虑 farm 通道
- 如果 app 协议分析难度高（加密复杂），降级到 farm 通道

请以 JSON 格式返回：
{{
    "channel": "web|app|farm",
    "strategy": "策略描述",
    "steps": ["步骤1", "步骤2", ...],
    "fallback_channel": "web|app|farm|null"
}}
"""


def planning_agent(state: dict) -> dict:
    """Planning Agent node for LangGraph."""
    pipeline = PipelineState(**state)
    llm = get_llm()

    request = pipeline.request
    user_msg = f"采集需求：{request.goal}"
    if request.url:
        user_msg += f"\n目标 URL：{request.url}"
    if request.app_name:
        user_msg += f"\n目标 App：{request.app_name}"
    if request.channel_hint:
        user_msg += f"\n用户建议通道：{request.channel_hint.value}"

    response = llm.invoke([
        SystemMessage(content=PLANNING_PROMPT),
        HumanMessage(content=user_msg),
    ])

    import json
    try:
        plan_data = json.loads(response.content)
        plan = CrawlPlan(
            channel=ChannelType(plan_data["channel"]),
            strategy=plan_data["strategy"],
            steps=plan_data.get("steps", []),
            fallback_channel=ChannelType(plan_data["fallback_channel"]) if plan_data.get("fallback_channel") else None,
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        # 默认走 web 通道
        plan = CrawlPlan(
            channel=ChannelType.WEB,
            strategy="默认 Web 采集策略",
            steps=["访问页面", "解析内容", "提取数据"],
            fallback_channel=ChannelType.FARM,
        )

    return {"plan": plan, "current_step": "planned"}
