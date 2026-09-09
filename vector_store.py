"""Milvus 向量层：建 collection、写入、相似检索（实体链接 + RAG 兜底）。

三张 collection：
  - symptom_emb     症状实体链接（口语症状 -> 规范 Symptom）
  - disease_emb     疾病语义向量（用户描述 -> 候选疾病兜底）
  - knowledge_chunk 医学知识片段（RAG）
"""
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

import config

COLLECTIONS = {
    "symptom_emb": "症状实体链接向量",
    "disease_emb": "疾病语义向量",
    "knowledge_chunk": "医学知识片段 RAG",
}

_INDEX_PARAMS = {
    "metric_type": "COSINE",
    "index_type": "IVF_FLAT",
    "params": {"nlist": 128},
}
_SEARCH_PARAMS = {"metric_type": "COSINE", "params": {"nprobe": 16}}


class VectorStore:
    """Milvus 连接与操作封装。"""

    def __init__(self, host=None, port=None):
        connections.connect(
            alias="default",
            host=host or config.MILVUS_HOST,
            port=port or config.MILVUS_PORT,
        )

    def ensure_collections(self, dim: int = config.EMBED_DIM):
        """不存在则创建 collection 并建索引、加载。"""
        for name, desc in COLLECTIONS.items():
            if utility.has_collection(name):
                Collection(name).load()
                continue
            fields = [
                FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema("neo4j_id", DataType.VARCHAR, max_length=64),
                FieldSchema("text", DataType.VARCHAR, max_length=512),
                FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dim),
            ]
            col = Collection(name, CollectionSchema(fields, desc))
            col.create_index("embedding", _INDEX_PARAMS)
            col.load()

    def insert(self, collection: str, rows: list[dict]):
        """rows: [{neo4j_id, text, embedding}]，embedding 为 list[float]。"""
        if not rows:
            return
        col = Collection(collection)
        col.insert(rows)
        col.flush()

    def search(self, collection: str, embedding: list[float],
               top_k: int = 5, threshold: float = config.LINK_THRESHOLD) -> list[dict]:
        """相似检索，返回 {neo4j_id, text, score}（仅保留 >= threshold 的命中）。"""
        col = Collection(collection)
        col.load()
        res = col.search(
            data=[embedding],
            anns_field="embedding",
            param=_SEARCH_PARAMS,
            limit=top_k,
            output_fields=["neo4j_id", "text"],
        )
        hits = []
        for h in res[0]:
            if h.distance >= threshold:
                hits.append({
                    "neo4j_id": h.entity.get("neo4j_id"),
                    "text": h.entity.get("text"),
                    "score": round(float(h.distance), 4),
                })
        return hits

    def count(self, collection: str) -> int:
        if not utility.has_collection(collection):
            return 0
        return Collection(collection).num_entities
