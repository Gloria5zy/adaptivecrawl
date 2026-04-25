"""Memory System - 短期记忆(Redis) + 长期记忆(JSON文件存储站点特征)"""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any


class MemorySystem:
    """双层记忆系统：短期(dict/Redis) + 长期(JSON文件)。"""

    def __init__(self, storage_dir: str = ".memory", redis_url: str | None = None):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # 短期记忆（当前任务上下文）
        self._short_term: dict[str, Any] = {}

        # Redis 连接（可选，降级为内存 dict）
        self._redis = None
        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

    # ── 短期记忆 ──────────────────────────────────────────

    def set_short(self, key: str, value: Any, ttl: int = 3600):
        """设置短期记忆（默认 1 小时过期）。"""
        if self._redis:
            self._redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        else:
            self._short_term[key] = {
                "value": value,
                "expires": time.time() + ttl,
            }

    def get_short(self, key: str) -> Any | None:
        """获取短期记忆。"""
        if self._redis:
            val = self._redis.get(key)
            return json.loads(val) if val else None
        else:
            entry = self._short_term.get(key)
            if entry and entry["expires"] > time.time():
                return entry["value"]
            return None

    # ── 长期记忆：站点特征库 ──────────────────────────────

    def _site_file(self, domain: str) -> Path:
        return self.storage_dir / "sites" / f"{domain}.json"

    def get_site_profile(self, domain: str) -> dict[str, Any]:
        """获取站点特征。"""
        path = self._site_file(domain)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def update_site_profile(self, domain: str, data: dict[str, Any]):
        """更新站点特征。"""
        path = self._site_file(domain)
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = self.get_site_profile(domain)
        existing.update(data)
        existing["last_updated"] = time.time()
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 长期记忆：通道成功率统计 ──────────────────────────

    def _stats_file(self) -> Path:
        return self.storage_dir / "channel_stats.json"

    def _load_stats(self) -> dict:
        path = self._stats_file()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _save_stats(self, stats: dict):
        path = self._stats_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_channel_result(self, domain: str, channel: str, success: bool):
        """记录通道采集结果。"""
        stats = self._load_stats()
        key = f"{domain}:{channel}"

        if key not in stats:
            stats[key] = {"success": 0, "failure": 0, "last_used": 0}

        if success:
            stats[key]["success"] += 1
        else:
            stats[key]["failure"] += 1
        stats[key]["last_used"] = time.time()

        self._save_stats(stats)

    def get_channel_success_rate(self, domain: str, channel: str) -> float:
        """获取某站点某通道的成功率。"""
        stats = self._load_stats()
        key = f"{domain}:{channel}"
        entry = stats.get(key, {})
        total = entry.get("success", 0) + entry.get("failure", 0)
        if total == 0:
            return 0.0
        return entry["success"] / total

    def recommend_channel(self, domain: str) -> str | None:
        """基于历史数据推荐最优通道。"""
        stats = self._load_stats()
        best_channel = None
        best_rate = -1.0

        for key, entry in stats.items():
            if key.startswith(f"{domain}:"):
                channel = key.split(":", 1)[1]
                total = entry.get("success", 0) + entry.get("failure", 0)
                if total >= 3:  # 至少 3 次记录才有参考价值
                    rate = entry["success"] / total
                    if rate > best_rate:
                        best_rate = rate
                        best_channel = channel

        return best_channel

    # ── 长期记忆：成功案例库 ──────────────────────────────

    def _cases_file(self) -> Path:
        return self.storage_dir / "success_cases.json"

    def save_success_case(self, domain: str, goal: str, strategy: dict[str, Any]):
        """保存成功的采集案例。"""
        path = self._cases_file()
        path.parent.mkdir(parents=True, exist_ok=True)

        cases = []
        if path.exists():
            cases = json.loads(path.read_text(encoding="utf-8"))

        cases.append({
            "domain": domain,
            "goal": goal,
            "strategy": strategy,
            "timestamp": time.time(),
        })

        # 保留最近 500 条
        cases = cases[-500:]
        path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")

    def search_similar_cases(self, goal: str, limit: int = 3) -> list[dict]:
        """字符级 n-gram + 子串匹配搜索相似案例（中文友好，后续升级为向量检索）。"""
        path = self._cases_file()
        if not path.exists():
            return []

        cases = json.loads(path.read_text(encoding="utf-8"))
        goal_lower = goal.lower()

        def _bigrams(s: str) -> set[str]:
            return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

        goal_grams = _bigrams(goal_lower)

        scored = []
        for case in cases:
            case_goal = case["goal"].lower()
            score = 0

            # 互相子串匹配
            if goal_lower in case_goal or case_goal in goal_lower:
                score += 10

            # bigram 重叠度
            case_grams = _bigrams(case_goal)
            overlap = len(goal_grams & case_grams)
            union = len(goal_grams | case_grams)
            if union > 0:
                score += overlap / union * 5

            if score > 0.5:
                scored.append((score, case))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]
