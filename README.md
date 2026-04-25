# AdaptiveCrawl

自适应多通道智能采集系统 — 基于 Multi-Agent 架构，覆盖 Web/App/群控三大采集通道。

## 核心特性

- **Planning Agent**: 自然语言需求 → 自动规划采集策略
- **自适应解析**: LLM 智能识别页面结构，零配置数据提取
- **多通道调度**: Web / App协议 / 群控真机，自动选择最优路径
- **Memory 驱动**: 站点特征库 + 通道成功率统计，持续优化决策
- **评估闭环**: 实时准确率监控 + 反馈优化

## 架构

```
用户自然语言需求
       ↓
  Planning Agent (需求理解 + 通道选择)
       ↓
  ┌────┼────┐
  Web  App  Farm
  ↓    ↓    ↓
  Adaptive Parser Agent
       ↓
  结构化数据输出
```

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 设置 API Key
export OPENAI_API_KEY="your-key"

# 运行 Web 采集示例
python -m adaptivecrawl.cli crawl "https://example.com" --goal "提取所有文章标题和链接"
```

## 技术栈

- LangGraph (Agent 编排)
- Playwright (Web 自动化)
- mitmproxy (App 抓包)
- Appium / uiautomator2 (群控)
- GPT-4o / Claude (多模态解析)
- Redis (短期记忆)
- Qdrant (向量检索)

## License

MIT
