"""测试：App Channel（多格式 + mitmproxy addon + Frida）+ RAG System"""

import json
import tempfile
from pathlib import Path
from adaptivecrawl.channels.app import TrafficLog, export_mitmproxy_addon, parse_frida_output
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
    api_reqs = log.filter_api_requests()
    assert len(api_reqs) == 2
    print(f"✅ 流量过滤：{len(api_reqs)} 个 API 请求")

    summary = log.summarize()
    assert "X-Sign" in summary  # 关键 header 应该被展示
    print(f"✅ 流量摘要：{len(summary)} chars（含关键 headers）")


def test_traffic_log_har():
    """测试 HAR 文件解析。"""
    har = {
        "log": {
            "entries": [{
                "request": {
                    "url": "https://api.test.com/data",
                    "method": "GET",
                    "headers": [{"name": "User-Agent", "value": "TestApp/1.0"}],
                    "queryString": [{"name": "id", "value": "123"}],
                },
                "response": {
                    "status": 200,
                    "content": {"mimeType": "application/json", "text": '{"result": "ok"}'},
                },
            }]
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False) as f:
        json.dump(har, f)
        f.flush()
        log = TrafficLog.from_har(f.name)

    assert len(log.entries) == 1
    print("✅ HAR 解析：通过")


def test_charles_json_session():
    """测试 Charles JSON Session 格式解析。"""
    charles_data = [
        {
            "scheme": "https",
            "host": "api.shop.com",
            "path": "/v2/items",
            "method": "GET",
            "query": [{"name": "category", "value": "phone"}],
            "status": 200,
            "request": {
                "header": {
                    "headers": [
                        {"name": "Authorization", "value": "Bearer xxx"},
                        {"name": "X-App-Version", "value": "3.2.1"},
                    ]
                },
                "body": {"text": ""},
            },
            "response": {
                "header": {"Content-Type": "application/json"},
                "body": {"text": '{"items": [{"name": "iPhone"}]}'},
            },
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".chlsj", delete=False) as f:
        json.dump(charles_data, f)
        f.flush()
        log = TrafficLog.from_charles_json(f.name)

    assert len(log.entries) == 1
    assert "api.shop.com" in log.entries[0]["url"]
    assert log.entries[0]["headers"].get("Authorization") == "Bearer xxx"
    print("✅ Charles JSON Session 解析：通过")


def test_auto_load():
    """测试自动格式检测。"""
    # HAR 格式
    har = {"log": {"entries": []}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False) as f:
        json.dump(har, f)
        f.flush()
        log = TrafficLog.auto_load(f.name)
    assert len(log.entries) == 0
    print("✅ 自动检测 HAR：通过")

    # Charles 格式
    charles = [{"host": "test.com", "path": "/", "scheme": "https", "method": "GET", "status": 200,
                "query": [], "request": {"header": {"headers": []}, "body": {"text": ""}},
                "response": {"header": {}, "body": {"text": ""}}}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(charles, f)
        f.flush()
        log = TrafficLog.auto_load(f.name)
    assert len(log.entries) == 1
    print("✅ 自动检测 Charles JSON：通过")


def test_mitmproxy_addon_export():
    """测试 mitmproxy addon 脚本导出。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_mitmproxy_addon(f"{tmpdir}/mitmproxy_addon.py")
        content = Path(path).read_text()
        assert "class TrafficCapture" in content
        assert "def response" in content
        assert "addons" in content
        print("✅ mitmproxy addon 导出：通过")


def test_mitmproxy_traffic_dir():
    """测试从 mitmproxy addon 输出目录加载流量。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 模拟 addon 输出
        entries = [{"url": "https://api.test.com/data", "method": "GET",
                     "headers": {}, "query_params": {}, "post_data": "",
                     "status": 200, "response_body": '{"ok": true}',
                     "response_mime": "application/json"}]
        traffic_file = Path(tmpdir) / "traffic_1234567890.json"
        traffic_file.write_text(json.dumps(entries))

        # 加载
        json_files = sorted(Path(tmpdir).glob("traffic_*.json"), reverse=True)
        assert len(json_files) == 1
        all_entries = json.loads(json_files[0].read_text())
        log = TrafficLog.from_json_list(all_entries)
        assert len(log.entries) == 1
        print("✅ mitmproxy traffic_dir 加载：通过")


def test_frida_output_parsing():
    """测试 Frida 输出解析。"""
    frida_log = """
[*] Attached to com.example.app
[*] Hooked javax.crypto.Cipher.doFinal
{"function": "doFinal", "input": "plaintext123", "output": "encrypted_abc"}
{"function": "sign", "input": "data_to_sign", "output": "signature_xyz"}
    """
    result = parse_frida_output(frida_log)
    assert len(result["hooked_functions"]) >= 1
    assert len(result["captured_calls"]) == 2
    assert result["captured_calls"][0]["function"] == "doFinal"
    print(f"✅ Frida 输出解析：{len(result['captured_calls'])} 个捕获")


def test_rag_store_local():
    """测试 RAG 本地存储和检索。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rag = RAGStore(storage_dir=tmpdir)
        rag.add_case("taobao.com", "抓取商品价格", {"channel": "web"})
        rag.add_case("jd.com", "提取用户评论", {"channel": "app"})

        results = rag.search("商品价格采集")
        assert len(results) >= 1
        print(f"✅ RAG 检索：找到 {len(results)} 条")


def test_pipeline_builds():
    """Pipeline 构建验证。"""
    pipeline = build_pipeline()
    assert pipeline is not None
    print("✅ Pipeline 构建成功")


if __name__ == "__main__":
    test_traffic_log_parsing()
    test_traffic_log_har()
    test_charles_json_session()
    test_auto_load()
    test_mitmproxy_addon_export()
    test_mitmproxy_traffic_dir()
    test_frida_output_parsing()
    test_rag_store_local()
    test_pipeline_builds()
    print("\n🎉 Week 3-4 测试全部通过！")
