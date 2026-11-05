"""A stand-in for Graphviz's `dot -TFMT`, from the Graphviz that pygraphviz's wheels bundle.

python -m issue_graph.dot FMT: DOT on stdin, dot's output in format FMT on
stdout, Graphviz's messages on stderr. graph.render runs it in a process of
its own, as it would run dot: Graphviz, a C library, writes its messages
straight to stderr, and the bundled fontconfig warns about newer distros'
config files (Ubuntu 24.04's) there on every run. In a child process that
stderr is captured, becomes the error message on failure and is dropped on
success; a Graphviz crash fails one rendering, not the window.
"""

import sys

import pygraphviz


def main() -> int:
    try:
        out = pygraphviz.AGraph(string=sys.stdin.read()).draw(format=sys.argv[1], prog="dot")
    except ValueError as e:  # pygraphviz's DotError (bad DOT) is one too
        print(e, file=sys.stderr)
        return 1
    sys.stdout.buffer.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
