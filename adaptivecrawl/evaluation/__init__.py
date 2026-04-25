"""Evaluation module - 采集结果评估"""

from __future__ import annotations
from ..models import PipelineState


def evaluator(state: dict) -> dict:
    """评估采集结果，决定是否需要重试。"""
    pipeline = PipelineState(**state)

    if not pipeline.results:
        return {"current_step": "error", "error": "无采集结果"}

    last_result = pipeline.results[-1]

    if last_result.success and last_result.metrics.get("confidence", 0) >= 0.6:
        return {"current_step": "done"}

    # 结果不理想，判断是否重试
    if pipeline.retry_count < pipeline.max_retries:
        return {
            "retry_count": pipeline.retry_count + 1,
            "current_step": "retry",
        }

    return {"current_step": "done"}  # 超过重试次数，返回当前结果
