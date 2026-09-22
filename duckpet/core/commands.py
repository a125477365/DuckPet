"""中文语音指令解析：规则解析（毫秒级，离线）为主，可选本地小 LLM 兜底。"""

from __future__ import annotations

import re

from .events import Intent, ParsedCommand
from .roles import Role

# 目标物中文 -> 检测器英文提示词（YOLO-World / COCO 用）
TARGET_PROMPTS = {
    "抹布": "rag",
    "布": "cloth",
    "毛巾": "towel",
    "球": "sports ball",
    "小球": "sports ball",
    "瓶子": "bottle",
    "拖鞋": "slipper",
    "玩具": "toy",
    "纸团": "paper ball",
    "沙发": "sofa",
}

DEST_PROMPTS = {
    "桌上": "table",
    "桌子": "table",
    "地上": "floor",
    "门口": "door",
    "篮子": "basket",
    "沙发": "sofa",
}

_FOLLOW = re.compile(r"(跟着我|跟我走|跟我来|跟随我|跟着我走|跟着主人)")
_KICK = re.compile(r"(踢球|踢.?球|把球踢|踢一下球)")
_CARRY_VERB = re.compile(r"(捡|叼|拿|搬|拾)")
_DIRECTION = re.compile(r"(左边|右边|前面|后面|旁边|脚下)")
_DEST = re.compile(r"(?:放|扔|丢|搬|拿)到(?P<dest>[\u4e00-\u9fff]{1,6})")
_TARGET = re.compile(
    r"(?:捡|叼|拿|搬|拾)(?:起|起来|一下|下)?(?:你?(?:左边|右边|前面|后面|旁边|脚下)的?)?"
    r"(?P<target>[\u4e00-\u9fff]{1,6}?)(?:放|扔|丢|搬|拿|$|，|。|,)"
)
_COME = re.compile(r"(过来|来这|来我这)")
_STOP = re.compile(r"(停下|别动|站住|休息吧|歇会)")
_SING = re.compile(r"(唱歌|唱首歌|来一首)")
_DANCE = re.compile(r"(跳舞|跳个舞|跳支舞|来段舞|dance)", re.IGNORECASE)
# 杂技（注意顺序：_DANCE 先匹配，"跳个舞"不会被 _JUMP 抢走）
_FWD_ROLL = re.compile(r"(前滚翻|前空翻|翻跟头|翻跟斗|打个滚|滚一个)")
_BACK_ROLL = re.compile(r"(后滚翻|后空翻)")
_JUMP = re.compile(r"(原地跳|跳一下|跳一跳|蹦蹦|跳高|跳起来)")
_LIE_DOWN = re.compile(r"(躺下|趴下|睡觉觉)")
_SIT = re.compile(r"(坐下|蹲下|坐好)")
_STAND_UP = re.compile(r"(站起来|起立|起身)")
_BA_TARGET = re.compile(r"把(?P<target>[\u4e00-\u9fff]{1,6}?)(?:捡|叼|拿|搬|拾|放)")
_SET_NAME = re.compile(
    r"(?:你以后(?:就)?叫|你(?:就)?叫|你的名字是|给你改名叫)(?P<name>[\u4e00-\u9fffA-Za-z0-9]{1,8})"
)
_ASK_NAME = re.compile(r"你叫什么名字")
_ADD_RELATION = re.compile(
    r"(?:记住我|认识一下).*(?:我是(?:你的?)?(?P<role>主人|家人|亲人|朋友|客人))?"
    r"|我是(?:你的?)(?P<role2>主人|家人|亲人|朋友|客人)"
)
_SELF_NAME = re.compile(r"我叫(?P<name>[\u4e00-\u9fffA-Za-z0-9]{1,8})")


class RuleParser:
    def parse(self, text: str, speaker_role: Role = Role.STRANGER) -> ParsedCommand:
        t = text.strip().strip("。！？!?,，")
        if not t:
            return ParsedCommand(Intent.UNKNOWN, raw=text)

        if _ASK_NAME.search(t):
            return ParsedCommand(Intent.UNKNOWN, raw=text)  # 由上层礼貌回答

        m = _SET_NAME.search(t)
        if m:
            return ParsedCommand(Intent.SET_NAME, raw=text, person_name=m.group("name"))

        m = _ADD_RELATION.search(t)
        if m:
            role_text = m.group("role") or m.group("role2")
            name_m = _SELF_NAME.search(t)
            return ParsedCommand(
                Intent.ADD_RELATION,
                raw=text,
                person_name=name_m.group("name") if name_m else None,
                relation_role=Role.from_label(role_text) if role_text else Role.GUEST,
            )

        if _FOLLOW.search(t):
            return ParsedCommand(Intent.FOLLOW, raw=text)

        if _KICK.search(t):
            return ParsedCommand(Intent.KICK_BALL, raw=text, target="球")

        if _CARRY_VERB.search(t):
            ba_m = _BA_TARGET.search(t)
            target_m = _TARGET.search(t)
            dir_m = _DIRECTION.search(t)
            dest_m = _DEST.search(t)
            target = (ba_m.group("target") if ba_m
                      else (target_m.group("target") if target_m else None))
            return ParsedCommand(
                Intent.CARRY,
                raw=text,
                target=target,
                direction=dir_m.group(1) if dir_m else None,
                destination=dest_m.group("dest") if dest_m else None,
            )

        if _COME.search(t):
            return ParsedCommand(Intent.COME, raw=text)
        if _STOP.search(t):
            return ParsedCommand(Intent.STOP, raw=text)
        if _SING.search(t):
            return ParsedCommand(Intent.SING, raw=text)
        if _DANCE.search(t):
            return ParsedCommand(Intent.DANCE, raw=text)
        if _FWD_ROLL.search(t):
            return ParsedCommand(Intent.TRICK, raw=text, target="roulade")
        if _BACK_ROLL.search(t):
            return ParsedCommand(Intent.TRICK, raw=text, target="backflip")
        if _JUMP.search(t):
            return ParsedCommand(Intent.TRICK, raw=text, target="jump")
        if _LIE_DOWN.search(t):
            return ParsedCommand(Intent.TRICK, raw=text, target="lie_down")
        if _SIT.search(t):
            return ParsedCommand(Intent.SIT, raw=text)
        if _STAND_UP.search(t):
            return ParsedCommand(Intent.STAND_UP, raw=text)
        return ParsedCommand(Intent.UNKNOWN, raw=text)


class OllamaParser:
    """规则解析不出来时，用本地小 LLM（如 Qwen2.5-1.5B）做结构化抽取。"""

    SYSTEM = (
        "你是机器鸭的指令解析器。把中文指令解析成 JSON："
        "action 只能是 follow/kick_ball/carry/come/stop/sing/unknown；"
        "target 是操作对象（如 ball、rag）；direction 是 left/right/front/back；"
        "destination 是放置地点。"
        '示例："请捡起你右边的抹布放到桌上" -> '
        '{"action":"carry","target":"rag","direction":"right","destination":"table"}'
    )

    def __init__(self, model: str = "qwen2.5:1.5b"):
        self.model = model

    def parse(self, text: str, speaker_role: Role = Role.STRANGER) -> ParsedCommand:
        try:
            import ollama  # noqa: PLC0415
        except ImportError:
            return ParsedCommand(Intent.UNKNOWN, raw=text)
        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "target": {"type": ["string", "null"]},
                "direction": {"type": ["string", "null"]},
                "destination": {"type": ["string", "null"]},
            },
            "required": ["action"],
        }
        resp = ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": text},
            ],
            format=schema,
            options={"temperature": 0},
        )
        import json

        d = json.loads(resp.message.content)
        try:
            intent = Intent[d.get("action", "unknown").upper()]
        except KeyError:
            intent = Intent.UNKNOWN
        return ParsedCommand(
            intent,
            raw=text,
            target=d.get("target"),
            direction=d.get("direction"),
            destination=d.get("destination"),
        )


class CascadedParser:
    """先规则（毫秒级、覆盖高频指令），未命中再走 LLM（可选）。"""

    def __init__(self, llm_enabled: bool = False, llm_model: str = "qwen2.5:1.5b"):
        self.rule = RuleParser()
        self.llm = OllamaParser(llm_model) if llm_enabled else None

    def parse(self, text: str, speaker_role: Role = Role.STRANGER) -> ParsedCommand:
        cmd = self.rule.parse(text, speaker_role)
        if cmd.intent is Intent.UNKNOWN and self.llm is not None:
            return self.llm.parse(text, speaker_role)
        return cmd
