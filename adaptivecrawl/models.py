"""Pydantic models for the crawl pipeline."""

from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    WEB = "web"
    APP = "app"
    FARM = "farm"


class CrawlRequest(BaseModel):
    """用户的采集需求"""
    url: str | None = None
    goal: str = Field(..., description="自然语言描述的采集目标")
    app_name: str | None = None
    channel_hint: ChannelType | None = None


class CrawlPlan(BaseModel):
    """Planning Agent 生成的采集计划"""
    channel: ChannelType
    strategy: str = Field(..., description="采集策略描述")
    steps: list[str] = Field(default_factory=list, description="具体执行步骤")
    fallback_channel: ChannelType | None = None


class ParseRule(BaseModel):
    """LLM 生成的解析规则"""
    fields: dict[str, str] = Field(default_factory=dict, description="字段名 → 提取描述")
    selectors: dict[str, str] = Field(default_factory=dict, description="字段名 → CSS/XPath")
    confidence: float = 0.0


class CrawlResult(BaseModel):
    """单次采集结果"""
    url: str
    channel: ChannelType
    raw_html: str = ""
    extracted_data: list[dict[str, Any]] = Field(default_factory=list)
    parse_rule: ParseRule | None = None
    success: bool = False
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class PipelineState(BaseModel):
    """LangGraph 状态机的全局状态"""
    request: CrawlRequest
    plan: CrawlPlan | None = None
    raw_content: str = ""
    screenshot_b64: str | None = None
    parse_rule: ParseRule | None = None
    results: list[CrawlResult] = Field(default_factory=list)
    current_step: str = "init"
    retry_count: int = 0
    max_retries: int = 3
    error: str | None = None
