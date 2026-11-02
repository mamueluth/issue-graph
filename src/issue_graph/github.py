"""Fetch a repo's open issues and their links through the gh CLI."""

import json
import subprocess
from dataclasses import dataclass

# One paginated GraphQL query, a second or two. parent and blockedBy are
# github.com's issue relationship fields.
QUERY = """
query($owner: String!, $repo: String!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    issues(states: OPEN, first: 100, after: $endCursor) {
      nodes {
        number title body url
        issueType { name }
        milestone { number title }
        labels(first: 20) { nodes { name color } }
        parent { number repository { nameWithOwner } }
        blockedBy(first: 50) { nodes { number repository { nameWithOwner } } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


class GhError(RuntimeError):
    """gh is missing or a gh call failed; the message is gh's own."""


@dataclass(frozen=True)
class Label:
    name: str
    color: str  # hex as GitHub sends it, without "#"


@dataclass(frozen=True)
class Milestone:
    number: int
    title: str


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str  # Markdown
    url: str
    type: str | None  # Bug, Feature, ... if the repo uses issue types
    milestone: Milestone | None
    labels: tuple[Label, ...]
    # Links to open issues of this repo only: links to closed issues or to
    # other repos are dropped when fetching.
    parent: int | None
    blocked_by: tuple[int, ...]


def gh(*args: str) -> str:
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise GhError("gh not found: install the GitHub CLI and run `gh auth login`") from None
    if done.returncode != 0:
        raise GhError(done.stderr.strip() or f"gh {args[0]} failed")
    return done.stdout


def current_repo() -> str:
    """OWNER/REPO of the git repo in the working directory, resolved the way gh itself does."""
    return gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()


def fetch(slug: str) -> list[Issue]:
    """Every open issue of OWNER/REPO, in GitHub's order."""
    owner, repo = slug.split("/")
    pages = json.loads(gh("api", "graphql", "--paginate", "--slurp",
                          "-f", f"owner={owner}", "-f", f"repo={repo}", "-f", f"query={QUERY}"))
    nodes = [n for page in pages for n in page["data"]["repository"]["issues"]["nodes"]]
    open_numbers = {n["number"] for n in nodes}

    def here(ref: dict | None) -> int | None:
        """The linked issue's number if it is open and in this repo."""
        if ref is None or ref["repository"]["nameWithOwner"].lower() != slug.lower():
            return None
        return ref["number"] if ref["number"] in open_numbers else None

    return [
        Issue(
            number=n["number"],
            title=n["title"],
            body=n["body"],
            url=n["url"],
            type=n["issueType"]["name"] if n["issueType"] else None,
            milestone=Milestone(**n["milestone"]) if n["milestone"] else None,
            labels=tuple(Label(**label) for label in n["labels"]["nodes"]),
            parent=here(n["parent"]),
            blocked_by=tuple(b for ref in n["blockedBy"]["nodes"] if (b := here(ref)) is not None),
        )
        for n in nodes
    ]
