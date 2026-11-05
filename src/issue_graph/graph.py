"""Issues as a Graphviz graph: the DOT text, and dot to lay it out or render it.

  A --blocks--> B          A blocks B            (solid, red)
  P --has sub-issue--> C   C is a sub-issue of P (dashed, blue)

Issues are grouped by milestone.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from itertools import groupby
from typing import Literal

from .github import Issue

Kind = Literal["blocks", "sub-issues"]
LINKS = ("blocks", "sub-issues", "both")


@dataclass(frozen=True)
class Edge:
    tail: int
    head: int
    kind: Kind


@dataclass(frozen=True)
class EdgeStyle:
    label: str
    color: str
    style: str


STYLES: dict[Kind, EdgeStyle] = {
    "blocks": EdgeStyle("blocks", "#cf222e", "solid"),
    "sub-issues": EdgeStyle("has sub-issue", "#0969da", "dashed"),
}


class GraphvizError(RuntimeError):
    """dot failed; the message is Graphviz's own."""


def edges(issues: list[Issue], links: str | None = None) -> list[Edge]:
    """The links between these issues, not to others; links = "blocks" or "sub-issues" keeps only that kind."""
    numbers = {i.number for i in issues}
    out: list[Edge] = []
    for issue in issues:
        out += [Edge(b, issue.number, "blocks") for b in issue.blocked_by]
        if issue.parent is not None:
            out.append(Edge(issue.parent, issue.number, "sub-issues"))
    return [e for e in out if e.tail in numbers and (links in (None, "both") or e.kind == links)]


def wrap(text: str, width: int = 30) -> list[str]:
    """dot does not wrap labels: break text into lines of about width characters."""
    lines = [""]
    for word in filter(None, text.split(" ")):
        if not lines[-1]:
            lines[-1] = word
        elif len(lines[-1]) + 1 + len(word) > width:
            lines.append(word)
        else:
            lines[-1] += " " + word
    return lines


def quote(lines: list[str]) -> str:
    """A quoted DOT string: backslashes and quotes escaped, lines joined by \\n."""
    escaped = (line.replace("\\", "\\\\").replace('"', '\\"') for line in lines)
    return '"' + "\\n".join(escaped) + '"'


def node(issue: Issue) -> str:
    return f"i{issue.number} [label={quote(wrap(f'#{issue.number} {issue.title}'))} URL={quote([issue.url])}]"


def rows(group: list[Issue], linked: set[int]) -> list[str]:
    """dot stacks a group's unlinked issues in one column; invisible edges set them in rows of three instead."""
    free = [f"i{i.number}" for i in group if i.number not in linked]
    return [" -> ".join(free[k:k + 3]) + " [style=invis]" for k in range(0, len(free), 3) if len(free[k:k + 3]) > 1]


def to_dot(issues: list[Issue], links: str | None = None) -> str:
    """DOT for every issue, or with links set, for that kind of link and the issues it connects."""
    es = edges(issues, links)
    linked = {n for e in es for n in (e.tail, e.head)}
    shown = [i for i in issues if links is None or i.number in linked]
    out = [
        "digraph issues {",
        "  rankdir=LR",
        '  node [shape=box style="rounded,filled" fillcolor="#ececff" color="#9370db"'
        ' fontname="Helvetica" fontsize=11]',
        '  edge [fontname="Helvetica" fontsize=10]',
    ]

    def milestone(i: Issue) -> int:
        return i.milestone.number if i.milestone else 0

    # sorted() is stable: issues keep GitHub's order inside their milestone.
    for _, members in groupby(sorted(shown, key=milestone), key=milestone):
        group = list(members)
        m = group[0].milestone
        if m is None:
            out += ["  " + line for line in [*map(node, group), *rows(group, linked)]]
            continue
        out += [
            f"  subgraph cluster_m{m.number} {{",
            f'    label={quote([m.title])} style=filled fillcolor="#ffffde" color="#aaaa33" fontname="Helvetica"',
            *("    " + line for line in [*map(node, group), *rows(group, linked)]),
            "  }",
        ]
    for e in es:
        s = STYLES[e.kind]
        out.append(f'  i{e.tail} -> i{e.head}'
                   f' [label="{s.label}" color="{s.color}" fontcolor="{s.color}" style={s.style}]')
    out.append("}")
    return "\n".join(out) + "\n"


def render(dot: str, fmt: str) -> bytes:
    """dot's output for the DOT text in format fmt (png, svg, json, ...): Graphviz bundled, see dot.py.

    -I: the child neither imports from the working directory nor reads PYTHON* variables.
    """
    done = subprocess.run([sys.executable, "-I", "-m", "issue_graph.dot", fmt], input=dot.encode(),
                          capture_output=True)
    if done.returncode != 0:
        raise GraphvizError(done.stderr.decode().strip() or f"dot -T{fmt} failed")
    return done.stdout


def layout(dot: str) -> dict:
    """dot's layout of the DOT text: positions plus drawing operations (xdot) as JSON."""
    return json.loads(render(dot, "json"))
