"""CLI entry point for AdaptiveCrawl."""

from __future__ import annotations
import argparse
import json
import sys

from .pipeline import run_crawl


def main():
    parser = argparse.ArgumentParser(description="AdaptiveCrawl - 自适应多通道智能采集系统")
    subparsers = parser.add_subparsers(dest="command")

    # crawl 子命令
    crawl_parser = subparsers.add_parser("crawl", help="执行采集任务")
    crawl_parser.add_argument("url", nargs="?", help="目标 URL")
    crawl_parser.add_argument("--goal", "-g", required=True, help="采集目标（自然语言描述）")
    crawl_parser.add_argument("--app", help="目标 App 名称")
    crawl_parser.add_argument("--output", "-o", help="输出文件路径")

    args = parser.parse_args()

    if args.command == "crawl":
        print(f"🚀 开始采集...")
        print(f"   目标: {args.goal}")
        if args.url:
            print(f"   URL: {args.url}")

        result = run_crawl(url=args.url, goal=args.goal, app_name=args.app)

        # 输出结果
        results = result.get("results", [])
        if results:
            last = results[-1]
            if hasattr(last, "model_dump"):
                output = last.model_dump()
            else:
                output = last

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                print(f"\n✅ 结果已保存到 {args.output}")
            else:
                print(f"\n📊 采集结果:")
                print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(f"\n❌ 采集失败: {result.get('error', '未知错误')}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
