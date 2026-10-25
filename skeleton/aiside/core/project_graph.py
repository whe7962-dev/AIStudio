"""项目图（DAG）：所有模块读写同一张图，改一个节点只重算下游。

规则（PRD FR1）：
- 节点 = 素材 / 抠图 / 锚点 / 模板 / 生成 / 选优 / 后处理 / 导出。
- 边 = 数据依赖。
- 改参数只把该节点及其下游标为 dirty；上游不动。
- 锚点变更触发全项目重算提示（返回受影响的下游清单）。
- 生成节点用 (prompt, seed, model, anchor) 哈希做缓存。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ids import new_id

# 节点状态机
DIRTY = "dirty"
READY = "ready"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Node:
    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    status: str = DIRTY
    outputs: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "params": self.params,
            "status": self.status,
            "outputs": self.outputs,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(
            id=d["id"],
            type=d["type"],
            params=d.get("params", {}),
            status=d.get("status", DIRTY),
            outputs=d.get("outputs", {}),
            version=d.get("version", 0),
        )


class ProjectGraph:
    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or new_id("proj")
        self.nodes: dict[str, Node] = {}
        # node_id -> set(上游 node_id)
        self.deps: dict[str, set[str]] = {}
        # node_id -> set(下游 node_id)
        self.children: dict[str, set[str]] = {}
        self._undo_stack: list[dict] = []

    # ---- 基本读写 ----
    def add_node(self, type_: str, params: dict | None = None, upstream: list[str] | None = None) -> Node:
        node = Node(id=new_id("node"), type=type_, params=params or {}, status=DIRTY)
        self.nodes[node.id] = node
        self.deps[node.id] = set()
        self.children[node.id] = set()
        for up in upstream or []:
            self.connect(up, node.id)
        self._snapshot()
        return node

    def get(self, node_id: str) -> Node:
        return self.nodes[node_id]

    def connect(self, upstream: str, downstream: str) -> None:
        if upstream not in self.nodes or downstream not in self.nodes:
            raise KeyError("unknown node")
        self.deps[downstream].add(upstream)
        self.children[upstream].add(downstream)
        self.mark_dirty_from(downstream)

    def upstream(self, node_id: str) -> set[str]:
        return set(self.deps.get(node_id, set()))

    def downstream(self, node_id: str) -> set[str]:
        """返回 node_id 的所有下游（含自身）。"""
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.children.get(cur, set()))
        return seen

    def mark_dirty_from(self, node_id: str) -> set[str]:
        affected = self.downstream(node_id)
        for nid in affected:
            self.nodes[nid].status = DIRTY
            self.nodes[nid].version += 1
        return affected

    def invalidate_downstream(self, node_id: str) -> set[str]:
        """把 node_id 的下游（不含自身）标为 dirty；用于节点完成后使下游重算。"""
        affected = self.downstream(node_id) - {node_id}
        for nid in affected:
            self.nodes[nid].status = DIRTY
            self.nodes[nid].version += 1
        return affected

    def set_status(self, node_id: str, status: str, outputs: dict | None = None) -> None:
        node = self.nodes[node_id]
        node.status = status
        if outputs is not None:
            node.outputs = outputs
        node.version += 1

    def update_params(self, node_id: str, params: dict) -> set[str]:
        node = self.nodes[node_id]
        node.params = {**node.params, **params}
        return self.mark_dirty_from(node_id)

    def remove_node(self, node_id: str) -> set[str]:
        affected = self.downstream(node_id)
        for nid in affected:
            self.nodes.pop(nid, None)
            self.deps.pop(nid, None)
            self.children.pop(nid, None)
        # 从所有上游的 children 中移除被删节点
        for children in self.children.values():
            children.discard(node_id)
        # 从所有依赖中移除被删节点引用
        for deps in self.deps.values():
            deps.discard(node_id)
        self._snapshot()
        return affected

    def topological_order(self) -> list[str]:
        """Kahn 拓扑排序，返回可按序执行的节点 id 列表。"""
        indeg = {nid: len(self.deps.get(nid, set())) for nid in self.nodes}
        queue = [nid for nid, d in indeg.items() if d == 0]
        order: list[str] = []
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            for child in self.children.get(cur, set()):
                indeg[child] -= 1
                if indeg[child] == 0:
                    queue.append(child)
        if len(order) != len(self.nodes):
            raise ValueError("项目图存在环")
        return order

    # ---- 缓存键（生成节点） ----
    @staticmethod
    def generation_cache_key(prompt: str, seed: int, model: str, anchor: str) -> str:
        import hashlib
        raw = f"{prompt}|{seed}|{model}|{anchor}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ---- 撤销 ----
    def _snapshot(self) -> None:
        self._undo_stack.append(self.to_dict())

    def undo(self) -> None:
        if not self._undo_stack:
            return
        state = self._undo_stack.pop()
        restored = self.from_dict(state)
        self.nodes = restored.nodes
        self.deps = restored.deps
        self.children = restored.children
        self.project_id = restored.project_id

    # ---- 持久化 ----
    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "deps": {nid: sorted(d) for nid, d in self.deps.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectGraph":
        g = cls(project_id=d["project_id"])
        g.nodes = {nid: Node.from_dict(nd) for nid, nd in d["nodes"].items()}
        g.deps = {nid: set(deps) for nid, deps in d.get("deps", {}).items()}
        g.children = {nid: set() for nid in g.nodes}
        for child, parents in g.deps.items():
            for parent in parents:
                g.children.setdefault(parent, set()).add(child)
        return g

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "ProjectGraph":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
