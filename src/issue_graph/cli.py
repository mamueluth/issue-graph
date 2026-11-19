"""issue-graph: a GitHub repo's open issues and their blocked-by and sub-issue links as a graph.

Opens a window to browse them; with -o renders to a file instead, without a display.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from . import github, graph

FORMATS = {".png": "png", ".svg": "svg", ".dot": "dot"}


def repo(text: str) -> str:
    if text.count("/") != 1 or not all(text.split("/")):
        raise argparse.ArgumentTypeError(f"expected OWNER/REPO, got {text!r}")
    return text


def has_display() -> bool:
    """Whether the window has a display to open on.

    On Linux, that is DISPLAY or WAYLAND_DISPLAY. When both are empty, a forwarded X socket named in
    REMOTE_CONTAINERS_DISPLAY_SOCK (as VS Code's dev containers set it) becomes the display: X<n> sets
    DISPLAY to :<n>.
    """
    if sys.platform != "linux" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    sock = Path(os.environ.get("REMOTE_CONTAINERS_DISPLAY_SOCK", ""))
    number = re.fullmatch(r"X(\d+)", sock.name)
    if number and sock.is_socket():
        os.environ["DISPLAY"] = f":{number[1]}"
        return True
    return False


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
    if not args.output and not has_display():
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
