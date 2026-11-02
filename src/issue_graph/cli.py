"""issue-graph: a GitHub repo's open issues and their blocked-by and sub-issue links as a graph.

Opens a window to browse them; with -o renders to a file instead, without a display.
"""

import argparse
import os
import sys
from pathlib import Path

from . import github, graph

FORMATS = {".png": "png", ".svg": "svg", ".dot": "dot"}


def repo(text: str) -> str:
    if text.count("/") != 1 or not all(text.split("/")):
        raise argparse.ArgumentTypeError(f"expected OWNER/REPO, got {text!r}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(prog="issue-graph", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", nargs="?", type=repo, metavar="OWNER/REPO",
                        help="default: the GitHub repo of the current directory")
    parser.add_argument("-o", "--output", type=Path, metavar="FILE",
                        help="render to FILE (.png, .svg or .dot) instead of opening the window")
    parser.add_argument("--links", choices=graph.LINKS,
                        help="only this kind of link and the issues it connects; both = either kind")
    args = parser.parse_args()
    if args.output and args.output.suffix.lower() not in FORMATS:
        parser.error(f"-o: unknown format {args.output.suffix!r}, use .png, .svg or .dot")
    has_display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if not args.output and sys.platform == "linux" and not has_display:
        parser.error("no display to open the window on; render to a file with -o FILE")

    try:
        slug = args.repo or github.current_repo()
        issues = github.fetch(slug)
        if args.output:
            dot = graph.to_dot(issues, args.links)
            fmt = FORMATS[args.output.suffix.lower()]
            args.output.write_bytes(dot.encode() if fmt == "dot" else graph.render(dot, fmt))
            return 0
        from . import ui  # Qt only for the window: rendering to a file needs neither Qt nor a display
        return ui.run(slug, issues, args.links)
    except (github.GhError, graph.GraphvizError) as e:
        print(f"issue-graph: {e}", file=sys.stderr)
        return 1
