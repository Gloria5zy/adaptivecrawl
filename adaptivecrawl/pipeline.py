"""LangGraph Pipeline - 核心编排引擎"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from .models import ChannelType
from .agents.planning import planning_agent
from .agents.parser import parser_agent
from .channels.web import web_channel
from .channels.app import app_channel
from .evaluation import evaluator


def route_channel(state: dict) -> str:
    """根据 plan 选择执行通道。"""
    plan = state.get("plan")
    if plan is None:
        return "web_channel"

    channel = plan.channel if hasattr(plan, "channel") else plan.get("channel", "web")
    if isinstance(channel, ChannelType):
        channel = channel.value

    channel_map = {
        "web": "web_channel",
        "app": "app_channel",
        "farm": "farm_channel",
    }
    return channel_map.get(channel, "web_channel")


def route_eval(state: dict) -> str:
    """根据评估结果决定下一步。"""
    step = state.get("current_step", "")
    if step == "retry":
        return "planning"
    return END


def route_app_result(state: dict) -> str:
    """App 通道结果路由：正常 → parser，降级 → farm。"""
    step = state.get("current_step", "")
    if step == "fallback_to_farm":
        return "farm_channel"
    return "parser"


def build_pipeline() -> StateGraph:
    """构建 LangGraph 采集流水线。"""

    workflow = StateGraph(dict)

    # 添加节点
    workflow.add_node("planning", planning_agent)
    workflow.add_node("web_channel", web_channel)
    workflow.add_node("app_channel", app_channel)
    # TODO: Week 5-6 实现
    workflow.add_node("farm_channel", lambda s: {**s, "error": "群控通道开发中", "current_step": "error"})
    workflow.add_node("parser", parser_agent)
    workflow.add_node("evaluator", evaluator)

    # 定义边
    workflow.set_entry_point("planning")
    workflow.add_conditional_edges("planning", route_channel)
    workflow.add_edge("web_channel", "parser")
    workflow.add_conditional_edges("app_channel", route_app_result)
    workflow.add_edge("farm_channel", "parser")
    workflow.add_edge("parser", "evaluator")
    workflow.add_conditional_edges("evaluator", route_eval)

    return workflow.compile()


def run_crawl(
    url: str | None = None,
    goal: str = "",
    app_name: str | None = None,
    traffic_data: list | None = None,
    traffic_file: str | None = None,
) -> dict:
    """运行采集流水线。"""
    from .models import CrawlRequest

    request = CrawlRequest(url=url, goal=goal, app_name=app_name)
    initial_state = {
        "request": request,
        "plan": None,
        "raw_content": "",
        "screenshot_b64": None,
        "parse_rule": None,
        "results": [],
        "current_step": "init",
        "retry_count": 0,
        "max_retries": 3,
        "error": None,
        # App 通道专用
        "traffic_data": traffic_data,
        "traffic_file": traffic_file,
    }

    pipeline = build_pipeline()
    final_state = pipeline.invoke(initial_state)
    return final_state
