from __future__ import annotations

from enum import IntEnum


class Role(IntEnum):
    """权限等级，数值越大优先级越高：主人 > 家人 > 客人朋友 > 陌生人。"""

    STRANGER = 1
    GUEST = 2
    FAMILY = 3
    OWNER = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def from_label(cls, text: str) -> "Role | None":
        return _FROM_LABEL.get(text.strip())


_LABELS = {
    Role.STRANGER: "陌生人",
    Role.GUEST: "客人朋友",
    Role.FAMILY: "家人",
    Role.OWNER: "主人",
}

_FROM_LABEL = {
    "陌生人": Role.STRANGER,
    "客人": Role.GUEST,
    "朋友": Role.GUEST,
    "客人朋友": Role.GUEST,
    "家人": Role.FAMILY,
    "亲人": Role.FAMILY,
    "主人": Role.OWNER,
}

# 跟随功能只对主人和家人开放（客人、陌生人不可指挥跟随）
FOLLOW_MIN_ROLE = Role.FAMILY
# 改名、登记家人等管理类指令的最低权限
MANAGE_MIN_ROLE = Role.FAMILY
