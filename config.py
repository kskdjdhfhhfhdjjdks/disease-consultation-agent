"""全局配置：连接串、模型、向量维度。

所有可配置项都支持通过环境变量或项目根目录的 `.env` 文件覆盖。
默认值针对本机已就绪的环境：Neo4j bolt 7687、Milvus 19530。
"""
import os
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """极简 .env 加载（不依赖 python-dotenv）。已存在的环境变量优先。"""
    p = Path(__file__).with_name(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

# ---- Neo4j（知识图谱：符号推理）----
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")  # 请按实际密码修改 .env

# ---- Milvus（向量库：语义检索 / 实体链接）----
MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")

# ---- Embedding ----
# 占位实现用 n-gram 哈希；生产请换成语义模型（见 embedder.py）
EMBED_DIM = int(os.getenv("EMBED_DIM", "256"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "ngram")
# 实体链接的余弦相似度阈值（低于此值视为未命中，进入追问）
LINK_THRESHOLD = float(os.getenv("LINK_THRESHOLD", "0.6"))

# ---- LLM（Claude）----
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

# ---- 对话追问 ----
MAX_FOLLOWUP_ROUNDS = int(os.getenv("MAX_FOLLOWUP_ROUNDS", "3"))

# ---- 部署开关（云端）----
# 云端无 Milvus 时设为 false（退化为精确匹配 + 规则/LLM 抽取）
USE_MILVUS = os.getenv("USE_MILVUS", "true").lower() in ("1", "true", "yes")
# 允许跨域的前端来源，多个用英文逗号分隔；"*" 表示任意来源
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
