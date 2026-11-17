"""Trusted Desktop-only endpoints for live Chat permission decisions."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from openjarvis.security.chat_permissions import broker, get_mode, set_mode
from openjarvis.security.confirmation import is_desktop_runtime

router = APIRouter(prefix="/v1/chat-permissions")


def desktop_only() -> None:
    # In a normal API deployment there is no local Desktop user to approve.
    if not is_desktop_runtime():
        raise HTTPException(status_code=403, detail="Desktop-only permissions")


class ModePayload(BaseModel):
    mode: Literal["autonomous", "guided"]


class DecisionPayload(BaseModel):
    allow: bool


@router.get("/mode")
def get_permission_mode() -> dict[str, str]:
    desktop_only()
    return {"mode": get_mode()}


@router.put("/mode")
def update_permission_mode(body: ModePayload) -> dict[str, str]:
    desktop_only()
    return {"mode": set_mode(body.mode)}


@router.get("/pending")
def pending_tool_permissions() -> dict[str, object]:
    desktop_only()
    return {"requests": broker.pending()}


@router.post("/{request_id}/decision")
def decide_tool_permission(request_id: str, body: DecisionPayload) -> dict[str, object]:
    desktop_only()
    # A UUID for one in-flight call; stale/duplicate requests always fail.
    if not broker.decide(request_id, body.allow):
        raise HTTPException(status_code=404, detail="Permission request expired")
    return {"id": request_id, "allowed": body.allow}
