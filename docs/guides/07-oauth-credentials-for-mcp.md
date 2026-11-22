# Guide 07 · Passing OAuth credentials from the client to an MCP server

**You'll learn:** how an agent acts *as a person* on an OAuth-protected MCP server, with the
sign-in done by your client application.

```
 organizer ──signs in──► authorization server (services/oauth.py)
     ▲                              │ code
     │                              ▼
 your client (oauth_client.py) ──exchanges──► access token + refresh token
     │ stores both in the vault (vaults.py)
     ▼
 session (vault attached) ──► Anthropic's MCP proxy adds the token ──► Calendar MCP server
                               and refreshes it when it expires
```

## Steps

**Step 1. Declare the MCP server on the agent, with no credentials.**
Find it: `managed/agents/scheduler/agent.md`, marker `Guide 07 · ... · Step 1`.

**Step 2. Start the authorization-code flow with PKCE** from your client.
Find it: `src/concierge/oauth_client.py`, marker `Step 2`.

**Step 3. Exchange the code for tokens.**
Find it: `src/concierge/oauth_client.py`, marker `Step 3`.

**Step 4. Store the tokens as an `mcp_oauth` credential.** The `refresh` block (refresh
token, client ID, token endpoint) is what makes automatic refresh possible.
Find it: `src/concierge/vaults.py`, marker `Step 4`.

**Step 5. Attach the vault when the session is created.**
Find it: `src/concierge/review.py`, marker `Step 5`.

**Step 6. See the server side.** The Calendar MCP server accepts only access tokens its
authorization server issued, and records bookings as made by the organizer.
Find it: `src/concierge/services/app.py`, marker `Step 6`.

## Try it
Keep the terminal that runs `uv run concierge serve` in view: it is the log of both the
authorization server and the Calendar MCP server.
```sh
uv run concierge auth calendar        # opens the sign-in page; use CONCIERGE_ORGANIZER_PASSWORD
uv run concierge agenda build
```

### What to look for in the `concierge serve` log
Every line about OAuth starts with a big marker, shown in bold yellow in the terminal:
```
========== OAUTH ==========
```
To see only those lines, search the terminal for `OAUTH`, or run
`uv run concierge serve 2>&1 | grep OAUTH`. There are three kinds:

| Kind | When you see it | What it proves |
| --- | --- | --- |
| `SIGN-IN` | Once, when `concierge auth calendar` finishes | Your client exchanged the code for tokens; they went into the vault. |
| `MCP CALL` | Each Calendar MCP tool call, including every booking you approve in `agenda build` | The agent's call reached the MCP server with the organizer's OAuth access token, added by Anthropic's MCP proxy. |
| `REFRESH` | When the access token has expired (after 15 minutes) and the agent calls the calendar again | Anthropic refreshed the token for the vault. You did not make this call. |

Sample lines (your titles and times will differ):
```
INFO:     ========== OAUTH ========== SIGN-IN: issued tokens for organizer (authorization_code grant). The access token expires in 15 min.
INFO:     ========== OAUTH ========== MCP CALL: Calendar MCP find_free_slots authorized by the OAuth access token for organizer
INFO:     ========== OAUTH ========== MCP CALL: Calendar MCP create_event authorized by the OAuth access token for organizer: booking 'Opening talk' in Main Hall at 2026-12-10T18:30
INFO:     ========== OAUTH ========== REFRESH: new access token for organizer (refresh_token grant, made by Anthropic for the vault, not by you). The old refresh token is retired.
```
Each booking you approve in `agenda build` should match one `MCP CALL ... create_event` line.
To see a `REFRESH`, wait more than 15 minutes after signing in and run `agenda build` again.

If a refresh is ever refused (for example, the vault holds a refresh token that was already
used), you see a `WARNING: ========== OAUTH ========== REFUSED: ...` line instead. Sign in
again with `concierge auth calendar`.

## What to notice
- The tokens go from your client straight into the vault. They are not written to disk, put
  in a prompt, or seen by the agent.
- The agent never handles the token, yet every `OAUTH ... MCP CALL` line proves the token
  reached the MCP server: Anthropic's MCP proxy added it on the way. The server knows *who* is acting, so it records each booking as
  made by the organizer. The log names the grant and the subject, never a token value.
- Credentials are matched to MCP servers by URL. If your tunnel address changes, sign in again.
- Vaults attach at session creation only.
- An invalid credential does not block the session: it surfaces as a `session.error` event.
- The mock authorization server is a teaching aid with one shared password. Use your real
  identity provider in practice.
