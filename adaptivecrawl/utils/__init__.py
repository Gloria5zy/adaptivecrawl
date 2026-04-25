"""LLM provider configuration and helpers."""

from __future__ import annotations
import os
from langchain_openai import ChatOpenAI


def get_llm(model: str = "gpt-4o", temperature: float = 0.0) -> ChatOpenAI:
    """Get a configured LLM instance."""
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),  # 支持国内代理
    )
