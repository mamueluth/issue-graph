# issue-graph

A GitHub repo's open issues as a graph: which issue blocks which (red) and
which has which sub-issues (blue, dashed), grouped by milestone. GitHub
itself shows these links only per issue, in the sidebar.

```sh
issue-graph                          # window for the repo of the current directory
issue-graph OWNER/REPO               # window for OWNER/REPO
issue-graph OWNER/REPO -o graph.png  # render to .png, .svg or .dot instead; needs no display
issue-graph --links blocks           # only that kind of link (blocks, sub-issues, both)
```

In the window: click an issue to read it, drag to pan, wheel to zoom. In
the issue pane, the blocked-by/blocks/sub-issue links jump to that issue;
"open on GitHub" opens the browser. In an SVG, every issue links to GitHub.

## How it works

`gh api graphql` fetches the open issues. Graphviz's `dot` lays the graph
out (`dot -Tjson`), and Qt (PySide6) draws its drawing operations in a
`QGraphicsScene`, which gives zoom, pan and clicking. Files (`-o`) come
straight from `dot`, without Qt.

Only open issues of the repo are drawn: links to closed issues or other
repos are left out. Only GitHub's relationship fields are links; "depends
on #53" written in an issue's text is not.

## Install

```sh
uv tool install --editable .   # puts issue-graph on PATH; code edits apply at once
```

Needs `gh` (logged in, read access to the repo's issues), Graphviz (`dot`),
and for the window a display; Qt's X11 libraries on Linux (see the `gui`
group in the container's `packages.yaml`). github.com only: the blocked-by
and sub-issue fields.
