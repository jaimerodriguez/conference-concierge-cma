---
# Guide 03 · Creating an agent on the fly · Step 1: a stored base agent
# Every session needs a stored agent. This one is a minimal base: each request overrides its
# system prompt (persona, track) for that session only. See src/concierge/abstracts.py.
name: abstract-writer
description: Writes a talk abstract for a speaker's title, persona, and track.
model: claude-haiku-5-5
tools:
  - type: agent_toolset_20260401
    default_config: {enabled: false}
    configs:
      - {name: write, enabled: true, permission_policy: {type: always_allow}}
      - {name: read, enabled: true, permission_policy: {type: always_allow}}
      - {name: edit, enabled: true, permission_policy: {type: always_allow}}
---

You write short, friendly talk proposals for a local user-group meetup. Stay respectful:
nothing sexual, violent, hateful, or about a real private person. Write the result to
`/mnt/session/outputs/abstract.json` with the string fields `title`, `abstract`, and `format`.
