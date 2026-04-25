"""测试：Pipeline 构建 + 内容类型检测 + Memory 系统"""

import json
import tempfile
from adaptivecrawl.pipeline import build_pipeline
from adaptivecrawl.agents.multimodal import detect_content_types
from adaptivecrawl.memory import MemorySystem
from adaptivecrawl.models import CrawlRequest, PipelineState, ChannelType


def test_pipeline_builds():
    """Pipeline 能正常编译。"""
    pipeline = build_pipeline()
    assert pipeline is not None
    print("✅ Pipeline 构建成功")


def test_content_type_detection():
    """多模态内容类型检测。"""
    html = """
    <html><body>
        <table><tr><td>数据</td></tr></table>
        <a href="report.pdf">下载报告</a>
        <img src="chart.png">
        <iframe src="https://youtube.com/watch?v=abc"></iframe>
    </body></html>
    """
    result = detect_content_types("https://example.com", html)
    assert "html" in result["content_types"]
    assert "table" in result["content_types"]
    assert "pdf" in result["content_types"]
    assert "image" in result["content_types"]
    assert "video" in result["content_types"]
    assert result["has_pdf_links"]
    assert len(result["pdf_urls"]) == 1
    print("✅ 内容类型检测：全部通过")


def test_content_type_plain_html():
    """纯 HTML 页面，无多模态内容。"""
    html = "<html><body><p>Hello World</p></body></html>"
    result = detect_content_types("https://example.com", html)
    assert result["content_types"] == ["html"]
    assert not result["has_tables"]
    assert not result["has_pdf_links"]
    print("✅ 纯 HTML 检测：通过")


def test_memory_system():
    """Memory 系统基本功能。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = MemorySystem(storage_dir=tmpdir)

        # 短期记忆
        mem.set_short("test_key", {"data": "hello"}, ttl=60)
        assert mem.get_short("test_key") == {"data": "hello"}
        assert mem.get_short("nonexistent") is None
        print("✅ 短期记忆：通过")

        # 通道成功率
        mem.record_channel_result("example.com", "web", True)
        mem.record_channel_result("example.com", "web", True)
        mem.record_channel_result("example.com", "web", False)
        rate = mem.get_channel_success_rate("example.com", "web")
        assert abs(rate - 0.667) < 0.01
        print(f"✅ 通道成功率：{rate:.3f}")

        # 推荐通道（不足 3 次不推荐）
        assert mem.recommend_channel("example.com") == "web"
        assert mem.recommend_channel("unknown.com") is None
        print("✅ 通道推荐：通过")

        # 站点特征
        mem.update_site_profile("example.com", {"anti_crawl": "cloudflare"})
        profile = mem.get_site_profile("example.com")
        assert profile["anti_crawl"] == "cloudflare"
        assert "last_updated" in profile
        print("✅ 站点特征：通过")

        # 成功案例
        mem.save_success_case("example.com", "提取商品价格", {"channel": "web"})
        mem.save_success_case("shop.com", "抓取用户评论", {"channel": "app"})
        cases = mem.search_similar_cases("提取价格")
        assert len(cases) >= 1
        print(f"✅ 案例检索：找到 {len(cases)} 条")


def test_models():
    """数据模型验证。"""
    req = CrawlRequest(url="https://example.com", goal="提取文章标题")
    assert req.url == "https://example.com"

    state = PipelineState(request=req)
    assert state.current_step == "init"
    assert state.retry_count == 0
    print("✅ 数据模型：通过")


if __name__ == "__main__":
    test_pipeline_builds()
    test_content_type_detection()
    test_content_type_plain_html()
    test_memory_system()
    test_models()
    print("\n🎉 所有测试通过！")
