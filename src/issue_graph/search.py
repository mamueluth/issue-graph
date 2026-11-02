"""GitHub's issue search syntax, applied to the issues already fetched.

  crash "null pointer"   words or phrases in the title or body, all of them; N or #N is issue N
  label:bug              a qualifier: author, label, milestone, type
  label:bug,docs         a comma list: either value
  label:a label:b        repeated: both
  -label:wontfix         not
  no:milestone           the field is empty: no:label, no:milestone, no:type

Matching ignores case. A value with spaces or commas is quoted: milestone:"v1.0, beta".
"""

import re
from dataclasses import dataclass, replace

from .github import Issue

FIELDS = ("author", "label", "milestone", "type")
NO = "no"

TOKEN = re.compile(r"""
    (?P<neg>-?)(?P<field>[a-z]+):(?P<values>(?:"[^"]*"?|[^\s",]*)(?:,(?:"[^"]*"?|[^\s",]*))*)  # -label:a,"b c"
  | "(?P<phrase>[^"]*)"?                                                                     # "a phrase"
  | (?P<word>\S+)
""", re.VERBOSE | re.IGNORECASE)
VALUE = re.compile(r'"([^"]*)"?|([^\s",]+)')


class QueryError(ValueError):
    """The search text has an unknown qualifier or one without a value."""


@dataclass(frozen=True)
class Term:
    """One part of a query: free text (field None) or a qualifier. Several values are alternatives."""
    field: str | None
    values: tuple[str, ...]
    negated: bool = False


def values(issue: Issue, field: str) -> list[str]:
    """The issue's values of a qualifier field: what label:, author:, ... compare against."""
    match field:
        case "author":
            return [issue.author] if issue.author else []
        case "label":
            return [label.name for label in issue.labels]
        case "milestone":
            return [issue.milestone.title] if issue.milestone else []
        case "type":
            return [issue.type] if issue.type else []
    raise ValueError(field)


def parse(text: str) -> list[Term]:
    """The terms of the search text. An unclosed quote runs to the end, so text being typed still parses."""
    terms = []
    for m in TOKEN.finditer(text):
        if m["field"] is None:
            free = m["phrase"] if m["phrase"] is not None else m["word"]
            if free.strip():
                terms.append(Term(None, (free,)))
            continue
        field = m["field"].lower()
        vals = tuple(a or b for a, b in VALUE.findall(m["values"]) if a or b)
        if field not in (*FIELDS, NO):
            raise QueryError(f"unknown qualifier {field}:, use {', '.join(f + ':' for f in (*FIELDS, NO))}")
        if not vals:
            raise QueryError(f"{field}: needs a value")
        if field == NO and (bad := [v for v in vals if v.lower() not in FIELDS[1:]]):
            raise QueryError(f"no:{bad[0]}: use no:label, no:milestone or no:type")
        terms.append(Term(field, vals, m["neg"] == "-"))
    return terms


def quoted(value: str) -> str:
    return f'"{value}"' if re.search(r'[\s,"]', value) else value


def text(terms: list[Term]) -> str:
    """The search text of the terms; it parses back to them unless a value holds a quote."""
    def one(t: Term) -> str:
        if t.field is None:  # quoted when it would read as a qualifier, too
            return f'"{t.values[0]}"' if re.search(r'[\s":]', t.values[0]) else t.values[0]
        return ("-" if t.negated else "") + f"{t.field}:" + ",".join(map(quoted, t.values))
    return " ".join(map(one, terms))


def holds(term: Term, issue: Issue) -> bool:
    if term.field is None:
        word = term.values[0].lower()
        hit = word.removeprefix("#") == str(issue.number) or word in issue.title.lower() or word in issue.body.lower()
    elif term.field == NO:
        hit = any(not values(issue, field.lower()) for field in term.values)
    else:
        have = {v.lower() for v in values(issue, term.field)}
        hit = any(v.lower() in have for v in term.values)
    return hit != term.negated


def matches(issue: Issue, terms: list[Term]) -> bool:
    return all(holds(t, issue) for t in terms)


def checked(terms: list[Term], field: str) -> set[str]:
    """The field's values the query asks for, lowercased: the panel ticks these."""
    return {v.lower() for t in terms if t.field == field and not t.negated for v in t.values}


def toggle(terms: list[Term], field: str, value: str, on: bool) -> list[Term]:
    """The terms with value ticked or unticked in the panel.

    Ticking adds it to the field's first qualifier as an alternative (label:bug -> label:bug,docs), or appends
    a qualifier. Unticking removes it from every qualifier that asks for it, and a qualifier left empty goes.
    """
    mine = [k for k, t in enumerate(terms) if t.field == field and not t.negated]
    if on:
        if not mine:
            return [*terms, Term(field, (value,))]
        first = terms[mine[0]]
        return [*terms[:mine[0]], replace(first, values=(*first.values, value)), *terms[mine[0] + 1:]]
    out = []
    for k, t in enumerate(terms):
        if k in mine:
            t = replace(t, values=tuple(v for v in t.values if v.lower() != value.lower()))
            if not t.values:
                continue
        out.append(t)
    return out
