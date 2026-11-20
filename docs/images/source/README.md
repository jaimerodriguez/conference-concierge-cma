# Visual sources

The images in `docs/images/` are rendered from the HTML pages in this folder. Edit the HTML,
then render again. Never edit the PNGs by hand.

| Page | Image | Used in |
|---|---|---|
| `flow-who-does-the-work.html` | `flow-who-does-the-work.png` | README, guides index |
| `guide-map.html` | `guide-map.png` | README, guides index |
| `flow-journey.html` | `flow-journey.png` | Presentation (all-in-one view with guide badges) |

`common.css` holds the shared colors, one per agent type. Keep the three pages in step:
they use the same step numbers (1 to 7), agent names, and agent types.

## Render

From the repository root:

```bash
uv run --with playwright playwright install chromium   # once
uv run --with playwright python docs/images/source/render.py             # all pages
uv run --with playwright python docs/images/source/render.py guide-map   # one page
```

Playwright is not a project dependency; `--with` brings it in only for this command.
The pages use the Inter and JetBrains Mono fonts when installed and fall back to the system
sans-serif and monospace fonts otherwise.

## When to update

- An agent is renamed, added, or changes type or model: `managed/agents/*/agent.md`.
- The flow changes: a new step, a new board status, a new approval.
- A guide is added or renumbered: `docs/guides/README.md`. Update the badges in
  `flow-journey.html` and the rows of `guide-map.html`.

Keep private values out of the images: no tunnel host, vault or workspace IDs, or real email
addresses.
