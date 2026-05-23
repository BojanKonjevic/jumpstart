"""Tests for DependencyGraph — the central dependency management module."""

from __future__ import annotations

import pytest

from zenit.core.dependency import DependencyGraph, DependencySpec
from zenit.schema.models import AddonConfig, AddonMeta

# ── helpers ───────────────────────────────────────────────────────────────────


def _a(id: str, requires: list[str] | None = None) -> AddonConfig:
    return AddonConfig(id=id, description="", requires=requires or [])


# ── build ─────────────────────────────────────────────────────────────────────


class TestBuild:
    def test_empty(self) -> None:
        graph = DependencyGraph.build([])
        assert graph.nodes == {}
        assert graph.edges == {}
        assert graph.reverse == {}

    def test_single(self) -> None:
        graph = DependencyGraph.build([_a("redis")])
        assert "redis" in graph.nodes
        assert graph.edges["redis"] == []

    def test_dep_edge(self) -> None:
        graph = DependencyGraph.build([_a("redis"), _a("celery", requires=["redis"])])
        assert graph.edges["celery"] == ["redis"]
        assert graph.reverse["redis"] == ["celery"]

    def test_reverse_is_not_shared(self) -> None:
        graph = DependencyGraph.build([_a("a"), _a("b", requires=["a", "a"])])
        assert graph.reverse["a"] == ["b", "b"]

    def test_multiple_consumers(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["a"]),
            ]
        )
        assert set(graph.reverse["a"]) == {"b", "c"}


# ── closure ────────────────────────────────────────────────────────────────────


class TestClosure:
    def test_empty(self) -> None:
        graph = DependencyGraph.build([])
        assert graph.closure(set()) == set()

    def test_no_deps(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.closure({"a"}) == {"a"}

    def test_direct(self) -> None:
        graph = DependencyGraph.build([_a("a"), _a("b", requires=["a"])])
        assert graph.closure({"b"}) == {"b", "a"}

    def test_transitive(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
            ]
        )
        assert graph.closure({"c"}) == {"c", "b", "a"}

    def test_multiple_roots(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c"),
                _a("d", requires=["c"]),
            ]
        )
        assert graph.closure({"b", "d"}) == {"b", "a", "d", "c"}

    def test_unknown_item_in_input(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.closure({"a", "unknown"}) == {"a", "unknown"}

    def test_keeps_original_set_unchanged(self) -> None:
        graph = DependencyGraph.build([_a("a"), _a("b", requires=["a"])])
        selected = {"b"}
        result = graph.closure(selected)
        assert selected == {"b"}
        assert result == {"b", "a"}

    def test_cycle_does_not_infinite_loop(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["a"]),
            ]
        )
        assert graph.closure({"a"}) == {"a", "b"}


# ── dependents ─────────────────────────────────────────────────────────────────


class TestDependents:
    def test_no_dependents(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.dependents("a") == set()

    def test_direct(self) -> None:
        graph = DependencyGraph.build([_a("a"), _a("b", requires=["a"])])
        assert graph.dependents("a") == {"b"}

    def test_transitive(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
            ]
        )
        assert graph.dependents("a") == {"b", "c"}

    def test_fork(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["a"]),
            ]
        )
        assert graph.dependents("a") == {"b", "c"}

    def test_unknown_addon(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.dependents("unknown") == set()

    def test_cycle_does_not_infinite_loop(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["a"]),
            ]
        )
        assert graph.dependents("a") == {"b"}


# ── chain ──────────────────────────────────────────────────────────────────────


class TestChain:
    def test_root_directly(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.chain("a") == [["a"]]

    def test_single_path(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
            ]
        )
        assert graph.chain("b") == [["a", "b"]]

    def test_deep_path(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
            ]
        )
        assert graph.chain("c") == [["a", "b", "c"]]

    def test_multiple_paths(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b"),
                _a("c", requires=["a", "b"]),
            ]
        )
        chains = graph.chain("c")
        assert ["a", "c"] in chains
        assert ["b", "c"] in chains

    def test_unknown_addon(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.chain("unknown") == []

    def test_addon_with_multiple_ancestors(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a1"),
                _a("a2"),
                _a("b", requires=["a1"]),
                _a("c", requires=["a2", "b"]),
            ]
        )
        chains = graph.chain("c")
        assert ["a1", "b", "c"] in chains
        assert ["a2", "c"] in chains

    def test_cycle_does_not_infinite_loop(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["a"]),
            ]
        )
        assert graph.chain("a") == []


# ── tsort ──────────────────────────────────────────────────────────────────────


class TestTsort:
    def test_empty(self) -> None:
        graph = DependencyGraph.build([])
        assert graph.tsort(set()) == []

    def test_single(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.tsort({"a"}) == ["a"]

    def test_dep_before_consumer(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
            ]
        )
        result = graph.tsort({"a", "b"})
        assert result.index("a") < result.index("b")
        assert set(result) == {"a", "b"}

    def test_chain(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
            ]
        )
        result = graph.tsort({"a", "b", "c"})
        assert result.index("a") < result.index("b") < result.index("c")
        assert set(result) == {"a", "b", "c"}

    def test_fork(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["a"]),
            ]
        )
        result = graph.tsort({"a", "b", "c"})
        assert result.index("a") < result.index("b")
        assert result.index("a") < result.index("c")
        assert set(result) == {"a", "b", "c"}

    def test_merge(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b"),
                _a("c", requires=["a", "b"]),
            ]
        )
        result = graph.tsort({"a", "b", "c"})
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("c")
        assert set(result) == {"a", "b", "c"}

    def test_diamond(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["a"]),
                _a("d", requires=["b", "c"]),
            ]
        )
        result = graph.tsort({"a", "b", "c", "d"})
        assert result.index("a") < result.index("b")
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("d")
        assert result.index("c") < result.index("d")
        assert set(result) == {"a", "b", "c", "d"}

    def test_subset_ignores_missing_deps(self) -> None:
        """Nodes not in the selected set are ignored (no error)."""
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
            ]
        )
        result = graph.tsort({"b", "c"})
        assert result.index("b") < result.index("c")
        assert set(result) == {"b", "c"}

    def test_unknown_items_ignored(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.tsort({"unknown"}) == []

    def test_disconnected(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b"),
                _a("c"),
            ]
        )
        result = graph.tsort({"a", "b", "c"})
        assert set(result) == {"a", "b", "c"}

    def test_cycle_returns_partial_result(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["a"]),
            ]
        )
        # Cycle means neither can be sorted first, but Kahn's will
        # process what it can (nothing with 0 in-degree).
        result = graph.tsort({"a", "b"})
        # Neither has 0 in-degree, so result is empty
        assert result == []


# ── tsort_reverse ──────────────────────────────────────────────────────────────


class TestTsortReverse:
    def test_reverse_order(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
            ]
        )
        result = graph.tsort_reverse({"a", "b", "c"})
        assert result.index("c") < result.index("b") < result.index("a")
        assert set(result) == {"a", "b", "c"}

    def test_empty(self) -> None:
        graph = DependencyGraph.build([])
        assert graph.tsort_reverse(set()) == []

    def test_single(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.tsort_reverse({"a"}) == ["a"]


# ── validate ───────────────────────────────────────────────────────────────────


class TestValidate:
    def test_empty_graph(self) -> None:
        graph = DependencyGraph.build([])
        assert graph.validate() == []

    def test_valid_single(self) -> None:
        graph = DependencyGraph.build([_a("a")])
        assert graph.validate() == []

    def test_valid_chain(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
            ]
        )
        assert graph.validate() == []

    def test_missing_dep(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["nonexistent"]),
            ]
        )
        errors = graph.validate()
        assert len(errors) == 1
        assert errors[0].type == "missing_dep"
        assert "b" in errors[0].message
        assert "nonexistent" in errors[0].message
        assert errors[0].addon_ids == ["b", "nonexistent"]

    def test_missing_dep_among_valid(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b", "c"]),
                _a("b"),
            ]
        )
        errors = graph.validate()
        assert len(errors) == 1
        assert errors[0].type == "missing_dep"
        assert "c" in errors[0].message

    def test_cycle_direct(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["a"]),
            ]
        )
        errors = graph.validate()
        assert any(e.type == "cycle" for e in errors)

    def test_cycle_indirect(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["c"]),
                _a("c", requires=["a"]),
            ]
        )
        errors = graph.validate()
        assert any(e.type == "cycle" for e in errors)

    def test_cycle_self(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["a"]),
            ]
        )
        errors = graph.validate()
        assert any(e.type == "cycle" for e in errors)

    def test_both_cycle_and_missing(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a", requires=["b"]),
                _a("b", requires=["a", "missing"]),
            ]
        )
        errors = graph.validate()
        types = {e.type for e in errors}
        assert "cycle" in types
        assert "missing_dep" in types

    def test_no_false_positive_for_tree(self) -> None:
        graph = DependencyGraph.build(
            [
                _a("a"),
                _a("b", requires=["a"]),
                _a("c", requires=["b"]),
                _a("d", requires=["a"]),
            ]
        )
        assert graph.validate() == []


# ── DependencySpec ─────────────────────────────────────────────────────────────


class TestDependencySpec:
    def test_default_optional(self) -> None:
        spec = DependencySpec(id="redis")
        assert spec.optional is False

    def test_explicit_optional(self) -> None:
        spec = DependencySpec(id="redis", optional=True)
        assert spec.optional is True

    def test_frozen(self) -> None:
        spec = DependencySpec(id="redis")
        with pytest.raises(AttributeError):
            spec.id = "other"  # type: ignore[misc]


# ── build_from_meta ─────────────────────────────────────────────────────────────


class TestBuildFromMeta:
    def _m(self, id: str, requires: list[str] | None = None) -> AddonMeta:
        return AddonMeta(id=id, description="", requires=requires or [])

    def test_empty(self) -> None:
        graph = DependencyGraph.build_from_meta([])
        assert graph.nodes == {}
        assert graph.edges == {}
        assert graph.reverse == {}

    def test_single(self) -> None:
        graph = DependencyGraph.build_from_meta([self._m("redis")])
        assert "redis" in graph.nodes
        assert graph.edges["redis"] == []

    def test_dep_edge(self) -> None:
        graph = DependencyGraph.build_from_meta(
            [self._m("redis"), self._m("celery", requires=["redis"])]
        )
        assert graph.edges["celery"] == ["redis"]
        assert graph.reverse["redis"] == ["celery"]

    def test_behaves_like_build(self) -> None:
        """build_from_meta and build produce identical graphs for same data."""
        graph_a = DependencyGraph.build(
            [
                AddonConfig(id="redis", description=""),
                AddonConfig(id="celery", description="", requires=["redis"]),
            ]
        )
        graph_b = DependencyGraph.build_from_meta(
            [self._m("redis"), self._m("celery", requires=["redis"])]
        )
        assert graph_a.nodes == graph_b.nodes
        assert graph_a.edges == graph_b.edges
        assert graph_a.reverse == graph_b.reverse

    def test_validate_on_meta_graph(self) -> None:
        graph = DependencyGraph.build_from_meta(
            [self._m("a"), self._m("b", requires=["missing"])]
        )
        errors = graph.validate()
        assert any(e.type == "missing_dep" for e in errors)
        assert any("missing" in e.message for e in errors)
