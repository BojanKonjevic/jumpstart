"""Central dependency graph for addon dependency management.

Provides topological sort, transitive closure, cycle detection,
and reverse-dependency queries - all in one place instead of
ad-hoc ``requires_map`` dicts rebuilt in 6+ locations.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from zenit.schema.models import AddonConfig, AddonMeta


@dataclass(frozen=True)
class DependencySpec:
    """A single node in the dependency graph.

    ``optional`` indicates a soft dependency - the addon will be
    auto-selected when its consumer is chosen, but won't block removal.
    """

    id: str
    optional: bool = False


@dataclass
class DependencyError:
    """A validation error found when checking the graph structure."""

    type: str  # "cycle" or "missing_dep"
    message: str
    addon_ids: list[str]


@dataclass
class DependencyGraph:
    """Directed graph of addon dependencies.

    * ``edges``: addon_id → list of addons it **requires** (its dependencies).
    * ``reverse``: addon_id → list of addons that **require it** (its consumers).
    """

    nodes: dict[str, DependencySpec] = field(default_factory=dict)
    edges: dict[str, list[str]] = field(default_factory=dict)
    reverse: dict[str, list[str]] = field(default_factory=dict)

    # ── Construction ────────────────────────────────────────────────────────

    @staticmethod
    def build(addons: list[AddonConfig]) -> DependencyGraph:
        """Construct a ``DependencyGraph`` from a list of ``AddonConfig`` objects.

        Every addon becomes a node.  Each addon's ``requires`` list becomes
        its outgoing edges.  The ``reverse`` map is built automatically.
        """
        return DependencyGraph._build(
            [(a.id, a.requires) for a in addons],
            {a.id for a in addons},
        )

    @staticmethod
    def build_from_meta(addons: list[AddonMeta]) -> DependencyGraph:
        """Construct a ``DependencyGraph`` from a list of ``AddonMeta`` objects.

        Same structure as ``build()`` but uses lightweight metadata - no exec
        of addon.py files required.
        """
        return DependencyGraph._build(
            [(a.id, a.requires) for a in addons],
            {a.id for a in addons},
        )

    @staticmethod
    def _build(
        items: list[tuple[str, list[str]]],
        node_ids: set[str],
    ) -> DependencyGraph:
        nodes: dict[str, DependencySpec] = {}
        edges: dict[str, list[str]] = {}
        reverse: dict[str, list[str]] = {}

        for addon_id, requires in items:
            nodes[addon_id] = DependencySpec(id=addon_id)
            edges[addon_id] = list(requires)
            for req in requires:
                reverse.setdefault(req, []).append(addon_id)

        return DependencyGraph(nodes=nodes, edges=edges, reverse=reverse)

    # ── Queries ─────────────────────────────────────────────────────────────

    def closure(self, selected: set[str]) -> set[str]:
        """Transitive closure - all dependencies of *selected*, including themselves.

        For any addon in *selected*, every addon it requires (directly or
        transitively) is included in the result.
        """
        result = set(selected)
        queue = list(selected)
        while queue:
            addon_id = queue.pop()
            for dep in self.edges.get(addon_id, []):
                if dep not in result:
                    result.add(dep)
                    queue.append(dep)
        return result

    def dependents(self, addon_id: str) -> set[str]:
        """All transitive consumers of *addon_id*.

        Returns every addon that depends on *addon_id*, directly or transitively.
        The query addon itself is never included in the result.
        """
        result: set[str] = set()
        visited: set[str] = {addon_id}
        queue = list(self.reverse.get(addon_id, []))
        while queue:
            consumer = queue.pop()
            if consumer not in visited:
                visited.add(consumer)
                result.add(consumer)
                queue.extend(self.reverse.get(consumer, []))
        return result

    def chain(self, addon_id: str) -> list[list[str]]:
        """All dependency paths from roots → *addon_id*.

        Each path is a list of addon IDs starting at a root (zero deps)
        and ending at *addon_id*.  Useful for human-readable error messages.
        """
        if addon_id not in self.nodes:
            return []

        roots = [n for n, deps in self.edges.items() if not deps]
        paths: list[list[str]] = []

        def _dfs(current: str, target: str, path: list[str]) -> None:
            if current == target:
                paths.append(list(path))
                return
            for consumer in self.reverse.get(current, []):
                if consumer not in path:
                    path.append(consumer)
                    _dfs(consumer, target, path)
                    path.pop()

        for root in roots:
            if root == addon_id:
                paths.append([root])
            else:
                _dfs(root, addon_id, [root])

        return paths

    # ── Ordering ────────────────────────────────────────────────────────────

    def tsort(self, selected: set[str]) -> list[str]:
        """Topological sort - dependencies before consumers (apply order).

        Only nodes present in *selected* and in the graph are included.
        Nodes not in the graph are silently ignored.
        """
        valid = selected & set(self.nodes.keys())
        if not valid:
            return []

        in_degree: dict[str, int] = {}
        for node in valid:
            deps_in_set = [d for d in self.edges.get(node, []) if d in valid]
            in_degree[node] = len(deps_in_set)

        queue = deque(node for node in valid if in_degree[node] == 0)
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for consumer in self.reverse.get(node, []):
                if consumer in valid:
                    in_degree[consumer] -= 1
                    if in_degree[consumer] == 0:
                        queue.append(consumer)

        return result

    def tsort_reverse(self, selected: set[str]) -> list[str]:
        """Reverse topological sort - consumers before dependencies (remove order)."""
        return list(reversed(self.tsort(selected)))

    # ── Validation ──────────────────────────────────────────────────────────

    def validate(self) -> list[DependencyError]:
        """Check the graph for missing deps and cycles.

        Returns a list of ``DependencyError`` objects (empty = valid).
        Missing deps are reported when an addon references another addon
        that is not registered.  Cycles are detected via DFS.
        """
        errors: list[DependencyError] = []

        for addon_id, deps in self.edges.items():
            for dep in deps:
                if dep not in self.nodes:
                    errors.append(
                        DependencyError(
                            type="missing_dep",
                            message=f"'{addon_id}' requires '{dep}' which is not a known addon",
                            addon_ids=[addon_id, dep],
                        )
                    )

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {node: WHITE for node in self.nodes}

        def _dfs(node: str, path: list[str]) -> None:
            color[node] = GRAY
            path.append(node)
            for dep in self.edges.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    errors.append(
                        DependencyError(
                            type="cycle",
                            message=f"Cycle detected: {' → '.join(cycle)}",
                            addon_ids=list(dict.fromkeys(cycle)),
                        )
                    )
                elif color[dep] == WHITE:
                    _dfs(dep, path)
            path.pop()
            color[node] = BLACK

        for node in self.nodes:
            if color[node] == WHITE:
                _dfs(node, [])

        return errors
