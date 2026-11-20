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
```sh
uv run concierge auth calendar        # opens the sign-in page; use CONCIERGE_ORGANIZER_PASSWORD
uv run concierge agenda build
```
Access tokens from the mock server last 15 minutes on purpose. Wait, run again, and watch
`concierge serve` log a `refresh_token` grant that you did not make.

## What to notice
- The tokens go from your client straight into the vault. They are not written to disk, put
  in a prompt, or seen by the agent.
- Credentials are matched to MCP servers by URL. If your tunnel address changes, sign in again.
- Vaults attach at session creation only.
- An invalid credential does not block the session: it surfaces as a `session.error` event.
- The mock authorization server is a teaching aid with one shared password. Use your real
  identity provider in practice.
