"""知识图谱构建：一键建 Schema、灌种子数据、按需建 Milvus 向量。

用法：
    python ingest.py

幂等：Neo4j 用 MERGE 幂等；Milvus 仅在 collection 为空时写入，避免重复。
云端模式：设 USE_MILVUS=false 时只灌 Neo4j（用于给 AuraDB 云端库初始化）。
"""
import config
from embedder import get_embedder
from graph import Graph


def main():
    g = Graph()
    emb = get_embedder()

    print("=" * 56)
    print("疾病问诊 Agent —— 知识图谱构建")
    print("=" * 56)

    # 1. 连通性
    print("[1/4] 检查 Neo4j 连接 ...")
    g.verify()
    print("       Neo4j 连接正常")

    # 2. Schema 约束
    print("[2/4] 创建 Schema 约束 ...")
    g.ensure_schema()
    print("       6 个唯一性约束就绪")

    # 3. 种子数据
    print("[3/4] 灌入种子数据（6 类实体 + 9 类关系）...")
    g.seed()
    symptoms = g.list_symptoms()
    diseases = g.list_diseases()
    print(f"       症状 {len(symptoms)} 个、疾病 {len(diseases)} 个已就绪")

    # 4. Milvus（可选）
    if config.USE_MILVUS:
        from vector_store import VectorStore
        v = VectorStore()
        print("[4/4] 创建 Milvus collection 并写入向量 ...")
        v.ensure_collections(config.EMBED_DIM)
        if v.count("symptom_emb") == 0:
            v.insert("symptom_emb", [
                {"neo4j_id": s, "text": s, "embedding": emb.embed(s)} for s in symptoms
            ])
        if v.count("disease_emb") == 0:
            v.insert("disease_emb", [
                {
                    "neo4j_id": d["name"],
                    "text": f"{d['name']} {d['description'] or ''}".strip(),
                    "embedding": emb.embed(f"{d['name']} {d['description'] or ''}"),
                }
                for d in diseases
            ])
        print(f"       症状向量 {v.count('symptom_emb')} 条、疾病向量 {v.count('disease_emb')} 条")
    else:
        print("[4/4] USE_MILVUS=false，跳过 Milvus（云端模式，仅 Neo4j）")

    print("-" * 56)
    print("完成。可运行 `python agent.py` 或 `uvicorn app:app` 开始问诊。")
    print("=" * 56)

    g.close()


if __name__ == "__main__":
    main()
