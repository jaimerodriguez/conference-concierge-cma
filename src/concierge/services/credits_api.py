"""The "CloudCredits" sponsor API: a plain REST API protected by an API key header.

It stands in for any third-party service an agent calls from the sandbox with ``curl`` or an
SDK. The key lives in the vault as an ``environment_variable`` credential (Guide 06).
"""

from __future__ import annotations

import secrets

from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from concierge.config import Settings
from concierge.services.store import Store


class IssueCodeRequest(BaseModel):
    member_id: str
    amount_usd: int = Field(default=50, ge=1, le=100)


def build_routes(settings: Settings, store: Store) -> list[Route]:
    async def issue_code(request: Request) -> Response:
        presented = request.headers.get("x-api-key", "")
        if not secrets.compare_digest(presented, settings.cloudcredits_api_key):
            # If the vault placeholder arrives here unsubstituted, this is the error you see.
            return JSONResponse({"error": "invalid API key"}, status_code=401)
        try:
            body = IssueCodeRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=422)

        member = store.get_member(body.member_id)
        if member is None:
            return JSONResponse({"error": "unknown member"}, status_code=404)
        if "speaker" not in member["roles"]:
            return JSONResponse({"error": "perks are for accepted speakers"}, status_code=403)
        perk = store.issue_perk(body.member_id, body.amount_usd)
        return JSONResponse(
            {"member_id": body.member_id, "code": perk["code"], "amount_usd": perk["amount_usd"]}
        )

    return [Route("/credits/api/codes", issue_code, methods=["POST"])]
