# 疾病问诊 Agent 产品设计文档

> 版本：v1.0　|　日期：2026-09-09　|　状态：设计定稿（待评审）
> 关联文档：`产品说明.txt`（3.3 / 3.4 / 四~六 章节）
> 运行环境已就绪：Neo4j 5.26.30(community) `bolt://127.0.0.1:7687`、Milvus `127.0.0.1:19530/9091`、Python 3.10.4 + anthropic SDK

---

## 0. 一句话定位

一个 **辅助诊断 + 知识支持** 的对话式 Agent：用户输入症状 → 系统给出候选疾病、必要检查、推荐科室、鉴别方向，并输出**可解释的证据链**，同时能**对话式追问**补全信息。**不替代医生，只做辅助。**

---

## 1. 产品能力清单（从产品说明收敛）

| 编号 | 能力 | 对应技术模块 | 输出示例 |
|---|---|---|---|
| C1 | 输入症状 → 候选疾病 | 抽取 + 检索 + 推理 | 肺炎、支气管炎、上呼吸道感染 |
| C2 | 基于候选疾病推荐必要检查 | 检索 + 推理 | 血常规、胸片 |
| C3 | 基于检查结果给出诊疗建议 | 推理 + Agent | 结合血象/影像 → 进一步建议 |
| C4 | 输出解释路径 | 推理 + 解释 | 发热+咳嗽+咳痰 → 肺炎（权重0.9） |
| C5 | 支持鉴别诊断 | 检索（鉴别诊断边） | 压榨样胸痛 → 排除心源性疾病 |
| C6 | 对话式追问 | Agent + 槽位填充 | "发热体温多高？持续几天？" |

---

## 2. 总体架构

```
                        ┌─────────────────────────────┐
                        │        用户（对话界面）        │
                        └──────────────┬──────────────┘
                                       │ 主诉文本
                        ┌──────────────▼──────────────┐
                        │   诊断 Agent（LLM 编排层）     │
                        │  Claude / anthropic SDK      │
                        │  ReAct 循环 + 工具调用        │
                        │  + 槽位状态 + 追问策略        │
                        └───┬────────┬────────┬────────┘
                ┌───────────┘        │        └───────────┐
        ┌───────▼───────┐   ┌───────▼───────┐   ┌────────▼────────┐
        │  知识抽取工具   │   │  图谱推理工具   │   │   语义检索工具    │
        │ (LLM 结构化)   │   │  (Neo4j)      │   │   (Milvus)       │
        └───────┬───────┘   └───────┬───────┘   └────────┬────────┘
                │                   │                    │
        ┌───────▼───────────────────▼────────────────────▼────────┐
        │                      存储层                              │
        │  Neo4j（符号知识图谱：实体/关系/属性 → 精确推理）          │
        │  Milvus（向量库：症状/疾病/检查 embedding → 语义模糊匹配） │
        └─────────────────────────────────────────────────────────┘
```

**三个核心角色：**

1. **LLM（Claude）**：自然语言理解、知识抽取、工具编排、追问决策、解释生成。
2. **Neo4j**：**符号推理**——精确、可解释、支持关系遍历（症状→疾病→检查/科室/鉴别）。
3. **Milvus**：**语义检索**——把口语化症状模糊对齐到图谱里的规范实体，处理同义词/近义表述，并承载医学知识片段的 RAG。

> **为什么两者都要？** 图谱是"骨架"（结构化的医学关系，可解释可推理），向量是"皮肤"（把自由文本接到骨架上）。只用图谱，口语"喘不上气"对不上规范"呼吸困难"；只用向量，给不出"发热+咳嗽+咳痰→肺炎→血常规"这条可解释链条。两者互补。

---

## 3. 知识建模（Neo4j Schema）

### 3.1 实体（6 类核心 + 1 类预留）

| Label | 中文 | 关键属性 | 说明 |
|---|---|---|---|
| `Symptom` | 症状 | `name`、`location`(部位)、`duration_type`(持续时间)、`severity`(严重程度)、`red_flag`(是否红旗症状) | 患者体感异常 |
| `Disease` | 疾病 | `name`、`etiology`(病因)、`classification`(分类)、`prognosis`(预后)、`description` | 诊断名称 |
| `Exam` | 检查 | `name`、`cost`(费用)、`duration`(耗时)、`population`(适用人群) | 诊断性检查 |
| `Drug` | 药品 | `name`、`dose`(剂量)、`usage`(用法)、`adverse_reaction`(不良反应) | 治疗药物 |
| `Department` | 科室 | `name` | 就诊科室 |
| `Complication` | 并发症 | `name` | 继发问题 |
| `Guideline` | 指南 | `name`、`source`、`year` | **预留扩展** |

> 属性 vs 实体原则（沿用产品说明 5.4）：被反复关联/查询/推理的 → 建实体或关系；仅作附属描述 → 建属性。

### 3.2 关系（9 类核心 + 2 类预留）

| 关系 | 方向 | 含义 | 关键属性 |
|---|---|---|---|
| `指向` | Symptom → Disease | 症状是疾病的临床表现 | `weight`(0~1，症状对该疾病的指向强度)、`frequency`(出现频率) |
| `典型症状` | Disease → Symptom | 疾病的典型症状 | `weight`、`typical`(是否典型) |
| `需要检查` | Disease → Exam | 疾病需要做的检查 | `priority`(首选/次选)、`rationale` |
| `治疗药物` | Disease → Drug | 疾病常见用药 | `line`(一线/二线) |
| `归属科室` | Disease → Department | 疾病归属科室 | — |
| `并发症` | Disease → Complication | 疾病的并发症 | `probability` |
| `鉴别诊断` | Disease → Disease | 需鉴别的疾病 | `direction`(鉴别方向说明) |
| `适应症` | Drug → Disease | 药物适应症 | — |
| `禁忌症` | Drug → Disease | 药物禁忌 | `reason` |
| `指南支撑`(预留) | Disease/Drug → Guideline | 结论的证据来源 | `level`(证据等级) |

### 3.3 Cypher 建图脚本（可直接在 Neo4j 执行）

```cypher
// 约束（保证 name 唯一，方便 MERGE）
CREATE CONSTRAINT symptom_name IF NOT EXISTS FOR (n:Symptom) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT disease_name IF NOT EXISTS FOR (n:Disease) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT exam_name    IF NOT EXISTS FOR (n:Exam)    REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT drug_name    IF NOT EXISTS FOR (n:Drug)    REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT dept_name    IF NOT EXISTS FOR (n:Department) REQUIRE n.name IS UNIQUE;

// —— 示例种子数据：肺炎链路 ——
MERGE (fever:Symptom {name:'发热'}) SET fever.location='全身', fever.red_flag=false;
MERGE (cough:Symptom {name:'咳嗽'});
MERGE (sputum:Symptom {name:'咳痰'});
MERGE (chestPain:Symptom {name:'胸痛'}) SET chestPain.red_flag=true;

MERGE (pneumonia:Disease {name:'肺炎', etiology:'细菌/病毒/真菌感染', classification:'呼吸系统感染', prognosis:'及时治疗预后良好'});
MERGE (bronchitis:Disease {name:'支气管炎', classification:'呼吸系统感染'});
MERGE (uri:Disease {name:'上呼吸道感染', classification:'呼吸系统感染'});
MERGE (chd:Disease {name:'冠心病', classification:'心血管疾病'});

MERGE (cbc:Exam {name:'血常规', cost:'低', duration:'快', population:'通用'});
MERGE (cxr:Exam {name:'胸片', cost:'低', duration:'快'});
MERGE (ecg:Exam {name:'心电图', cost:'低', duration:'快'});

MERGE (resp:Department {name:'呼吸科'});
MERGE (cardio:Department {name:'心内科'});

// 症状 → 疾病（指向，带权重）
MERGE (fever)-[:指向 {weight:0.9, frequency:'常见'}]->(pneumonia);
MERGE (cough)-[:指向 {weight:0.9, frequency:'常见'}]->(pneumonia);
MERGE (sputum)-[:指向 {weight:0.85, frequency:'常见'}]->(pneumonia);
MERGE (chestPain)-[:指向 {weight:0.5, frequency:'偶见'}]->(pneumonia);
MERGE (fever)-[:指向 {weight:0.7}]->(bronchitis);
MERGE (cough)-[:指向 {weight:0.8}]->(bronchitis);
MERGE (fever)-[:指向 {weight:0.6}]->(uri);
MERGE (chestPain)-[:指向 {weight:0.9}]->(chd);

// 疾病 → 典型症状 / 检查 / 科室 / 鉴别
MERGE (pneumonia)-[:典型症状 {weight:0.9}]->(fever);
MERGE (pneumonia)-[:典型症状 {weight:0.9}]->(cough);
MERGE (pneumonia)-[:典型症状 {weight:0.85}]->(sputum);
MERGE (pneumonia)-[:需要检查 {priority:'首选'}]->(cbc);
MERGE (pneumonia)-[:需要检查 {priority:'首选'}]->(cxr);
MERGE (pneumonia)-[:归属科室]->(resp);
MERGE (pneumonia)-[:鉴别诊断 {direction:'胸痛压榨样且活动后加重需排除心源性疾病'}]->(chd);
MERGE (chd)-[:需要检查 {priority:'首选'}]->(ecg);
MERGE (chd)-[:归属科室]->(cardio);
```

---

## 4. 知识抽取（LLM 把文本变成结构化知识）

沿用产品说明 6.3 的抽取 Prompt 设计（任务描述 / 实体类型定义 / 输出格式 / 待抽取文本四段式）。这是**离线建库**阶段做的事，与在线问诊分离。

抽取产出两路写入：

1. **结构化三元组 → Neo4j**（MERGE 节点与关系）。
2. **文本片段 + embedding → Milvus**（原始证据留存，供 RAG 追溯）。

> 抽取走**管道式**（实体识别 → 候选配对 → 关系分类）保证可控；对简单句子可走**联合式**直接出三元组。文档选择：默认管道式，低置信度回退联合式。

---

## 5. 存储设计（Neo4j + Milvus 分工）

### 5.1 Neo4j 存什么

- 全部实体节点、关系、属性（第 3 节 Schema）。
- 承载**精确推理**：症状聚合 → 疾病排序、需要检查、归属科室、鉴别诊断、治疗药物。

### 5.2 Milvus 存什么（三张 collection）

| Collection | 字段 | 用途 |
|---|---|---|
| `symptom_emb` | `id`(主键)、`neo4j_id`、`text`、`embedding` | 口语症状 → 规范 Symptom 的**实体链接** |
| `disease_emb` | `id`、`neo4j_id`、`text`(疾病名+描述)、`embedding` | 用户描述 → 候选疾病的语义兜底 |
| `knowledge_chunk` | `id`、`source`、`text`、`embedding` | 医学知识/指南片段，**RAG** 回答开放问题 |

embedding 维度与所用 embedding 模型一致（示例 1536；用其他模型时同步改 `dim`）。

```python
# 建 collection 示意（pymilvus）
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType

connections.connect(host="127.0.0.1", port="19530")

fields = [
    FieldSchema("id",        DataType.INT64,       is_primary=True, auto_id=True),
    FieldSchema("neo4j_id",  DataType.VARCHAR,     max_length=64),
    FieldSchema("text",      DataType.VARCHAR,     max_length=512),
    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=1536),
]
col = Collection("symptom_emb", CollectionSchema(fields, "症状实体链接向量"))
col.create_index("embedding",
                 {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}})
col.load()
```

---

## 6. 检索层（混合检索）

| 路径 | 引擎 | 命中 | 特点 |
|---|---|---|---|
| 精确图谱查询 | Neo4j Cypher | 规范实体/关系 | 精确、可解释、可推理 |
| 语义相似检索 | Milvus ANN | 近义/口语表述 | 模糊、抗表述差异 |
| RAG | Milvus + LLM | 知识片段 | 回答开放问题 |

**融合策略：** 先 Milvus 做**实体链接**（口语 → 规范 Symptom），再进 Neo4j 做**关系推理**，最后 LLM 对开放问题用 RAG 兜底。即"语义归一化 → 符号推理 → 生成式补充"。

---

## 7. 诊断推理算法（核心，一步一步）

> 这是整个 Agent 的"大脑"，对应产品说明 C1~C5。

### Step 1　症状抽取与规范化

- 输入：`患者主诉：发热3天，咳，有痰，胸痛`
- 用 LLM 抽取结构化症状 + 属性槽位：

```json
[{"name":"发热","duration":"3天","severity":null,"location":null},
 {"name":"咳嗽","duration":null,"severity":null,"location":null},
 {"name":"咳痰","duration":null,"severity":null,"location":null},
 {"name":"胸痛","duration":null,"severity":null,"location":null}]
```

### Step 2　实体链接（Milvus）

- 每个抽取症状文本 → embedding → `symptom_emb` Top-K 检索 → 映射到 Neo4j 的 `Symptom.name`。
- 阈值过滤（如余弦相似度 < 0.6 视为未命中，进入追问）。

### Step 3　候选疾病打分（Neo4j 聚合）

对命中的症状集合，统计每条 `指向` 边并累加权重：

```cypher
MATCH (s:Symptom)-[r:指向]->(d:Disease)
WHERE s.name IN $symptoms
RETURN d.name AS disease,
       count(r) AS matched_count,
       sum(r.weight) AS score
ORDER BY score DESC
```

打分公式（示例）：`score = Σ weight(指向边)`，辅以 `matched_count` 决定置信度。可扩展为 `score = Σ weight × matched_count` 让"多症状命中"占优。

**对示例输出排序：** 肺炎（发热0.9+咳嗽0.9+咳痰0.85+胸痛0.5 = 3.15）> 支气管炎 > 上呼吸道感染。

### Step 4　补齐"疾病 → 检查/科室/鉴别"

```cypher
MATCH (d:Disease {name:$disease})
OPTIONAL MATCH (d)-[:需要检查]->(e:Exam)
OPTIONAL MATCH (d)-[:归属科室]->(dp:Department)
OPTIONAL MATCH (d)-[:鉴别诊断]->(dd:Disease)
RETURN d, collect(DISTINCT e.name) AS exams,
       collect(DISTINCT dp.name) AS dept,
       collect(DISTINCT dd.name) AS differential
```

### Step 5　鉴别诊断分支（红旗症状触发）

- 命中含 `red_flag=true` 的症状（如"胸痛"）→ 沿 `鉴别诊断` 边取方向说明，生成鉴别提示：
  - "胸痛压榨样且活动后加重 → 排除心源性疾病（冠心病），建议心电图。"
- **安全升级**：红旗症状（压榨样胸痛、呼吸困难、高热惊厥等）→ 输出"建议立即就医"。

### Step 6　信息完整度检查 → 触发追问（对应 C6，见第 9 节）

- 缺失的关键槽位（症状的 `location`/`duration_type`/`severity`）→ 生成追问。

### Step 7　生成可解释输出（对应 C4）

最终输出结构化报告（见第 10 节模板），每条结论都带**证据链**：

```
发热(3天) + 咳嗽 + 咳痰 →[指向 0.9/0.9/0.85]→ 肺炎
肺炎 →[需要检查]→ 血常规、胸片
肺炎 →[归属科室]→ 呼吸科
胸痛 →[鉴别诊断]→ 冠心病（压榨样且活动后加重需排除）
```

---

## 8. Agent 设计（编排层）

### 8.1 工具集（Tool 定义）

Agent 通过 **Anthropic 的 tool-use（函数调用）** 暴露以下工具：

| 工具名 | 参数 | 返回 | 背后引擎 |
|---|---|---|---|
| `extract_symptoms` | `text` | 结构化症状数组 | LLM |
| `link_symptom` | `symptom_text, top_k` | 规范 Symptom 候选 | Milvus |
| `rank_diseases` | `symptoms[]` | 候选疾病 + 分数 | Neo4j |
| `get_exams` | `disease` | 检查列表 | Neo4j |
| `get_department` | `disease` | 科室 | Neo4j |
| `get_differential` | `disease` | 鉴别诊断 + 方向 | Neo4j |
| `get_drugs` | `disease` | 治疗药物 | Neo4j |
| `search_knowledge` | `query, top_k` | 知识片段（RAG） | Milvus |
| `ask_followup` | `question` | 追问文本 | —（槽位策略） |

### 8.2 ReAct 循环（编排伪代码）

```python
state = {"symptoms": [], "slots": {}, "history": []}

def run_diagnosis(complaint):
    # 1) 抽取
    raw = tool.extract_symptoms(complaint)
    # 2) 实体链接
    for s in raw:
        linked = tool.link_symptom(s["name"])
        if linked.confidence >= 0.6:
            state["symptoms"].append(linked.name)
        else:
            pending.append(s["name"])          # 未命中 → 待追问
    # 3) 推理
    candidates = tool.rank_diseases(state["symptoms"])
    top = candidates[0]
    exams = tool.get_exams(top)
    dept = tool.get_department(top)
    diff = tool.get_differential(top)
    # 4) 信息完整度 / 鉴别追问
    question = followup_strategy(state, top, diff)   # 见第 9 节
    if question:
        return {"reply": question, "partial": {...}, "need_more": True}
    # 5) 生成报告（带解释路径）
    return build_report(state, top, candidates, exams, dept, diff)
```

### 8.3 状态与多轮

- `slots` 保存已确认的属性（部位/持续时间/严重程度）。
- 多轮对话累积症状；用户补充回答后重新走 Step 1~7，分数动态更新。

---

## 9. 对话式追问策略（C6）

| 触发条件 | 追问类型 | 示例 |
|---|---|---|
| 症状未命中规范实体 | 澄清症状 | "你说的'喘不上气'是指呼吸困难吗？" |
| 红旗症状缺严重度 | 鉴别/安全追问 | "胸痛是压榨样吗？活动后会加重吗？" |
| 候选疾病分数接近 | 鉴别追问 | "发热最高到多少度？有寒战吗？" |
| 缺持续时间/部位 | 槽位追问 | "咳嗽持续几天了？" |

**追问上限**：单轮最多 2 个问题、全局最多 3 轮追问，避免打扰（配置项）。

---

## 10. 输出报告模板（对齐产品说明 3.4）

```
【候选疾病】
1. 肺炎（匹配症状 4/4，置信度 高）
2. 支气管炎（2/4，中）
3. 上呼吸道感染（1/4，低）

【建议检查】血常规、胸片
【推荐科室】呼吸科
【解释依据】
发热(3天)+咳嗽+咳痰 是肺炎常见症状（指向权重 0.9/0.9/0.85）；
胸痛提示需进一步排查肺部感染或胸膜受累。

【鉴别方向】
若胸痛为压榨样且活动后加重，需排除心源性疾病（冠心病），建议心电图。

⚠️ 本结果仅供辅助参考，不能替代执业医师的诊断，请及时就医。
```

---

## 11. 接口设计（FastAPI，预留）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 对话主入口：输入主诉/追问回答，返回回复 + 是否需要更多信息 |
| GET | `/api/report/{session_id}` | 拉取某会话的诊断报告 |
| POST | `/api/ingest` | 离线：上传医学文本，触发抽取入库（Neo4j + Milvus） |
| GET | `/healthz` | 健康检查（探测 Neo4j / Milvus 连通性） |

---

## 12. 评估与安全

### 12.1 评估指标

- **实体链接准确率**：抽取症状映射到规范 Symptom 的 F1。
- **候选疾病命中率**：金标准疾病是否出现在 Top-3 / Top-5。
- **解释可追溯性**：每条结论能否回查到图谱边。
- **追问有效性**：追问后诊断置信度提升幅度。

### 12.2 医学安全红线

1. 永远输出**免责声明**（不替代医生）。
2. **红旗症状**（压榨样胸痛、呼吸困难、意识改变、高热惊厥、大出血等）→ 强制"立即就医"提示，优先于其他结论。
3. 不直接给出**处方剂量**（药品剂量仅作知识展示，标注"遵医嘱"）。
4. 用药禁忌（`禁忌症` 边）在建议药品时**强制过滤**。

---

## 13. 落地实施步骤（Roadmap）

| 阶段 | 任务 | 产出 |
|---|---|---|
| P0 | 环境确认 + 依赖安装 | `neo4j`、`pymilvus`、`fastapi`、`uvicorn` 装齐 |
| P1 | Neo4j 建 Schema + 种子数据 | 第 3 节 Cypher 可执行 |
| P2 | Milvus 建 collection + embedding 入库 | 三张 collection 就绪 |
| P3 | 实体链接 + 疾病打分（离线验证） | Step 2~3 跑通，Top-3 命中 |
| P4 | Agent 工具 + ReAct 循环 | 对话式问诊闭环 |
| P5 | 追问策略 + 解释路径 + 安全红线 | 完整报告输出 |
| P6 | FastAPI 接口 + 联调 | 可对外访问 |

**依赖清单（requirements.txt）：**

```
anthropic          # 已装
numpy              # 已装
neo4j              # pip install neo4j
pymilvus           # pip install pymilvus
fastapi
uvicorn
```

**连接配置（环境变量）：**

```
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<你的密码>
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
ANTHROPIC_MODEL=claude-sonnet-5   # 可配置
```

---

## 14. 待确认问题（评审清单）

1. embedding 模型选型（影响 Milvus `dim` 与实体链接效果）。
2. 疾病打分的精确公式（是否引入"多症状命中加权"）。
3. 红旗症状清单的最终范围。
4. 种子数据的规模与来源（演示用 20+ 疾病，还是先 4 类打样）。
