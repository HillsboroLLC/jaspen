from __future__ import annotations
from typing import List, Optional, Literal, Dict, Set
from datetime import date
from pydantic import BaseModel, Field, field_validator, model_validator

ItemType = Literal["phase", "task"]

class Task(BaseModel):
    """Atomic work item."""
    id: str = Field(min_length=3)
    type: Literal["task"] = "task"
    name: str = Field(min_length=1, max_length=200)
    assignee: Optional[str] = None
    lead_time_days: int = Field(ge=0, default=0)
    depends_on: List[str] = Field(default_factory=list)
    due_date: Optional[date] = None

class Phase(BaseModel):
    """Grouping for tasks."""
    id: str = Field(min_length=3)
    type: Literal["phase"] = "phase"
    name: str = Field(min_length=1, max_length=200)
    children: List[Task] = Field(default_factory=list)

class Milestone(BaseModel):
    id: str
    name: str
    depends_on: List[str] = Field(default_factory=list)

class Risk(BaseModel):
    id: str
    name: str
    mitigation: Optional[str] = None
    impact: Optional[Literal["low", "medium", "high"]] = "medium"
    likelihood: Optional[Literal["low", "medium", "high"]] = "medium"

class Resources(BaseModel):
    team: List[Dict[str, str]] = Field(default_factory=list)
    budget: Dict[str, object] = Field(default_factory=dict)

class Assumption(BaseModel):
    id: str
    text: str

class WBS(BaseModel):
    version: int = 1
    fingerprint: Optional[str] = None
    items: List[Phase] = Field(default_factory=list)
    meta: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_structure(self):
        seen: Set[str] = set()
        task_ids: Set[str] = set()

        for ph in self.items:
            if ph.id in seen:
                raise ValueError(f"duplicate id: {ph.id}")
            seen.add(ph.id)
            for t in ph.children:
                if t.id in seen:
                    raise ValueError(f"duplicate id: {t.id}")
                seen.add(t.id)
                task_ids.add(t.id)

        for ph in self.items:
            for t in ph.children:
                missing = [d for d in t.depends_on if d not in task_ids]
                if missing:
                    raise ValueError(f"task {t.id} depends on unknown ids: {missing}")

        # Cycle detection (networkx if available; else DFS)
        try:
            import networkx as nx  # optional
            g = nx.DiGraph()
            for tid in task_ids:
                g.add_node(tid)
            for ph in self.items:
                for t in ph.children:
                    for d in t.depends_on:
                        g.add_edge(d, t.id)
            if not nx.is_directed_acyclic_graph(g):
                raise ValueError("dependency graph has cycles")
        except Exception:
            graph: Dict[str, List[str]] = {tid: [] for tid in task_ids}
            for ph in self.items:
                for t in ph.children:
                    graph[t.id] = list(t.depends_on)
            visiting: Set[str] = set()
            visited: Set[str] = set()

            def dfs(u: str) -> bool:
                if u in visiting:
                    return True
                if u in visited:
                    return False
                visiting.add(u)
                for v in graph.get(u, []):
                    if dfs(v):
                        return True
                visiting.remove(u)
                visited.add(u)
                return False

            for node in graph:
                if dfs(node):
                    raise ValueError("dependency graph has cycles")
        return self

class Timeline(BaseModel):
    phases: List[Dict[str, str]] = Field(default_factory=list)

class Plan(BaseModel):
    """Single contract for DB JSON columns."""
    wbs: WBS
    timeline: Timeline = Field(default_factory=Timeline)
    milestones: List[Milestone] = Field(default_factory=list)
    risks: List[Risk] = Field(default_factory=list)
    resources: Resources = Field(default_factory=Resources)
    assumptions: List[Assumption] = Field(default_factory=list)
    notes: str = ""  # DB Text

    @field_validator("notes")
    @classmethod
    def _notes_to_str(cls, v):
        return v if isinstance(v, str) else str(v)

    def to_db_payload(self) -> Dict[str, object]:
        return {
            "wbs": self.wbs.model_dump(),
            "timeline": self.timeline.model_dump(),
            "milestones": [m.model_dump() for m in self.milestones],
            "risks": [r.model_dump() for r in self.risks],
            "resources": self.resources.model_dump(),
            "assumptions": [a.model_dump() for a in self.assumptions],
            "notes": self.notes,
        }
