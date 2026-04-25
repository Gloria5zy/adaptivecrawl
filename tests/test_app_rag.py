"""测试：App Channel + RAG System"""

import json
import tempfile
from adaptivecrawl.channels.app import TrafficLog
from adaptivecrawl.memory.rag import RAGStore
from adaptivecrawl.pipeline import build_pipeline


def test_traffic_log_parsing():
    """测试抓包日志解析。"""
    entries = [
        {
            "url": "https://api.example.com/v1/products?page=1",
            "method": "GET",
            "headers": {"Authorization": "Bearer token123"},
            "query_params": {"page": "1"},
            "post_data": "",
            "status": 200,
            "response_body": '{"data": [{"id": 1, "name": "商品A"}]}',
            "response_mime": "application/json",
        },
        {
            "url": "https://cdn.example.com/style.css",
            "method": "GET",
            "headers": {},
            "query_params": {},
            "post_data": "",
            "status": 200,
            "response_body": "body { color: red }",
            "response_mime": "text/css",
        },
        {
            "url": "https://api.example.com/v1/reviews",
            "method": "POST",
            "headers": {"X-Sign": "abc123"},
            "query_params": {},
            "post_data": '{"product_id": 1}',
            "status": 200,
            "response_body": '{"reviews": [{"text": "好评"}]}',
            "response_mime": "application/json",
        },
    ]

    log = TrafficLog.from_json_list(entries)

    # 过滤 API 请求（应排除 CSS）
    api_reqs = log.filter_api_requests()
    assert len(api_reqs) == 2
    assert all("css" not in r["url"] for r in api_reqs)
    print(f"✅ 流量过滤：{len(api_reqs)} 个 API 请求（排除了静态资源）")

    # 摘要生成
    summary = log.summarize()
    assert "api.example.com" in summary
    assert "products" in summary
    print(f"✅ 流量摘要：{len(summary)} chars")


def test_traffic_log_har():
    """测试 HAR 文件解析。"""
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://api.test.com/data",
                        "method": "GET",
                        "headers": [{"name": "User-Agent", "value": "TestApp/1.0"}],
                        "queryString": [{"name": "id", "value": "123"}],
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"result": "ok"}',
                        },
                    },
                }
            ]
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False) as f:
        json.dump(har, f)
        f.flush()
        log = TrafficLog.from_har(f.name)

    assert len(log.entries) == 1
    assert log.entries[0]["url"] == "https://api.test.com/data"
    print("✅ HAR 解析：通过")


def test_rag_store_local():
    """测试 RAG 本地存储和检索。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rag = RAGStore(storage_dir=tmpdir)

        # 添加案例
        rag.add_case("taobao.com", "抓取商品价格", {"channel": "web", "success_rate": 0.9})
        rag.add_case("jd.com", "提取用户评论", {"channel": "app", "success_rate": 0.85})
        rag.add_case("douyin.com", "采集视频信息", {"channel": "farm", "success_rate": 0.7})

        # 语义检索
        results = rag.search("商品价格采集")
        assert len(results) >= 1
        assert any("taobao" in r.get("domain", "") for r in results)
        print(f"✅ RAG 检索「商品价格采集」：找到 {len(results)} 条")

        results = rag.search("用户评论")
        assert len(results) >= 1
        print(f"✅ RAG 检索「用户评论」：找到 {len(results)} 条")

        # 添加站点知识
        rag.add_site_knowledge("taobao.com", {
            "anti_crawl": ["rate_limit", "captcha"],
            "best_channel": "app",
        })

        results = rag.search_by_domain("taobao.com")
        assert len(results) >= 1
        print(f"✅ RAG 域名检索 taobao.com：找到 {len(results)} 条")


def test_pipeline_with_app_channel():
    """测试 Pipeline 包含 App 通道。"""
    pipeline = build_pipeline()
    assert pipeline is not None
    print("✅ Pipeline 构建成功（含 App 通道）")


if __name__ == "__main__":
    test_traffic_log_parsing()
    test_traffic_log_har()
    test_rag_store_local()
    test_pipeline_with_app_channel()
    print("\n🎉 Week 3-4 测试全部通过！")
