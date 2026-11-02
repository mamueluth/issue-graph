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
    issue(3, "Login crash", labels=["bug", "docs"], blocked_by=(1,)),
    issue(4, "Refactor", author=None, parent=3),
]


@pytest.mark.parametrize("query, numbers", [
    ("", [1, 2, 3, 4]),
    ("crash", [1, 3]),
    ("CRASH login", [3]),
    ('"null pointer"', [1]),
    ("#2", [2]),
    ("label:bug", [1, 3]),
    ("label:bug label:docs", [3]),
    ("label:bug,docs", [1, 2, 3]),
    ('label:"good first issue"', [2]),
    ("-label:bug", [2, 4]),
    ("no:label", [4]),
    ("-no:milestone", [1, 2]),
    ('milestone:"v1.0, beta"', [1]),
    ("author:BOB", [2]),
    ("type:bug,task crash", [1]),
])
def test_matches(query, numbers):
    terms = search.parse(query)
    assert [i.number for i in ISSUES if search.matches(i, terms)] == numbers
    assert search.parse(search.text(terms)) == terms


@pytest.mark.parametrize("query, error", [
    ("assignee:ann", "unknown qualifier assignee: use author:"),
    ("lable:editor", "unknown qualifier lable: did you mean label:"),
    ("label: editor", "label: needs a value"),
    ("no:author", "no:author"),
])
def test_errors(query, error):
    with pytest.raises(search.QueryError, match=error):
        search.parse(query)


def test_typing_an_unclosed_quote_still_parses():
    assert search.parse('crash label:"good fir') == [search.Term(None, ("crash",)), search.Term("label", ("good fir",))]


def test_ticking_edits_the_query():
    terms = search.parse("crash -label:bug")
    terms = search.toggle(terms, "label", "docs", True)
    assert search.text(terms) == "crash -label:bug label:docs"
    terms = search.toggle(terms, "label", "good first issue", True)
    assert search.text(terms) == 'crash -label:bug label:docs,"good first issue"'
    assert search.checked(terms, "label") == {"docs", "good first issue"}
    terms = search.toggle(terms, "label", "DOCS", False)
    terms = search.toggle(terms, "label", "good first issue", False)
    assert search.text(terms) == "crash -label:bug"


def test_a_filtered_graph_has_no_links_to_hidden_issues():
    shown = [i for i in ISSUES if i.number != 3]  # 1 blocks 3, 3 is the parent of 4
    assert graph.edges(shown) == []
    assert "i3" not in graph.to_dot(shown)  # a link to it would make dot draw it anyway
