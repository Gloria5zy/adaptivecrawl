"""Evaluation module - 采集结果评估 + Memory 反馈"""

from __future__ import annotations
from urllib.parse import urlparse
from ..models import PipelineState
from ..memory import MemorySystem


# 全局 Memory 实例
_memory = MemorySystem(storage_dir=".memory")


def get_memory() -> MemorySystem:
    return _memory


def evaluator(state: dict) -> dict:
    """评估采集结果，记录到 Memory，决定是否重试。"""
    pipeline = PipelineState(**state)
    memory = get_memory()

    if not pipeline.results:
        return {"current_step": "error", "error": "无采集结果"}

    last_result = pipeline.results[-1]

    # 提取域名
    domain = ""
    if pipeline.request.url:
        domain = urlparse(pipeline.request.url).netloc

    # 记录通道结果到 Memory
    if domain and pipeline.plan:
        channel = pipeline.plan.channel.value if hasattr(pipeline.plan.channel, "value") else str(pipeline.plan.channel)
        memory.record_channel_result(domain, channel, last_result.success)

        # 成功时保存案例
        if last_result.success and last_result.metrics.get("confidence", 0) >= 0.6:
            memory.save_success_case(
                domain=domain,
                goal=pipeline.request.goal,
                strategy={
                    "channel": channel,
                    "confidence": last_result.metrics.get("confidence", 0),
                    "record_count": last_result.metrics.get("record_count", 0),
                    "content_types": last_result.metrics.get("content_types", []),
                },
            )

        # 更新站点特征
        memory.update_site_profile(domain, {
            "last_channel": channel,
            "last_success": last_result.success,
            "content_types": last_result.metrics.get("content_types", []),
        })

    # 评估逻辑
    if last_result.success and last_result.metrics.get("confidence", 0) >= 0.6:
        return {"current_step": "done"}

    if pipeline.retry_count < pipeline.max_retries:
        return {
            "retry_count": pipeline.retry_count + 1,
            "current_step": "retry",
        }

    return {"current_step": "done"}
