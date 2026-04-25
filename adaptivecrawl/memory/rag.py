"""RAG System - 向量检索增强的任务规划"""

from __future__ import annotations
import json
import time
import hashlib
from pathlib import Path
from typing import Any


class RAGStore:
    """RAG 存储：支持 Qdrant 向量检索，降级为本地 JSON + bigram 匹配。"""

    def __init__(self, storage_dir: str = ".memory/rag", qdrant_url: str | None = None):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._qdrant = None
        self._collection = "crawl_cases"

        if qdrant_url:
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams
                self._qdrant = QdrantClient(url=qdrant_url)
                # 确保 collection 存在
                collections = [c.name for c in self._qdrant.get_collections().collections]
                if self._collection not in collections:
                    self._qdrant.create_collection(
                        collection_name=self._collection,
                        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                    )
            except Exception:
                self._qdrant = None

    def _get_embedder(self):
        """获取 embedding 模型（懒加载）。"""
        if not hasattr(self, "_embedder"):
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                self._embedder = None
        return self._embedder

    def _embed(self, text: str) -> list[float] | None:
        embedder = self._get_embedder()
        if embedder:
            return embedder.encode(text).tolist()
        return None

    def _doc_id(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    # ── 存储 ──────────────────────────────────────────────

    def add_case(self, domain: str, goal: str, strategy: dict[str, Any], result_summary: str = ""):
        """添加成功案例到 RAG 存储。"""
        doc_text = f"域名:{domain} 目标:{goal} 结果:{result_summary}"
        doc = {
            "domain": domain,
            "goal": goal,
            "strategy": strategy,
            "result_summary": result_summary,
            "timestamp": time.time(),
            "text": doc_text,
        }

        if self._qdrant:
            vec = self._embed(doc_text)
            if vec:
                from qdrant_client.models import PointStruct
                self._qdrant.upsert(
                    collection_name=self._collection,
                    points=[PointStruct(
                        id=self._doc_id(doc_text),
                        vector=vec,
                        payload=doc,
                    )],
                )
                return

        # 降级：JSON 文件存储
        self._save_local(doc)

    def add_site_knowledge(self, domain: str, knowledge: dict[str, Any]):
        """添加站点知识（反爬特征、页面结构模式等）。"""
        doc_text = f"站点知识:{domain} {json.dumps(knowledge, ensure_ascii=False)}"
        doc = {
            "type": "site_knowledge",
            "domain": domain,
            "knowledge": knowledge,
            "timestamp": time.time(),
            "text": doc_text,
        }

        if self._qdrant:
            vec = self._embed(doc_text)
            if vec:
                from qdrant_client.models import PointStruct
                self._qdrant.upsert(
                    collection_name=self._collection,
                    points=[PointStruct(
                        id=self._doc_id(doc_text),
                        vector=vec,
                        payload=doc,
                    )],
                )
                return

        self._save_local(doc)

    # ── 检索 ──────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """语义检索相似案例。"""
        if self._qdrant:
            vec = self._embed(query)
            if vec:
                results = self._qdrant.search(
                    collection_name=self._collection,
                    query_vector=vec,
                    limit=limit,
                )
                return [
                    {**r.payload, "score": r.score}
                    for r in results
                ]

        # 降级：本地 bigram 匹配
        return self._search_local(query, limit)

    def search_by_domain(self, domain: str, limit: int = 5) -> list[dict]:
        """按域名检索相关知识。"""
        if self._qdrant:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            vec = self._embed(f"站点 {domain}")
            if vec:
                results = self._qdrant.search(
                    collection_name=self._collection,
                    query_vector=vec,
                    query_filter=Filter(must=[
                        FieldCondition(key="domain", match=MatchValue(value=domain))
                    ]),
                    limit=limit,
                )
                return [{**r.payload, "score": r.score} for r in results]

        return [d for d in self._load_local() if d.get("domain") == domain][:limit]

    # ── 本地存储（降级方案）────────────────────────────────

    def _local_file(self) -> Path:
        return self.storage_dir / "cases.jsonl"

    def _save_local(self, doc: dict):
        path = self._local_file()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    def _load_local(self) -> list[dict]:
        path = self._local_file()
        if not path.exists():
            return []
        docs = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                docs.append(json.loads(line))
        return docs

    def _search_local(self, query: str, limit: int) -> list[dict]:
        """本地 bigram 匹配检索。"""
        docs = self._load_local()
        query_lower = query.lower()

        def _bigrams(s: str) -> set[str]:
            return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

        query_grams = _bigrams(query_lower)
        scored = []

        for doc in docs:
            text = doc.get("text", "").lower()
            text_grams = _bigrams(text)
            overlap = len(query_grams & text_grams)
            union = len(query_grams | text_grams)
            score = overlap / union if union > 0 else 0

            if query_lower in text or text in query_lower:
                score += 0.5

            if score > 0.05:
                scored.append({**doc, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
