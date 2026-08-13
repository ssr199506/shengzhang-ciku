"""grow3.probe —— 审计探针（"哪个环节滤掉了什么"）。Step 7 落地。

每级闸门记录 进/出 数 + 差集，输出 JSON 审计日志。差集列表**全量**输出
（本词库最大 7150 词，JSON 完全存得下），方便 grep 单个词在哪级被滤。

结构示例：
    {
      "config": {...},
      "stages": [
        {"gate": "ent", "before": 7150, "after": 5865,
         "removed": ["词1", ...], "removed_count": 1285},
        {"gate": "spe_rescue", "before": 5156, "after": 5186,
         "rescued": ["词X", ...], "rescued_count": 30}
      ],
      "final_count": 5186
    }

Step 1 仅放空壳。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List


@dataclass
class AuditStage:
    gate: str
    before: int
    after: int
    removed: List[str] = field(default_factory=list)
    rescued: List[str] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return len(self.removed)

    @property
    def rescued_count(self) -> int:
        return len(self.rescued)


@dataclass
class AuditLog:
    config: dict = field(default_factory=dict)
    stages: List[AuditStage] = field(default_factory=list)
    final_count: int = 0

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "stages": [
                {
                    "gate": s.gate,
                    "before": s.before,
                    "after": s.after,
                    "removed": s.removed,
                    "removed_count": s.removed_count,
                    "rescued": s.rescued,
                    "rescued_count": s.rescued_count,
                }
                for s in self.stages
            ],
            "final_count": self.final_count,
        }

    def dump(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
