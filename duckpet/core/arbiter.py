"""优先级仲裁器：实现"主人 > 家人 > 客人朋友 > 陌生人"的呼叫/指令裁决规则。

规则（来自需求 4/5）：
- 没有任务时，任何人呼叫 -> ENGAGE（转头/转身找呼叫者，看脸等指令）
- 有任务时，更高级别的人呼叫 -> PREEMPT（放下手头工作，去找呼叫者）
- 同级或更低级别的人呼叫 -> ACK_ONLY（朝呼叫方向转头礼貌回应，继续手头任务）
- 指令同理：更高级别 -> 立即执行（抢占）；同级/更低 -> 排队，等当前任务完成后执行
- 跟随中：更高级别的人呼叫 -> 直接改跟随更高级别的人（FOLLOW_SWITCH，需求 5）
- 能力门控：跟随仅主人/家人；改名/登记关系仅家人及以上
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .events import CallEvent, Intent, ParsedCommand
from .roles import FOLLOW_MIN_ROLE, MANAGE_MIN_ROLE, Role


class Decision(Enum):
    ENGAGE = auto()         # 去找呼叫者并等待指令
    PREEMPT = auto()        # 放下当前任务，去找呼叫者
    ACK_ONLY = auto()       # 转头礼貌回应，继续当前任务
    EXECUTE = auto()        # 立即执行指令
    QUEUE = auto()          # 排队等待
    REJECT = auto()         # 权限不足，拒绝
    FOLLOW_SWITCH = auto()  # 跟随中直接切换跟随目标


@dataclass
class TaskContext:
    active_name: str | None = None       # 当前行为名（None = 空闲乱逛）
    active_role: Role = Role.STRANGER    # 当前任务是谁发的
    following: bool = False
    follow_target_role: Role = Role.STRANGER


class Arbiter:
    def decide_call(self, call: CallEvent, ctx: TaskContext) -> Decision:
        if ctx.following and call.role > ctx.follow_target_role:
            return Decision.FOLLOW_SWITCH
        if ctx.active_name is None:
            return Decision.ENGAGE
        if call.role > ctx.active_role:
            return Decision.PREEMPT
        return Decision.ACK_ONLY

    def decide_command(self, cmd: ParsedCommand, role: Role, ctx: TaskContext) -> Decision:
        if cmd.intent is Intent.FOLLOW and role < FOLLOW_MIN_ROLE:
            return Decision.REJECT
        if cmd.intent is Intent.SET_NAME and role < MANAGE_MIN_ROLE:
            return Decision.REJECT
        if cmd.intent is Intent.STOP:
            # 停下当前任务：发令人级别不低于当前任务级别才生效
            if ctx.active_name is not None and role >= ctx.active_role:
                return Decision.EXECUTE
            return Decision.ACK_ONLY
        if cmd.intent is Intent.STAND_UP:
            return Decision.EXECUTE   # 坐着时"站起来"不能排队（坐行为不会自己结束）
        if ctx.active_name is None:
            return Decision.EXECUTE
        if role > ctx.active_role:
            return Decision.EXECUTE  # 抢占
        return Decision.QUEUE
