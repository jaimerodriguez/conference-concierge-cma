---
# Guide 20 · Moving tools into your own sandbox · Step 3: swap the vaulted secret for a custom tool
# Phase 2 variant of speaker-liaison. Environment-variable vault credentials need
# Anthropic-managed egress, so outside the cloud sandbox the sponsor API call moves into a
# custom tool. Custom tools run in OUR process (phase2/a-self-hosted-sandbox/issue_perks.py),
# which holds the API key. The agent and the sandbox never see it.
name: speaker-liaison-host-tool
description: Issues sponsor perk codes through a host-side custom tool.
model: claude-haiku-5-5
tools:
  - type: agent_toolset_20260401
    default_config: {enabled: false}
  - type: mcp_toolset
    mcp_server_name: eventdb
    default_config: {permission_policy: {type: always_allow}}
  - type: custom
    name: issue_perk_code
    description: >-
      Issue the sponsor's $50 CloudCredits code to an accepted speaker. Returns the same code
      if the member already has one, so calling it twice is safe.
    input_schema:
      type: object
      properties:
        member_id: {type: string, description: The speaker's member id from the Event DB.}
      required: [member_id]
mcp_servers:
  - {type: url, name: eventdb, url: "https://concierge.example.com/eventdb/mcp"}
---

You look after accepted speakers of a local user-group meetup.

Our sponsor, CloudCredits, gives each accepted speaker a $50 credit code. For each accepted
proposal (use the eventdb `list_proposals` tool with status `accepted`), issue one code for
its speaker with the `issue_perk_code` tool, then record it with the eventdb `record_perk`
tool. Reply with a table: speaker name, talk title, code.
