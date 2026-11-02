# issue-graph

A GitHub repo's open issues as a graph: which issue blocks which (red) and
which has which sub-issues (blue, dashed), grouped by milestone. GitHub
itself shows these links only per issue, in the sidebar.

## Install

```sh
uv tool install git+https://github.com/mamueluth/issue-graph
```

Needs `gh` (logged in, read access to the repo's issues) and Graphviz
(`dot`). github.com only: the blocked-by and sub-issue fields. The window
needs a display and, on Linux, Qt's display libraries: a desktop has them, a
bare container does not. On Debian/Ubuntu:

```sh
sudo apt-get install -y --no-install-recommends graphviz fonts-dejavu-core \
  libegl1 libgl1 libfontconfig1 libdbus-1-3 libx11-xcb1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xkb1
```

Working on issue-graph itself: `uv tool install --editable .` in a clone,
so code edits apply at once.

## Use

```sh
issue-graph                          # window for the repo of the current directory
issue-graph OWNER/REPO               # window for OWNER/REPO
issue-graph OWNER/REPO -o graph.png  # render to .png, .svg or .dot instead; needs no display
issue-graph --links blocks           # only that kind of link (blocks, sub-issues, both)
```

In the window: click an issue to read it, drag to pan, wheel to zoom. In
the issue pane, the blocked-by/blocks/sub-issue links jump to that issue;
"open on GitHub" opens the browser. Refresh (F5) fetches the issues again
and keeps the selected issue selected. In an SVG, every issue links to
GitHub.

## How it works

`gh api graphql` fetches the open issues. Graphviz's `dot` lays the graph
out (`dot -Tjson`), and Qt (PySide6) draws its drawing operations in a
`QGraphicsScene`, which gives zoom, pan and clicking. Files (`-o`) come
straight from `dot`, without Qt.

Only open issues of the repo are drawn: links to closed issues or other
repos are left out. Only GitHub's relationship fields are links; "depends
on #53" written in an issue's text is not.
