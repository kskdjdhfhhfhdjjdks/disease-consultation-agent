# 疾病问诊 Agent

基于 **Neo4j（知识图谱）+ Milvus（向量检索）+ Claude（LLM 编排）** 的辅助诊断系统。
完整设计见 `疾病问诊Agent设计文档.md`。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置连接（复制示例并按实际填写，尤其 Neo4j 密码）
cp .env.example .env
# 编辑 .env 中的 NEO4J_PASSWORD

# 3. 构建知识图谱（建 Schema + 灌种子数据 + 建 Milvus 向量）
python ingest.py

# 4. 启动 Web 服务（接口 + 前端页面）
uvicorn app:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000

# 或命令行问诊（不用 Web）
python agent.py
python agent.py "发热3天，咳，有痰，胸痛"
```

## Web 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端页面 |
| POST | `/api/chat` | 对话入口，body `{message, session_id?}` |
| POST | `/api/reset` | 重置会话 |
| GET | `/api/report/{id}` | 取会话诊断报告 |
| GET | `/healthz` | 健康检查（Neo4j / Milvus） |

## 文件结构

| 文件 | 职责 |
|---|---|
| `config.py` | 连接串 / 模型 / 维度配置，自动加载 `.env` |
| `embedder.py` | embedding 抽象 + n-gram 哈希占位实现 |
| `graph.py` | Neo4j：Schema、种子数据、推理查询 |
| `vector_store.py` | Milvus：建 collection、写入、相似检索 |
| `llm.py` | Claude：症状抽取、追问生成（均带降级） |
| `ingest.py` | 知识图谱构建（一键建库） |
| `agent.py` | 诊断 Agent：7 步编排 + 多轮追问 + 报告 |

## 关键设计

- **医学结论只来自图谱**：疾病排序、检查/科室推荐走 Neo4j，可追溯可审计；LLM 只做语言层（抽取、追问）。
- **降级可跑**：即使 Claude 不可用，规则抽取 + 图谱推理仍能给出结构化报告。
- **embedding 是占位**：`embedder.py` 用字符 n-gram 哈希让系统开箱即跑；生产请替换为语义模型（如 BGE），并同步改 `config.EMBED_DIM`。

## 安全提示

本系统仅供辅助参考，不替代执业医师诊断。
