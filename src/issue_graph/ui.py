"""The window: the issue graph, laid out by Graphviz and drawn by Qt, next to the selected issue."""

import re
import sys
import threading
from datetime import datetime

from PySide6.QtCore import QPointF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath,
                           QPen, QPolygonF, QWheelEvent)
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsItemGroup, QGraphicsPathItem,
                               QGraphicsPolygonItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QMainWindow, QSplitter, QTextBrowser)

from . import github, graph
from .github import Issue

PEN_STYLES = {"solid": Qt.PenStyle.SolidLine, "dashed": Qt.PenStyle.DashLine, "dotted": Qt.PenStyle.DotLine}


def color(spec: str) -> QColor:
    """A Graphviz color: a name or #RRGGBB[AA]. Qt reads 8 hex digits as #AARRGGBB, so alpha is set apart."""
    if spec.startswith("#") and len(spec) == 9:
        c = QColor(spec[:7])
        c.setAlpha(int(spec[7:], 16))
        return c
    return QColor(spec)


def draw(ops: list[dict]) -> list[QGraphicsItem]:
    """Qt items for Graphviz drawing operations (xdot, as dot -Tjson lists them).

    Graphviz's y axis points up, Qt's down: y is negated. Only the operations
    issue-graph's graphs use are drawn; others (ellipses, images, gradients) are skipped.
    """
    pen, fill, font, visible = QPen(QColor("black"), 1), QColor(), QFont(), True
    items: list[QGraphicsItem] = []
    for op in ops:
        kind = op["op"]
        points = [QPointF(x, -y) for x, y in op.get("points", [])]
        if kind == "c":
            pen.setColor(color(op["color"]))
        elif kind == "C":
            fill = color(op["color"])
        elif kind == "S":
            visible = op["style"] != "invis"
            pen.setStyle(PEN_STYLES.get(op["style"], pen.style()))
            pen.setWidthF(2 if op["style"] == "bold" else pen.widthF())
        elif kind == "F":
            font = QFont(op["face"])
            font.setPixelSize(max(1, round(op["size"])))  # Graphviz sizes are points, one point per scene unit
        elif not visible:
            continue
        elif kind == "T":
            items.append(text(op, font, pen.color()))
        elif kind in "pP":
            shape = QGraphicsPolygonItem(QPolygonF(points))
            shape.setPen(pen)
            if kind == "P":
                shape.setBrush(fill)
            items.append(shape)
        elif kind in "bB":
            path = QPainterPath(points[0])
            for k in range(1, len(points) - 2, 3):
                path.cubicTo(points[k], points[k + 1], points[k + 2])
            curve = QGraphicsPathItem(path)
            curve.setPen(pen)
            # A closed curve is a shape (a rounded box) and gets filled, an open one is an edge.
            # The letter can't tell: Graphviz 2.43's JSON swaps b (filled) and B (unfilled).
            if points[0] == points[-1] and fill.isValid():
                curve.setBrush(fill)
            items.append(curve)
    return items


def text(op: dict, font: QFont, ink: QColor) -> QGraphicsSimpleTextItem:
    """A text operation: pt is the baseline's left end, middle or right end, per align."""
    item = QGraphicsSimpleTextItem(op["text"])
    item.setFont(font)
    item.setBrush(ink)
    metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(op["text"])
    x, y = op["pt"]
    item.setPos(x - {"l": 0, "c": width / 2, "r": width}[op["align"]], -y - metrics.ascent())
    return item


def build(scene: QGraphicsScene, layout: dict) -> dict[int, QGraphicsItemGroup]:
    """Draw dot's layout: milestone boxes, then links, then the issues on top. Returns the issues' items by number."""
    objects = layout.get("objects", [])
    subgraphs = layout.get("_subgraph_cnt", 0)  # objects lists the subgraphs first, then the nodes
    for cluster in objects[:subgraphs]:
        for item in draw(cluster.get("_draw_", []) + cluster.get("_ldraw_", [])):
            scene.addItem(item)
    for edge in layout.get("edges", []):
        for key in ("_draw_", "_hdraw_", "_tdraw_", "_ldraw_"):
            for item in draw(edge.get(key, [])):
                scene.addItem(item)
    nodes = {}
    for obj in objects[subgraphs:]:
        items = draw(obj.get("_draw_", []) + obj.get("_ldraw_", []))
        for item in items:
            scene.addItem(item)
        group = scene.createItemGroup(items)
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        group.setCursor(Qt.CursorShape.PointingHandCursor)
        number = int(obj["name"].removeprefix("i"))
        group.setData(0, number)
        nodes[number] = group
    return nodes


def escape(text: str) -> str:
    """Text for Markdown: every ASCII punctuation character may be backslash-escaped."""
    return re.sub(r"([\\`*_\[\]{}()#+\-.!<>|~])", r"\\\1", text)


def markdown(issue: Issue, links: list[graph.Edge], issues: dict[int, Issue]) -> str:
    """The detail pane: title, facts, links to related issues (issue:N jumps there), then the description."""
    def refs(numbers: list[int]) -> str:
        return ", ".join(f"[#{n} {escape(issues[n].title)}](issue:{n})" for n in numbers)

    facts = [f"Type: {issue.type}" if issue.type else "",
             f"Milestone: {escape(issue.milestone.title)}" if issue.milestone else "",
             "Labels: " + ", ".join(escape(label.name) for label in issue.labels) if issue.labels else ""]
    related = {
        "Blocked by": [e.tail for e in links if e.kind == "blocks" and e.head == issue.number],
        "Blocks": [e.head for e in links if e.kind == "blocks" and e.tail == issue.number],
        "Sub-issue of": [e.tail for e in links if e.kind == "sub-issues" and e.head == issue.number],
        "Sub-issues": [e.head for e in links if e.kind == "sub-issues" and e.tail == issue.number],
    }
    parts = [f"## #{issue.number} {escape(issue.title)}",
             " · ".join(f for f in facts if f) + f" · [open on GitHub]({issue.url})",
             *(f"**{name}:** {refs(numbers)}" for name, numbers in related.items() if numbers),
             "---",
             issue.body.strip() or "*No description.*"]
    return "\n\n".join(parts)


class GraphView(QGraphicsView):
    """Drag to pan, wheel to zoom around the mouse."""

    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("white"))

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.0015 ** event.angleDelta().y()
        self.scale(factor, factor)

    def fit(self) -> None:
        """The whole graph in view, but never magnified."""
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1:
            self.resetTransform()


class Window(QMainWindow):
    fetched = Signal(object)  # the issues, from the refresh thread
    fetch_failed = Signal(str)

    def __init__(self, slug: str, issues: list[Issue], links: str | None):
        super().__init__()
        self.setWindowTitle(f"{slug} — issue-graph")
        self.slug = slug
        self.only = links  # --links
        self.current: int | None = None  # the issue in the detail pane
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.selected)
        self.view = GraphView(self.scene)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(self.follow)
        self.detail.setMarkdown("*Click an issue to read it.*")
        split = QSplitter()
        split.addWidget(self.view)
        split.addWidget(self.detail)
        split.setSizes([1000, 450])
        self.setCentralWidget(split)
        bar = self.addToolBar("Refresh")
        bar.setMovable(False)
        self.refresh_action = bar.addAction("Refresh", self.refresh)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.setToolTip(f"Fetch the issues from GitHub again ({self.refresh_action.shortcut().toString()})")
        # Slots of the window, not lambdas: Qt queues those to the window's thread, a lambda would run in the fetch's.
        self.fetched.connect(self.refreshed)
        self.fetch_failed.connect(self.refresh_failed)
        self.load(issues)
        self.resize(1450, 900)

    def load(self, issues: list[Issue]) -> None:
        """Draw the issues. The selected issue stays selected and in view if it is still open."""
        self.issues = {i.number: i for i in issues}
        self.links = graph.edges(issues)  # every link, for the detail pane, whatever the graph shows
        self.scene.clear()
        self.nodes = build(self.scene, graph.layout(graph.to_dot(issues, self.only)))
        self.scene.setSceneRect(self.scene.itemsBoundingRect())  # by itself, it only ever grows
        if self.current in self.issues:
            self.show_issue(self.current)
            if self.current in self.nodes:
                self.nodes[self.current].setSelected(True)
                self.view.centerOn(self.nodes[self.current])
        elif self.current is not None:
            self.detail.setMarkdown(f"*#{self.current} is closed now, or gone.*")
            self.current = None
        self.statusBar().showMessage(f"{len(issues)} open issues, {len(self.links)} links, fetched"
                                     f" {datetime.now():%H:%M} · drag to pan, wheel to zoom")

    def refresh(self) -> None:
        """Fetch the issues again in a thread: gh takes seconds, and the window stays usable meanwhile."""
        self.refresh_action.setEnabled(False)
        self.statusBar().showMessage("Fetching the issues …")

        def fetch() -> None:  # in the thread: it reaches the window only through signals
            try:
                self.fetched.emit(github.fetch(self.slug))
            except github.GhError as e:
                self.fetch_failed.emit(str(e))
        threading.Thread(target=fetch, daemon=True).start()

    @Slot(object)
    def refreshed(self, issues: list[Issue]) -> None:
        self.refresh_action.setEnabled(True)
        self.load(issues)

    @Slot(str)
    def refresh_failed(self, error: str) -> None:
        self.refresh_action.setEnabled(True)
        self.statusBar().showMessage(f"Refresh failed: {error}")

    def selected(self) -> None:
        items = self.scene.selectedItems()
        if items and items[0].data(0) != self.current:  # reselected after a refresh: load showed it already
            self.show_issue(items[0].data(0))

    def show_issue(self, number: int) -> None:
        self.current = number
        self.detail.setMarkdown(markdown(self.issues[number], self.links, self.issues))

    def follow(self, url: QUrl) -> None:
        if url.scheme() == "issue":
            self.select(int(url.path()))
        else:
            QDesktopServices.openUrl(url)

    def select(self, number: int) -> None:
        node = self.nodes.get(number)
        if node is None:  # not drawn under --links: still show it
            self.show_issue(number)
            return
        self.scene.clearSelection()
        node.setSelected(True)
        self.view.centerOn(node)


def run(slug: str, issues: list[Issue], links: str | None) -> int:
    app = QApplication(sys.argv[:1])
    window = Window(slug, issues, links)
    window.show()
    QTimer.singleShot(0, window.view.fit)  # once the window is laid out and the view has its size
    return app.exec()
