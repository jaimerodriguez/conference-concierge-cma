"""The demo's stand-in "outside world": the services the agents call.

Everything here is a mock you run yourself, exposed through one public tunnel:

* ``oauth``        a tiny OAuth 2.0 authorization server
* ``calendar_mcp`` a Calendar MCP server that requires an OAuth access token
* ``eventdb_mcp``  an Event DB MCP server that requires a static bearer token
* ``credits_api``  the "CloudCredits" sponsor REST API that requires an API key header

None of this code calls Claude. It is what a real deployment would already have.
"""
