"""Graphviz comes bundled with pygraphviz: the window's layout and -o's files need no Graphviz install."""

import pytest

from issue_graph import graph
from issue_graph.github import Issue, Milestone


def issue(number, milestone=None, parent=None, blocked_by=()):
    return Issue(number=number, title=f"Issue {number}", body="", url=f"https://github.com/o/r/issues/{number}",
                 author="ann", type=None, milestone=Milestone(1, milestone) if milestone else None, labels=(),
                 parent=parent, blocked_by=blocked_by)


DOT = graph.to_dot([issue(1, milestone="v1"), issue(2, parent=1, blocked_by=(1,))])


def test_layout_has_what_the_window_draws():
    layout = graph.layout(DOT)
    assert layout["_subgraph_cnt"] == 1  # the milestone box
    nodes = layout["objects"][layout["_subgraph_cnt"]:]
    assert sorted(n["name"] for n in nodes) == ["i1", "i2"]
    assert all(n["_draw_"] and n["_ldraw_"] for n in nodes)
    assert len(layout["edges"]) == 2  # blocks and has sub-issue


def test_files():
    assert graph.render(DOT, "png").startswith(b"\x89PNG")
    assert b'href="https://github.com/o/r/issues/2"' in graph.render(DOT, "svg")


def test_a_graphviz_error_is_graphvizs_message():
    with pytest.raises(graph.GraphvizError, match="syntax error"):
        graph.render("digraph { a -> }", "json")
