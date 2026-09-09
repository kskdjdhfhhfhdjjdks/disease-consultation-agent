"""Claude 封装：自然语言理解（症状抽取）+ 追问生成。

设计原则：LLM 只做"语言"层面的事（把自由文本变成结构化症状、把追问
变成自然的问句），**不做医学结论**——疾病排序、检查/科室推荐一律来自
Neo4j 图谱（graph.py），保证可追溯、可审计。

所有方法都带降级：Claude 不可用（无凭证/网络失败）时抛出的异常由
上层 agent 捕获并走规则兜底。
"""
import json

import anthropic

import config


class LLM:
    def __init__(self):
        try:
            self.client = anthropic.Anthropic()
            self.available = True
        except Exception:
            self.client = None
            self.available = False

    def _chat(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        resp = self.client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    @staticmethod
    def _parse_json(text: str):
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    # ---- 症状抽取 ----
    def extract_symptoms(self, complaint: str) -> list[dict]:
        """从主诉抽取结构化症状。

        返回 [{name, duration, location, severity}]，缺失字段为 null。
        """
        system = (
            "你是医学问诊助手，负责从患者主诉中抽取症状，不做诊断。"
            "只输出 JSON，不要输出任何其他文字。"
        )
        prompt = (
            "从以下主诉中抽取所有症状。输出 JSON 数组，每个元素为对象，"
            '含四个字段："name"(症状名，如 发热/咳嗽)、"duration"(持续时间，如 3天)、'
            '"location"(部位)、"severity"(严重程度)。缺失的字段填 null。\n\n'
            f"主诉：{complaint}\n\n只输出 JSON 数组："
        )
        text = self._chat(system, prompt, max_tokens=2048)
        data = self._parse_json(text)
        return data if isinstance(data, list) else [data]

    # ---- 追问生成 ----
    def generate_followup(self, context: str) -> str:
        """基于上下文生成一句自然的追问（用于红旗症状澄清 / 鉴别）。"""
        system = (
            "你是医学问诊助手。根据当前信息，向患者提出一句简短、具体的追问，"
            "以补充鉴别诊断所需的关键信息。只输出这一句问话。"
        )
        prompt = f"当前已收集信息：\n{context}\n\n请提出一句追问："
        return self._chat(system, prompt, max_tokens=512).strip()
