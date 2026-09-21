from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .roles import Role


@dataclass
class Person:
    name: str
    role: Role
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    voice_embeddings: list[list[float]] = field(default_factory=list)
    face_embeddings: list[list[float]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": int(self.role),
            "voice_embeddings": self.voice_embeddings,
            "face_embeddings": self.face_embeddings,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Person":
        return cls(
            id=d["id"],
            name=d["name"],
            role=Role(d["role"]),
            voice_embeddings=d.get("voice_embeddings", []),
            face_embeddings=d.get("face_embeddings", []),
            created_at=d.get("created_at", time.time()),
        )


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class PersonRegistry:
    """主人/家人/客人档案库：声纹 + 人脸 embedding，JSON 持久化。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._people: dict[str, Person] = {}
        if self.path.exists():
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                p = Person.from_json(d)
                self._people[p.id] = p

    def __iter__(self):
        return iter(self._people.values())

    def __len__(self) -> int:
        return len(self._people)

    @property
    def owner(self) -> Person | None:
        for p in self._people.values():
            if p.role == Role.OWNER:
                return p
        return None

    def add(self, name: str, role: Role) -> Person:
        existing = self.find_by_name(name)
        if existing:
            existing.role = max(existing.role, role)
            self.save()
            return existing
        if role == Role.OWNER and self.owner is not None:
            raise ValueError(f"已经有主人了（{self.owner.name}），请先移除再设置")
        p = Person(name=name, role=role)
        self._people[p.id] = p
        self.save()
        return p

    def remove(self, name: str) -> bool:
        p = self.find_by_name(name)
        if p is None:
            return False
        del self._people[p.id]
        self.save()
        return True

    def find_by_name(self, name: str) -> Person | None:
        for p in self._people.values():
            if p.name == name:
                return p
        return None

    def add_voice(self, person: Person, embedding: list[float]) -> None:
        person.voice_embeddings.append(list(embedding))
        self.save()

    def add_face(self, person: Person, embedding: list[float]) -> None:
        person.face_embeddings.append(list(embedding))
        self.save()

    def match_voice(self, embedding: list[float], threshold: float) -> tuple[Person | None, float]:
        return self._match(embedding, threshold, "voice_embeddings")

    def match_face(self, embedding: list[float], threshold: float) -> tuple[Person | None, float]:
        return self._match(embedding, threshold, "face_embeddings")

    def _match(self, vec, threshold, attr) -> tuple[Person | None, float]:
        best: Person | None = None
        best_score = 0.0
        for p in self._people.values():
            for ref in getattr(p, attr):
                score = cosine(vec, ref)
                if score > best_score:
                    best, best_score = p, score
        if best is not None and best_score >= threshold:
            return best, best_score
        return None, best_score

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_json() for p in self._people.values()]
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
