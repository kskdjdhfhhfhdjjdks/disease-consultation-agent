"""疾病问诊 Agent：编排 7 步诊断 + 多轮追问 + 可解释报告。

诊断链路（对应设计文档第 7 节）：
  1. 症状抽取（LLM，降级为规则匹配）
  2. 实体链接（Milvus：口语症状 -> 规范 Symptom）
  3. 候选疾病打分（Neo4j：Σ weight(指向边)）
  4. 补齐 检查/科室/鉴别/用药（Neo4j）
  5. 红旗症状鉴别分支
  6. 信息完整度检查 -> 追问（最多 MAX_FOLLOWUP_ROUNDS 轮）
  7. 生成可解释报告

原则：医学结论（疾病排序、检查/科室推荐）全部来自图谱；LLM 只做语言层。

用法：
    python agent.py         # 交互式对话
    python agent.py "发热3天，咳，有痰，胸痛"   # 单次诊断
"""
import sys

import config
from embedder import get_embedder
from graph import Graph
from llm import LLM
from vector_store import VectorStore

# 口语 -> 规范症状 的同义词表（供无 LLM 时的规则抽取兜底）
SYNONYMS = {
    "发烧": "发热",
    "干咳": "咳嗽",
    "有痰": "咳痰",
    "痰": "咳痰",
    "喘不上气": "呼吸困难",
    "心慌": "心悸",
    "咯血": "咳血",
}

# 红旗症状 -> 固定澄清问句（无 LLM 时兜底）
RED_FLAG_QUESTIONS = {
    "胸痛": "胸痛是压榨样的吗？活动后会加重吗？",
}


class DiagnosisAgent:
    def __init__(self):
        self.graph = Graph()
        self.vector = None
        if config.USE_MILVUS:
            try:
                self.vector = VectorStore()
            except Exception:  # 云端无 Milvus 时优雅降级
                self.vector = None
        self.embedder = get_embedder()
        self.llm = LLM()
        self._known_symptoms = set(self.graph.list_symptoms())

    def close(self):
        self.graph.close()

    # ---------- Step 1：症状抽取 ----------
    def _extract(self, text: str) -> list[str]:
        if self.llm.available:
            try:
                items = self.llm.extract_symptoms(text)
                names = [it.get("name") for it in items if it.get("name")]
                if names:
                    return names
            except Exception:
                pass  # 降级到规则
        return self._extract_by_rules(text)

    def _extract_by_rules(self, text: str) -> list[str]:
        found = []
        for s in self._known_symptoms:
            if s in text:
                found.append(s)
        # 简写：单独的"咳"视为"咳嗽"（避开"咳嗽/咳痰"已命中）
        if "咳" in text and "咳嗽" not in text and "咳痰" not in text:
            found.append("咳嗽")
        for raw, canon in SYNONYMS.items():
            if raw in text and canon not in found:
                found.append(canon)
        return found

    # ---------- Step 2：实体链接 ----------
    def _link(self, name: str):
        if name in self._known_symptoms:
            return name
        if self.vector is None:
            return None
        try:
            hits = self.vector.search("symptom_emb", self.embedder.embed(name), top_k=3)
        except Exception:  # Milvus 不可用时退化为精确匹配
            return None
        return hits[0]["neo4j_id"] if hits else None

    # ---------- 主入口 ----------
    def diagnose(self, text: str, session: dict | None = None) -> dict:
        session = session or {"symptoms": [], "asked": set(), "rounds": 0}

        # Step 1~2：抽取 + 链接 + 合并
        for s in self._extract(text):
            linked = self._link(s)
            if linked and linked not in session["symptoms"]:
                session["symptoms"].append(linked)

        # Step 3：候选疾病打分
        ranked = self.graph.rank_diseases(session["symptoms"]) if session["symptoms"] else []
        # 红旗症状
        flags = self.graph.symptom_flags(session["symptoms"]) if session["symptoms"] else {}
        red = [s for s, f in flags.items() if f]

        # Step 6：信息完整度 -> 追问
        question = self._maybe_followup(session, ranked, red)
        if question:
            return {
                "status": "need_more",
                "reply": question,
                "session": session,
                "symptoms": list(session["symptoms"]),
                "partial": ranked[:3] if ranked else [],
            }

        # Step 7：报告（结构化 + 文本）
        data = self._analyze(session["symptoms"], ranked, red)
        return {
            "status": "done",
            "reply": self._format_report(data),
            "session": session,
            "report": data,
        }

    # ---------- Step 6：追问策略 ----------
    def _maybe_followup(self, session: dict, ranked: list, red: list[str]):
        if session["rounds"] >= config.MAX_FOLLOWUP_ROUNDS:
            return None

        # 红旗症状澄清（只问一次）
        for s in red:
            key = f"red:{s}"
            if key in session["asked"]:
                continue
            session["asked"].add(key)
            session["rounds"] += 1
            if s in RED_FLAG_QUESTIONS:
                return self._followup_text(RED_FLAG_QUESTIONS[s], s)
            return self._followup_text(f"能具体说说「{s}」的情况吗？", s)

        # 无候选疾病 -> 收集更多症状
        if not ranked:
            session["rounds"] += 1
            return "请再补充一些症状，例如：发热、咳嗽、咳痰、胸痛、多饮、多尿、体重下降？"

        return None

    def _followup_text(self, fallback: str, symptom: str) -> str:
        if self.llm.available:
            try:
                return self.llm.generate_followup(f"患者存在需澄清的症状：{symptom}")
            except Exception:
                pass
        return fallback

    # ---------- Step 7：报告 ----------
    def _analyze(self, symptoms: list[str], ranked: list[dict], red: list[str]) -> dict:
        """结构化诊断结果（供前端渲染与文本报告共用）。"""
        total = len(symptoms)
        data = {
            "symptoms": symptoms,
            "candidates": [],
            "exams": [],
            "departments": [],
            "drugs": [],
            "explanation": "",
            "description": "",
            "differentials": [],
            "red_flags": red,
            "top_disease": None,
            "disclaimer": "本结果仅供辅助参考，不能替代执业医师的诊断，请及时就医。",
        }
        for r in ranked[:3]:
            data["candidates"].append({
                "disease": r["disease"],
                "matched_count": r["matched_count"],
                "total": total,
                "score": round(r["score"], 2),
                "confidence": self._confidence(r["matched_count"], total, r["score"]),
            })
        if ranked:
            top = ranked[0]["disease"]
            d = self.graph.get_disease_details(top)
            data["top_disease"] = top
            data["exams"] = [e["name"] for e in d.get("exams", [])]
            data["departments"] = list(d.get("departments", []))
            data["drugs"] = [{"name": x["name"], "line": x.get("line")} for x in d.get("drugs", [])]
            matched = " + ".join(ranked[0]["matched_symptoms"])
            data["explanation"] = (
                f"{matched} 是 {top} 的常见/相关表现"
                f"（症状→疾病「指向」边，score={round(ranked[0]['score'], 2)}）"
            )
            data["description"] = d.get("description", "")
            data["differentials"] = [
                {"name": x["name"], "direction": x.get("direction")}
                for x in d.get("differentials", [])
            ]
        return data

    @staticmethod
    def _format_report(data: dict) -> str:
        """结构化结果 -> 终端文本（CLI 用）。"""
        lines = ["【候选疾病】"]
        if not data["candidates"]:
            lines.append("  （当前信息不足以给出候选，请补充症状）")
        else:
            for i, c in enumerate(data["candidates"], 1):
                lines.append(
                    f"  {i}. {c['disease']}（匹配症状 {c['matched_count']}/{c['total']}，置信度 {c['confidence']}）"
                )
        if data["candidates"]:
            if data["exams"]:
                lines.append(f"\n【建议检查】{'、'.join(data['exams'])}")
            if data["departments"]:
                lines.append(f"【推荐科室】{'、'.join(data['departments'])}")
            if data["drugs"]:
                drugs = "、".join(f"{x['name']}({x['line'] or '—'})" for x in data["drugs"])
                lines.append(f"【常见用药·仅供参考】{drugs}（剂量遵医嘱）")
            lines.append("\n【解释依据】")
            lines.append(f"  {data['explanation']}")
            if data["description"]:
                lines.append(f"  {data['top_disease']}：{data['description']}")
            if data["differentials"]:
                lines.append("\n【鉴别方向】")
                for x in data["differentials"]:
                    note = f"（{x['direction']}）" if x.get("direction") else ""
                    lines.append(f"  · 需与 {x['name']} 鉴别{note}")
        if data["red_flags"]:
            lines.append(
                f"\n⚠️ 存在需警惕的症状：{'、'.join(data['red_flags'])}。建议尽快就医，由医生进一步评估。"
            )
        lines.append("\n⚠️ " + data["disclaimer"])
        return "\n".join(lines)

    @staticmethod
    def _confidence(matched_count: int, total: int, score: float) -> str:
        ratio = matched_count / max(total, 1)
        if ratio >= 0.6 or score >= 2.0:
            return "高"
        if ratio >= 0.3 or score >= 1.0:
            return "中"
        return "低"


def run_once(text: str):
    agent = DiagnosisAgent()
    try:
        res = agent.diagnose(text)
        print(res["reply"])
    finally:
        agent.close()


def run_interactive():
    agent = DiagnosisAgent()
    session = None
    print("疾病问诊 Agent 已就绪（输入 quit 退出）")
    try:
        while True:
            text = input("\n你 > ").strip()
            if text.lower() in ("quit", "exit", "q"):
                break
            if not text:
                continue
            try:
                res = agent.diagnose(text, session)
                session = res["session"]
                print("\n助手 >")
                print(res["reply"])
            except Exception as e:  # noqa: BLE001
                print(f"[错误] {e}")
    finally:
        agent.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_once(" ".join(sys.argv[1:]))
    else:
        run_interactive()
