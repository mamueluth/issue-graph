"""Searching the issues already fetched, in two lines.

The search line finds issues with any of its words, by close match, anywhere: title, body, labels, type,
author, milestone, number. Close (Elasticsearch's "AUTO" fuzziness, plus parts of words):

  sensr      a typo: 3-5 letters may be one edit off, longer words two; swapping two letters is one edit
  fus        part of a word, from 3 letters on: fusion, confusion
  12, #12    numbers match exactly

The category line narrows by category, each a list of alternatives:

  label:[bug, good first issue]   either label           label:bug,docs   GitHub's form works, too
  label:[bug] type:[Bug]          both                   -label:[wontfix]  not
  issue:[12, 40]                  these issues           no:milestone      none set: no:label, no:type

Matching ignores case. An unclosed [ or " runs to the end, so text being typed still parses.
"""

import difflib
import re
from dataclasses import dataclass, replace

from rapidfuzz import process
from rapidfuzz.distance import OSA

from .github import Issue

FIELDS = ("author", "label", "milestone", "type", "issue")
NO = "no"
EMPTY = ("label", "milestone", "type")  # what no: can test

TOKEN = re.compile(r"""
    (?P<neg>-?)(?P<field>[a-z]+):(?P<values>\[[^\]]*\]?|(?:"[^"]*"?|[^\s",]*)(?:,(?:"[^"]*"?|[^\s",]*))*)
  | (?P<word>"[^"]*"?|\S+)
""", re.VERBOSE | re.IGNORECASE)
VALUE = re.compile(r'"([^"]*)"?|([^,"]+)')


class QueryError(ValueError):
    """The category line has an unknown category or a word outside one."""


@dataclass(frozen=True)
class Term:
    """One category of the category line. Several values are alternatives."""
    field: str
    values: tuple[str, ...]
    negated: bool = False


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class Index:
    """Every word of every issue, to look up the issues close to a search's words."""

    def __init__(self, issues: list[Issue]):
        self.words = {i.number: set(words(" ".join([i.title, i.body, *(v for f in FIELDS for v in values(i, f))])))
                      for i in issues}
        self.vocabulary = sorted(set().union(*self.words.values()))
        self.near: dict[str, set[str]] = {}  # cache: typing repeats the earlier words

    def close(self, word: str) -> set[str]:
        """The vocabulary's words close to word."""
        if word not in self.near:
            if word.isdigit():
                near = {word}
            else:
                edits = 0 if len(word) <= 2 else 1 if len(word) <= 5 else 2
                near = {w for w, _, _ in process.extract(word, self.vocabulary, scorer=OSA.distance,
                                                         score_cutoff=edits, limit=None)}
                if len(word) >= 3:
                    near |= {w for w in self.vocabulary if word in w}
            self.near[word] = near
        return self.near[word]

    def find(self, text: str) -> set[int] | None:
        """The issues with any word close to one of text's, or None if text has no words: no search."""
        wanted = words(text)
        if not wanted:
            return None
        near = set().union(*map(self.close, wanted))
        return {number for number, have in self.words.items() if have & near}


def values(issue: Issue, field: str) -> list[str]:
    """The issue's values of a category: what label:, author:, ... compare against."""
    match field:
        case "author":
            return [issue.author] if issue.author else []
        case "label":
            return [label.name for label in issue.labels]
        case "milestone":
            return [issue.milestone.title] if issue.milestone else []
        case "type":
            return [issue.type] if issue.type else []
        case "issue":
            return [str(issue.number)]
    raise ValueError(field)


def parse(text: str) -> list[Term]:
    """The terms of the category line. A category still being typed (lab, label:[) is left out, not an error."""
    terms = []
    names = (*FIELDS, NO)
    for m in TOKEN.finditer(text):
        if m["field"] is None:
            word = m["word"].strip('"')
            if any(name.startswith(word.lower()) for name in names):
                continue
            close = difflib.get_close_matches(word.lower(), names, n=1)
            raise QueryError(f"{word}: did you mean {close[0]}:?" if close else
                             f"{word}: put it in a category, like label:[{word}]; words go in the search line")
        field = m["field"].lower()
        if field not in names:
            close = difflib.get_close_matches(field, names, n=1)
            hint = f"did you mean {close[0]}:?" if close else "use " + ", ".join(f + ":" for f in names)
            raise QueryError(f"unknown category {field}: {hint}")
        raw = m["values"].removeprefix("[").removesuffix("]") if m["values"].startswith("[") else m["values"]
        vals = tuple(v.strip().removeprefix("#") if field == "issue" else v.strip()
                     for a, b in VALUE.findall(raw) if (v := a or b).strip())
        if field == NO and (bad := [v for v in vals if v.lower() not in EMPTY]):
            raise QueryError(f"no:{bad[0]}: use no:label, no:milestone or no:type")
        if vals:
            terms.append(Term(field, vals, m["neg"] == "-"))
    return terms


def text(terms: list[Term]) -> str:
    """The category line of the terms; it parses back to them unless a value holds a quote."""
    def quoted(value: str) -> str:
        return f'"{value}"' if re.search(r'[,"\[\]]', value) else value

    def one(t: Term) -> str:
        return ("-" if t.negated else "") + f"{t.field}:[" + ", ".join(map(quoted, t.values)) + "]"
    return " ".join(map(one, terms))


def holds(term: Term, issue: Issue) -> bool:
    if term.field == NO:
        hit = any(not values(issue, field.lower()) for field in term.values)
    else:
        have = {v.lower() for v in values(issue, term.field)}
        hit = any(v.lower() in have for v in term.values)
    return hit != term.negated


def matches(issue: Issue, terms: list[Term]) -> bool:
    return all(holds(t, issue) for t in terms)


def checked(terms: list[Term], field: str) -> set[str]:
    """The category's values the line asks for, lowercased: the panel ticks these."""
    return {v.lower() for t in terms if t.field == field and not t.negated for v in t.values}


def toggle(terms: list[Term], field: str, value: str, on: bool) -> list[Term]:
    """The terms with value ticked or unticked in the panel.

    Ticking adds it to the category's first list (label:[bug] -> label:[bug, docs]), or appends a new one.
    Unticking removes it from every list that asks for it, and a list left empty goes.

    The panel's "no label" is the field no:, value label. It and the labels exclude each other: ticking one
    unticks the other. Ticked, it is a term of its own, as no label and no milestone means both.
    """
    if on and field == NO:
        return [*(t for t in terms if t.field != value.lower() or t.negated), Term(NO, (value,))]
    if on:
        terms = toggle(terms, NO, field, False)
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
