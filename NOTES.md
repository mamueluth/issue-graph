# Notes

Goal: browse a repo's issues without Claude, then drop the toolbox
`issue-graph` skill (its DOT output is reproduced exactly: checked against
the skill's script on 3 repos × 4 `--links` modes).

## Backlog

- Filters in the window: labels, issue types, milestones. The data is
  already fetched; a filter change rebuilds the DOT and relayouts.
- Following a link at overview zoom centers the issue but it stays tiny:
  zoom in to a readable size.
- Selection highlight is a thin dashed box: make it stand out, maybe
  highlight the selected issue's links too.
- Rebuild loses the `uv tool install`: add it to `packages.yaml` once the
  tool has settled.
- Remove the toolbox skill.
