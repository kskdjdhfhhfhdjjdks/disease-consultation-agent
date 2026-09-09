"""Embedding 抽象与占位实现。

生产环境请实现语义 embedding（如 BGE-M3 / text-embedding 模型），
替换下面的 NGramHashEmbedder；只需实现 `embed(text) -> list[float]`，
并把 config.EMBED_DIM 改成对应维度即可，其余代码无需改动。
"""
import hashlib

import numpy as np

import config


class NGramHashEmbedder:
    """无外部依赖的占位 embedding：字符 n-gram 哈希。

    原理：
      1. 把文本切成 1~2 元字符组（中文单字 + 相邻双字）；
      2. 每个字符组用 md5 哈希到固定维度向量的一格并累加（md5 保证跨进程稳定）；
      3. L2 归一化。
    效果：共享字符越多的文本余弦相似度越高。适合让系统"开箱即跑"，
    但无语义（如"发烧"与"发热"相似度为 0），所以语义归一化主要靠 LLM 抽取层完成。

    注意：必须用稳定哈希（md5），不能用 Python 内置 hash()（其随机化种子会
    导致 ingest 与 query 两次运行的向量不一致）。
    """

    def __init__(self, dim: int = config.EMBED_DIM):
        self.dim = dim

    def _grams(self, text: str) -> list[str]:
        t = "".join(text.split())  # 去掉空白
        grams = [t[i] for i in range(len(t))]
        grams += [t[i:i + 2] for i in range(len(t) - 1)]
        return grams

    def _bucket(self, gram: str) -> int:
        h = hashlib.md5(gram.encode("utf-8")).hexdigest()
        return int(h, 16) % self.dim

    def embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype="float32")
        for g in self._grams(text):
            vec[self._bucket(g)] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()


def get_embedder() -> "object":
    """返回当前配置的 embedder。

    TODO：接入真实语义模型，例如：
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("BAAI/bge-small-zh-v1.5")  # dim=512
    并把 config.EMBED_DIM 改为对应维度。
    """
    if config.EMBED_MODEL == "ngram":
        return NGramHashEmbedder()
    raise ValueError(f"未知 EMBED_MODEL: {config.EMBED_MODEL}")
