"""Neo4j 数据访问层：Schema、种子数据、符号推理查询。

知识图谱承载"精确、可解释"的推理（症状→疾病→检查/科室/鉴别/用药）。
所有查询结果都来自图谱，保证可追溯（每一条结论都能回查到边）。
"""
from neo4j import GraphDatabase

import config

# ---- Schema 约束（name 唯一，便于 MERGE / 实体链接）----
CONSTRAINTS = [
    "CREATE CONSTRAINT symptom_name IF NOT EXISTS FOR (n:Symptom) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT disease_name IF NOT EXISTS FOR (n:Disease) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT exam_name    IF NOT EXISTS FOR (n:Exam)    REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT drug_name    IF NOT EXISTS FOR (n:Drug)    REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT dept_name    IF NOT EXISTS FOR (n:Department) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT compl_name   IF NOT EXISTS FOR (n:Complication) REQUIRE n.name IS UNIQUE",
]

# ---- 演示种子数据：覆盖 6 类实体 + 9 类关系，对齐产品说明 3.4 示例 ----
SEED = [
    # 症状（属性：location / red_flag）
    "MERGE (n:Symptom {name:'发热'}) SET n.location='全身', n.red_flag=false",
    "MERGE (n:Symptom {name:'咳嗽'}) SET n.location='呼吸道', n.red_flag=false",
    "MERGE (n:Symptom {name:'咳痰'}) SET n.location='呼吸道', n.red_flag=false",
    "MERGE (n:Symptom {name:'胸痛'}) SET n.location='胸部', n.red_flag=true",
    "MERGE (n:Symptom {name:'多饮'}) SET n.red_flag=false",
    "MERGE (n:Symptom {name:'多尿'}) SET n.red_flag=false",
    "MERGE (n:Symptom {name:'体重下降'}) SET n.red_flag=false",

    # 疾病（属性：etiology / classification / prognosis / description）
    "MERGE (n:Disease {name:'肺炎'}) SET n.classification='呼吸系统感染', n.etiology='细菌/病毒/真菌感染', n.prognosis='及时治疗预后良好', n.description='肺部感染性疾病，常见发热咳嗽咳痰'",
    "MERGE (n:Disease {name:'支气管炎'}) SET n.classification='呼吸系统感染', n.description='支气管黏膜炎症，咳嗽为主要表现'",
    "MERGE (n:Disease {name:'上呼吸道感染'}) SET n.classification='呼吸系统感染', n.description='鼻腔咽喉部位急性炎症'",
    "MERGE (n:Disease {name:'冠心病'}) SET n.classification='心血管疾病', n.description='冠状动脉粥样硬化导致心肌缺血'",
    "MERGE (n:Disease {name:'糖尿病'}) SET n.classification='内分泌代谢疾病', n.description='血糖升高为主的代谢性疾病'",

    # 检查 / 药品 / 科室 / 并发症
    "MERGE (n:Exam {name:'血常规'}) SET n.cost='低', n.duration='快', n.population='通用'",
    "MERGE (n:Exam {name:'胸片'}) SET n.cost='低', n.duration='快'",
    "MERGE (n:Exam {name:'心电图'}) SET n.cost='低', n.duration='快'",
    "MERGE (n:Exam {name:'空腹血糖'}) SET n.cost='低', n.duration='快'",
    "MERGE (n:Exam {name:'糖化血红蛋白'}) SET n.cost='中', n.duration='较慢'",
    "MERGE (n:Drug {name:'阿莫西林'}) SET n.dose='遵医嘱', n.usage='口服', n.adverse_reaction='过敏反应'",
    "MERGE (n:Drug {name:'阿司匹林'}) SET n.usage='口服', n.adverse_reaction='出血风险'",
    "MERGE (n:Drug {name:'二甲双胍'}) SET n.usage='口服', n.adverse_reaction='胃肠道反应'",
    "MERGE (n:Department {name:'呼吸科'})",
    "MERGE (n:Department {name:'心内科'})",
    "MERGE (n:Department {name:'内分泌科'})",
    "MERGE (n:Complication {name:'糖尿病足'})",
    "MERGE (n:Complication {name:'脑卒中'})",

    # 关系：症状 -[指向]-> 疾病（weight = 该症状对该疾病的指向强度）
    "MATCH (s:Symptom {name:'发热'}),(d:Disease {name:'肺炎'}) MERGE (s)-[:指向 {weight:0.9, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'咳嗽'}),(d:Disease {name:'肺炎'}) MERGE (s)-[:指向 {weight:0.9, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'咳痰'}),(d:Disease {name:'肺炎'}) MERGE (s)-[:指向 {weight:0.85, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'胸痛'}),(d:Disease {name:'肺炎'}) MERGE (s)-[:指向 {weight:0.5, frequency:'偶见'}]->(d)",
    "MATCH (s:Symptom {name:'发热'}),(d:Disease {name:'支气管炎'}) MERGE (s)-[:指向 {weight:0.7, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'咳嗽'}),(d:Disease {name:'支气管炎'}) MERGE (s)-[:指向 {weight:0.8, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'咳痰'}),(d:Disease {name:'支气管炎'}) MERGE (s)-[:指向 {weight:0.6, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'发热'}),(d:Disease {name:'上呼吸道感染'}) MERGE (s)-[:指向 {weight:0.6, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'咳嗽'}),(d:Disease {name:'上呼吸道感染'}) MERGE (s)-[:指向 {weight:0.5, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'胸痛'}),(d:Disease {name:'冠心病'}) MERGE (s)-[:指向 {weight:0.9, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'多饮'}),(d:Disease {name:'糖尿病'}) MERGE (s)-[:指向 {weight:0.85, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'多尿'}),(d:Disease {name:'糖尿病'}) MERGE (s)-[:指向 {weight:0.85, frequency:'常见'}]->(d)",
    "MATCH (s:Symptom {name:'体重下降'}),(d:Disease {name:'糖尿病'}) MERGE (s)-[:指向 {weight:0.7, frequency:'常见'}]->(d)",

    # 关系：疾病 -[典型症状]-> 症状
    "MATCH (d:Disease {name:'肺炎'}),(s:Symptom {name:'发热'}) MERGE (d)-[:典型症状 {weight:0.9}]->(s)",
    "MATCH (d:Disease {name:'肺炎'}),(s:Symptom {name:'咳嗽'}) MERGE (d)-[:典型症状 {weight:0.9}]->(s)",
    "MATCH (d:Disease {name:'肺炎'}),(s:Symptom {name:'咳痰'}) MERGE (d)-[:典型症状 {weight:0.85}]->(s)",

    # 关系：疾病 -[需要检查]-> 检查
    "MATCH (d:Disease {name:'肺炎'}),(e:Exam {name:'血常规'}) MERGE (d)-[:需要检查 {priority:'首选'}]->(e)",
    "MATCH (d:Disease {name:'肺炎'}),(e:Exam {name:'胸片'}) MERGE (d)-[:需要检查 {priority:'首选'}]->(e)",
    "MATCH (d:Disease {name:'冠心病'}),(e:Exam {name:'心电图'}) MERGE (d)-[:需要检查 {priority:'首选'}]->(e)",
    "MATCH (d:Disease {name:'糖尿病'}),(e:Exam {name:'空腹血糖'}) MERGE (d)-[:需要检查 {priority:'首选'}]->(e)",
    "MATCH (d:Disease {name:'糖尿病'}),(e:Exam {name:'糖化血红蛋白'}) MERGE (d)-[:需要检查 {priority:'首选'}]->(e)",

    # 关系：疾病 -[归属科室]-> 科室
    "MATCH (d:Disease {name:'肺炎'}),(p:Department {name:'呼吸科'}) MERGE (d)-[:归属科室]->(p)",
    "MATCH (d:Disease {name:'支气管炎'}),(p:Department {name:'呼吸科'}) MERGE (d)-[:归属科室]->(p)",
    "MATCH (d:Disease {name:'上呼吸道感染'}),(p:Department {name:'呼吸科'}) MERGE (d)-[:归属科室]->(p)",
    "MATCH (d:Disease {name:'冠心病'}),(p:Department {name:'心内科'}) MERGE (d)-[:归属科室]->(p)",
    "MATCH (d:Disease {name:'糖尿病'}),(p:Department {name:'内分泌科'}) MERGE (d)-[:归属科室]->(p)",

    # 关系：疾病 -[鉴别诊断]-> 疾病（带 direction 说明）
    "MATCH (d:Disease {name:'肺炎'}),(o:Disease {name:'冠心病'}) MERGE (d)-[:鉴别诊断 {direction:'胸痛压榨样且活动后加重需排除心源性疾病'}]->(o)",
    "MATCH (d:Disease {name:'冠心病'}),(o:Disease {name:'肺炎'}) MERGE (d)-[:鉴别诊断 {direction:'发热咳嗽咳痰需排除肺部感染'}]->(o)",

    # 关系：疾病 -[治疗药物]-> 药品
    "MATCH (d:Disease {name:'肺炎'}),(g:Drug {name:'阿莫西林'}) MERGE (d)-[:治疗药物 {line:'一线'}]->(g)",
    "MATCH (d:Disease {name:'冠心病'}),(g:Drug {name:'阿司匹林'}) MERGE (d)-[:治疗药物 {line:'一线'}]->(g)",
    "MATCH (d:Disease {name:'糖尿病'}),(g:Drug {name:'二甲双胍'}) MERGE (d)-[:治疗药物 {line:'一线'}]->(g)",

    # 关系：疾病 -[并发症]-> 并发症
    "MATCH (d:Disease {name:'糖尿病'}),(c:Complication {name:'糖尿病足'}) MERGE (d)-[:并发症 {probability:'较高'}]->(c)",
    "MATCH (d:Disease {name:'糖尿病'}),(c:Complication {name:'脑卒中'}) MERGE (d)-[:并发症 {probability:'较高'}]->(c)",

    # 关系：药品 -[适应症]-> 疾病 / 药品 -[禁忌症]-> 疾病
    "MATCH (g:Drug {name:'阿莫西林'}),(d:Disease {name:'肺炎'}) MERGE (g)-[:适应症]->(d)",
    "MATCH (g:Drug {name:'阿司匹林'}),(d:Disease {name:'冠心病'}) MERGE (g)-[:适应症]->(d)",
    "MATCH (g:Drug {name:'二甲双胍'}),(d:Disease {name:'糖尿病'}) MERGE (g)-[:适应症]->(d)",
    "MATCH (g:Drug {name:'阿莫西林'}),(d:Disease {name:'肺炎'}) MERGE (g)-[:禁忌症 {reason:'青霉素过敏者禁用'}]->(d)",
]


class Graph:
    """Neo4j 连接与推理查询封装。"""

    def __init__(self, uri=None, user=None, password=None):
        self._driver = GraphDatabase.driver(
            uri or config.NEO4J_URI,
            auth=(user or config.NEO4J_USER, password or config.NEO4J_PASSWORD),
        )

    def close(self):
        self._driver.close()

    def verify(self) -> bool:
        """连通性检查。"""
        with self._driver.session() as s:
            s.run("RETURN 1").single()
        return True

    def _write(self, cql: str):
        with self._driver.session() as s:
            s.run(cql)

    def _read(self, cql: str, **params) -> list:
        with self._driver.session() as s:
            return [r for r in s.run(cql, **params)]

    # ---- 建库 ----
    def ensure_schema(self):
        for c in CONSTRAINTS:
            self._write(c)

    def seed(self):
        for c in SEED:
            self._write(c)

    # ---- 查询（供 ingest / agent 使用）----
    def list_symptoms(self) -> list[str]:
        return [r["name"] for r in self._read("MATCH (s:Symptom) RETURN s.name AS name ORDER BY name")]

    def list_diseases(self) -> list[dict]:
        return [dict(r) for r in self._read(
            "MATCH (d:Disease) RETURN d.name AS name, d.description AS description ORDER BY name"
        )]

    def symptom_flags(self, symptoms: list[str]) -> dict[str, bool]:
        """返回每个症状是否为红旗症状。"""
        rows = self._read(
            "MATCH (s:Symptom) WHERE s.name IN $names RETURN s.name AS name, s.red_flag AS red_flag",
            names=symptoms,
        )
        return {r["name"]: bool(r["red_flag"]) for r in rows}

    # ---- 核心推理 ----
    def rank_diseases(self, symptoms: list[str]) -> list[dict]:
        """症状集合 -> 候选疾病（按 score 降序）。

        score = Σ weight(指向边)，matched_count 用于置信度与并列判断。
        """
        rows = self._read(
            """
            UNWIND $symptoms AS sname
            MATCH (s:Symptom {name: sname})-[r:指向]->(d:Disease)
            RETURN d.name AS disease,
                   count(r) AS matched_count,
                   sum(r.weight) AS score,
                   collect(s.name) AS matched_symptoms
            ORDER BY score DESC, matched_count DESC
            """,
            symptoms=symptoms,
        )
        return [dict(r) for r in rows]

    def get_disease_details(self, disease: str) -> dict:
        """单个疾病的完整诊疗链路：检查/科室/鉴别/用药/典型症状/并发症。"""
        rows = self._read(
            """
            MATCH (d:Disease {name: $disease})
            OPTIONAL MATCH (d)-[e:需要检查]->(exam:Exam)
            OPTIONAL MATCH (d)-[:归属科室]->(dept:Department)
            OPTIONAL MATCH (d)-[diff:鉴别诊断]->(dd:Disease)
            OPTIONAL MATCH (d)-[tx:治疗药物]->(drug:Drug)
            OPTIONAL MATCH (d)-[:典型症状]->(sym:Symptom)
            OPTIONAL MATCH (d)-[:并发症]->(comp:Complication)
            RETURN d.name AS disease,
                   d.description AS description,
                   collect(DISTINCT {name: exam.name, priority: e.priority}) AS exams,
                   collect(DISTINCT dept.name) AS departments,
                   collect(DISTINCT {name: dd.name, direction: diff.direction}) AS differentials,
                   collect(DISTINCT {name: drug.name, line: tx.line}) AS drugs,
                   collect(DISTINCT sym.name) AS typical_symptoms,
                   collect(DISTINCT comp.name) AS complications
            """,
            disease=disease,
        )
        return dict(rows[0]) if rows else {}
