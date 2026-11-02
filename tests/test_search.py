import pytest

from issue_graph import graph, search
from issue_graph.github import Issue, Label, Milestone


def issue(number, title="", body="", author="ann", type=None, milestone=None, labels=(), parent=None, blocked_by=()):
    return Issue(number=number, title=title, body=body, url=f"https://github.com/o/r/issues/{number}",
                 author=author, type=type, milestone=Milestone(1, milestone) if milestone else None,
                 labels=tuple(Label(name, "ededed") for name in labels), parent=parent, blocked_by=blocked_by)


ISSUES = [
    issue(1, "Crash on start", "null pointer in main", type="Bug", milestone="v1.0, beta", labels=["bug"]),
    issue(2, "Docs for login", author="bob", type="Task", milestone="v2", labels=["docs", "good first issue"]),
    issue(3, "Login crash", "the sensor-fusion step", labels=["bug", "docs"], blocked_by=(1,)),
    issue(4, "Refactor the debugger", "see #12", author=None, parent=3),
    issue(12, "Configuration", "fusion of settings"),
]


@pytest.mark.parametrize("query, numbers", [
    ("", None),
    ("crash", {1, 3}),
    ("crash refactor", {1, 3, 4}),  # any word
    ("CRASHES", {1, 3}),  # one edit off
    ("sensr", {3}),  # a typo
    ("fus", {3, 12}),  # part of a word, in sensor-fusion and fusion
    ("bug", {1, 3, 4}),  # labelled bug, and debugger
    ("bob task", {2}),  # author and type
    ("beta", {1}),  # milestone
    ("#12", {4, 12}),  # issue 12, and #12 in a body
    ("13", set()),  # numbers match exactly
    ("ox", set()),  # two letters: exactly only
])
def test_search_line(query, numbers):
    assert search.Index(ISSUES).find(query) == numbers


@pytest.mark.parametrize("query, numbers", [
    ("", [1, 2, 3, 4, 12]),
    ("label:[bug]", [1, 3]),
    ("label:[bug] label:[docs]", [3]),
    ("label:[bug, docs]", [1, 2, 3]),
    ("label:bug,docs", [1, 2, 3]),
    ("label:[good first issue]", [2]),
    ("-label:[bug]", [2, 4, 12]),
    ("no:label", [4, 12]),
    ("-no:milestone", [1, 2]),
    ('milestone:["v1.0, beta"]', [1]),
    ("author:[BOB]", [2]),
    ("type:[bug, task] issue:[#1, 3]", [1]),
    ("label:[bug", [1, 3]),  # still being typed
    ("label:[] lab", [1, 2, 3, 4, 12]),
])
def test_category_line(query, numbers):
    terms = search.parse(query)
    assert [i.number for i in ISSUES if search.matches(i, terms)] == numbers
    assert search.parse(search.text(terms)) == terms


@pytest.mark.parametrize("query, error", [
    ("assignee:[ann]", "unknown category assignee: use author:"),
    ("lable:[editor]", "unknown category lable: did you mean label:"),
    ("lable", "lable: did you mean label:"),
    ("label: editor", "editor: put it in a category, like label:\\[editor\\]"),
    ("no:author", "no:author"),
])
def test_category_errors(query, error):
    with pytest.raises(search.QueryError, match=error):
        search.parse(query)


def test_ticking_edits_the_category_line():
    terms = search.parse("-label:bug")
    terms = search.toggle(terms, "label", "docs", True)
    assert search.text(terms) == "-label:[bug] label:[docs]"
    terms = search.toggle(terms, "label", "good, first", True)
    assert search.text(terms) == '-label:[bug] label:[docs, "good, first"]'
    assert search.checked(terms, "label") == {"docs", "good, first"}
    terms = search.toggle(terms, "label", "DOCS", False)
    terms = search.toggle(terms, "label", "good, first", False)
    assert search.text(terms) == "-label:[bug]"


def test_a_filtered_graph_has_no_links_to_hidden_issues():
    shown = [i for i in ISSUES if i.number != 3]  # 1 blocks 3, 3 is the parent of 4
    assert graph.edges(shown) == []
    assert "i3" not in graph.to_dot(shown)  # a link to it would make dot draw it anyway
