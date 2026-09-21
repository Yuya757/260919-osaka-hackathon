"""Tool-call recorder.

§13.2 requires「悪意あるページによるTool逸脱 0件」but the requirements give no
measurable definition. This records every tool invocation so the evaluation can
assert concrete invariants: which hosts were fetched, which tools ran, and in
what order. Passed explicitly as a parameter — no globals, no contextvars — so
concurrent runs cannot bleed into each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCall:
    name: str
    target: str
    outcome: str = "ok"


@dataclass
class ToolTrajectory:
    calls: list[ToolCall] = field(default_factory=list)

    def record(self, name: str, target: str, outcome: str = "ok") -> None:
        self.calls.append(ToolCall(name=name, target=target, outcome=outcome))

    def names(self) -> set[str]:
        return {call.name for call in self.calls}

    def targets(self, name: str) -> list[str]:
        return [call.target for call in self.calls if call.name == name]

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call.name == name)

    def as_dicts(self) -> list[dict[str, str]]:
        return [
            {"name": c.name, "target": c.target, "outcome": c.outcome} for c in self.calls
        ]
