"""The window: search and filters, the issue graph laid out by Graphviz and drawn by Qt, the selected issue."""

import html
import re
import sys
import threading
from collections import Counter
from datetime import datetime

from PySide6.QtCore import QPointF, QStringListModel, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetricsF, QKeyEvent, QKeySequence, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF, QWheelEvent)
from PySide6.QtWidgets import (QApplication, QCompleter, QGraphicsItem, QGraphicsItemGroup, QGraphicsPathItem,
                               QGraphicsPolygonItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton, QSplitter, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import github, graph, search
from .github import Issue

TICKABLE = [f for f in search.FIELDS if f != "issue"]  # the panel's tree: issues are too many, issue: is typed
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

    facts = [f"Author: {escape(issue.author)}" if issue.author else "",
             f"Type: {issue.type}" if issue.type else "",
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


class CategoryEdit(QLineEdit):
    """The category line, completing what is typed: a category's name, then inside [ ] that category's values."""

    edited = Signal()  # typed, or a completion inserted
    OPEN = re.compile(r"-?([a-z]+):\[([^\]]*)$", re.IGNORECASE)  # the cursor is in a list: its category, values so far
    NAME = re.compile(r"(?:^|\s)-?([a-z]*)$", re.IGNORECASE)  # the cursor ends a category's name, or a space

    def __init__(self) -> None:
        super().__init__()
        self.choices: dict[str, dict[str, str]] = {}  # per category: shown in the list -> inserted; the panel sets it
        self.options: dict[str, str] = {}  # the choices offered right now
        self.model = QStringListModel(self)
        self.completer = QCompleter(self.model, self)
        self.completer.setWidget(self)  # not setCompleter: that would complete the whole line, not the word typed
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.activated[str].connect(self.insert)
        self.textEdited.connect(self.suggest)
        self.textEdited.connect(self.edited)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.completer.popup().isVisible() and event.key() in (
                Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            event.ignore()  # the completer picks or closes; Qt hands it the key only if the line ignores it
            return
        at = self.cursorPosition()
        if event.text() == "]" and self.text()[at:at + 1] == "]":  # typing over the ] inserted with [
            self.setCursorPosition(at + 1)
            self.completer.popup().hide()
            return
        super().keyPressEvent(event)

    def suggest(self) -> None:
        """Offer what fits at the cursor: the category's values not listed yet, or the categories."""
        head = self.text()[:self.cursorPosition()]
        if m := self.OPEN.search(head):
            *listed, typed = (v.strip().lower() for v in m[2].split(","))
            self.options = {shown: value for shown, value in self.choices.get(m[1].lower(), {}).items()
                            if value.lower() not in listed}
        elif m := self.NAME.search(head):
            typed = m[1]
            self.options = {name: name for name in (*search.FIELDS, search.NO)}
        else:
            self.completer.popup().hide()
            return
        self.model.setStringList(list(self.options))
        self.completer.setCompletionPrefix(typed)
        if not self.completer.completionCount():
            self.completer.popup().hide()
            return
        popup = self.completer.popup()
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))  # Enter takes the first
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
        self.completer.complete(rect)

    def insert(self, shown: str) -> None:
        """Put the picked choice in place of what was typed: a category opens its list, [ ], for its values."""
        at = self.cursorPosition()
        head, tail = self.text()[:at], self.text()[at:]
        if self.OPEN.search(head):
            start = max(head.rfind("["), head.rfind(",")) + 1
            head = head[:start] + (" " if head[start - 1] == "," else "") + self.options[shown]
        else:
            head = head[:self.NAME.search(head).start(1)] + self.options[shown] + ":["
            tail = "]" + tail
        self.setText(head + tail)
        self.setCursorPosition(len(head))
        self.edited.emit()
        if head.endswith("["):
            self.suggest()


class FilterPanel(QWidget):
    """The search line, the category line, every author, label, milestone and type to tick, and Reset.

    The category line is the categories' only state: ticking a value edits it, and the ticks follow it.
    """

    changed = Signal()  # either line changed; the category line's terms are the last that parsed

    def __init__(self) -> None:
        super().__init__()
        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self.apply)
        tip = f"<pre>{html.escape(search.__doc__)}</pre>"
        self.words = QLineEdit()
        self.words.setPlaceholderText("Search: any words, close matches")
        self.words.setToolTip(tip)
        self.words.setClearButtonEnabled(True)
        self.words.textEdited.connect(self.timer.start)  # typing: apply once it pauses
        self.words.returnPressed.connect(self.apply)
        self.categories = CategoryEdit()
        self.categories.setPlaceholderText("Categories: label:[bug, editor] issue:[12]")
        self.categories.setToolTip(tip)
        self.categories.setClearButtonEnabled(True)
        self.categories.edited.connect(self.timer.start)
        self.categories.returnPressed.connect(self.apply)
        self.error = QLabel()  # why the category line does not parse; the graph keeps its last valid terms meanwhile
        self.error.setStyleSheet("color: #cf222e")
        self.error.setWordWrap(True)
        self.error.hide()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Issues"])
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionsClickable(True)  # a click sorts by that column, a second click the other way round
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.tree.headerItem().setData(1, Qt.ItemDataRole.InitialSortOrderRole, Qt.SortOrder.DescendingOrder)
        header.sortIndicatorChanged.connect(self.sort)
        self.values: list[QTreeWidgetItem] = []
        self.tree.itemChanged.connect(self.ticked)
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.words)
        layout.addWidget(self.categories)
        layout.addWidget(self.error)
        layout.addWidget(self.tree)
        layout.addWidget(reset)
        self.terms: list[search.Term] = []

    def fill(self, issues: list[Issue]) -> None:
        """List the issues' authors, labels, milestones and types with counts, ticked as the category line asks,
        and give the category line its choices.

        Called again after a refresh: the lines stay, and a group the user collapsed stays collapsed.
        """
        tops = [self.tree.topLevelItem(k) for k in range(self.tree.topLevelItemCount())]
        collapsed = {top.text(0) for top in tops if not top.isExpanded()}
        blocked = self.tree.blockSignals(True)  # building the items is no clicking
        self.tree.clear()
        self.values = []
        colors = {label.name: label.color for i in issues for label in i.labels}
        for field in TICKABLE:
            top = QTreeWidgetItem(self.tree, [field.capitalize()])
            counts = Counter(v for i in issues for v in search.values(i, field))
            for value in counts:
                item = QTreeWidgetItem(top, [value])
                item.setToolTip(0, value)  # a long name is cut off in a narrow panel
                item.setData(0, Qt.ItemDataRole.UserRole, (field, value))
                item.setData(1, Qt.ItemDataRole.DisplayRole, counts[value])
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
                if field == "label":
                    swatch = QPixmap(12, 12)
                    swatch.fill(QColor(f"#{colors[value]}"))
                    item.setIcon(0, swatch)
                self.values.append(item)
            top.setExpanded(top.text(0) not in collapsed)
            top.setDisabled(not counts)  # no issue has one: greyed, not hidden
        self.sort()
        self.tick(self.terms)
        self.tree.blockSignals(blocked)
        self.categories.choices = {
            **{field: {v: v for v in sorted({v for i in issues for v in search.values(i, field)}, key=str.lower)}
               for field in TICKABLE},
            "issue": {f"#{i.number} {i.title}": str(i.number) for i in sorted(issues, key=lambda i: i.number)},
            search.NO: {field: field for field in search.EMPTY},
        }

    def sort(self) -> None:
        """Sort each group's values as the header's sort indicator says; the groups keep their order.

        Equal counts stay A to Z in either direction.
        """
        header = self.tree.header()
        descending = header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        for k in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(k)
            items = sorted(top.takeChildren(), key=lambda item: item.text(0).lower())
            if header.sortIndicatorSection() == 1:
                items.sort(key=lambda item: item.data(1, Qt.ItemDataRole.DisplayRole), reverse=descending)  # stable
            elif descending:
                items.reverse()
            top.addChildren(items)

    def apply(self) -> None:
        self.timer.stop()
        try:
            self.terms = search.parse(self.categories.text())
            self.error.hide()
        except search.QueryError as e:
            self.error.setText(str(e))
            self.error.show()
        self.tick(self.terms)
        self.changed.emit()

    def tick(self, terms: list[search.Term]) -> None:
        """Tick the values the terms ask for, and only those."""
        wanted = {field: search.checked(terms, field) for field in TICKABLE}
        blocked = self.tree.blockSignals(True)  # ticks set here are no clicks
        for item in self.values:
            field, value = item.data(0, Qt.ItemDataRole.UserRole)
            item.setCheckState(0, Qt.CheckState.Checked if value.lower() in wanted[field] else Qt.CheckState.Unchecked)
        self.tree.blockSignals(blocked)

    def ticked(self, item: QTreeWidgetItem) -> None:
        field, value = item.data(0, Qt.ItemDataRole.UserRole)
        try:
            terms = search.parse(self.categories.text())
        except search.QueryError as e:  # the line being typed is broken: undo the tick
            self.error.setText(str(e))
            self.error.show()
            self.tick(self.terms)
            return
        on = item.checkState(0) == Qt.CheckState.Checked
        self.categories.setText(search.text(search.toggle(terms, field, value, on)))
        self.apply()

    def reset(self) -> None:
        self.words.clear()
        self.categories.clear()
        self.apply()


class Window(QMainWindow):
    fetched = Signal(object)  # the issues, from the refresh thread
    fetch_failed = Signal(str)

    def __init__(self, slug: str, issues: list[Issue], links: str | None):
        super().__init__()
        self.setWindowTitle(f"{slug} — issue-graph")
        self.slug = slug
        self.only = links  # --links
        self.shown: list[int] | None = None  # the issues the search matches, drawn or (under --links) not
        self.current: int | None = None  # the issue in the detail pane
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.selected)
        self.view = GraphView(self.scene)
        self.panel = FilterPanel()
        self.panel.changed.connect(self.filter)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(self.follow)
        self.detail.setMarkdown("*Click an issue to read it.*")
        split = QSplitter()
        split.addWidget(self.panel)
        split.addWidget(self.view)
        split.addWidget(self.detail)
        split.setSizes([280, 1000, 450])
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
        self.resize(1730, 900)

    def load(self, issues: list[Issue]) -> None:
        """Take the fetched issues: the panel lists their values, and the search's matches are drawn anew.

        The selected issue stays selected and in view, at the same zoom, if it is still open.
        """
        self.all = issues
        self.issues = {i.number: i for i in issues}
        self.links = graph.edges(issues)  # every link, for the detail pane, whatever the graph shows
        self.fetched_at = datetime.now()
        self.index = search.Index(issues)
        self.panel.fill(issues)
        if self.current in self.issues:
            self.show_issue(self.current)
        elif self.current is not None:
            self.detail.setMarkdown(f"*#{self.current} is closed now, or gone.*")
            self.current = None
        self.shown = None  # draw even if the same issues match: their links may have changed
        self.filter(fit=False)
        if self.current in self.nodes:
            self.view.centerOn(self.nodes[self.current])

    def filter(self, fit: bool = True) -> None:
        """Draw the issues both lines match. A new set of them is laid out anew; with fit, the view shows it all."""
        found = self.index.find(self.panel.words.text())
        shown = [i for i in self.all if search.matches(i, self.panel.terms) and (found is None or i.number in found)]
        if [i.number for i in shown] != self.shown:
            self.shown = [i.number for i in shown]
            self.scene.clear()
            self.nodes = build(self.scene, graph.layout(graph.to_dot(shown, self.only)))
            self.scene.setSceneRect(self.scene.itemsBoundingRect())  # by itself, it only ever grows
            if self.current in self.nodes:
                self.nodes[self.current].setSelected(True)
            if fit:
                self.view.fit()
        self.statusBar().showMessage(f"{len(shown)} of {len(self.all)} open issues, {len(graph.edges(shown))} links"
                                     f" between them, fetched {self.fetched_at:%H:%M} · drag to pan, wheel to zoom")

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
        if items and items[0].data(0) != self.current:  # reselected after a filter or refresh: keep the pane's scroll
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
        if node is None:  # filtered out, or not drawn under --links: still show it
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
