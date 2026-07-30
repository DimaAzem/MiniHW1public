"""
Real-Time Community Forum & Dispute Hub.

REST endpoints handle posting/listing; a WebSocket endpoint pushes new posts
to every connected client the instant they're created via POST
/api/forum/posts. Supports posting anonymously - the author is still stored
for moderation/rate-limiting purposes, it's just never returned in the API
response when the post is anonymous.
"""

import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user
from backend.database.connection import get_database
from backend.services.auth_service import InvalidTokenError, decode_access_token
from backend.services.forum_service import connection_manager

router = APIRouter()


class ForumRateLimitExceededError(Exception):
    def __init__(self) -> None:
        super().__init__("You're posting too quickly - please wait a bit before posting again.")


# ---------------------------------------------------------------------------
# Forum-specific rate limiting: a separate, stricter, per-USER (not per-IP)
# sliding window - distinct from the single global budget in
# backend/middleware/rate_limit.py, which applies one limit across the
# whole API. Demonstrates route-specific throttling as its own technique.
# ---------------------------------------------------------------------------
FORUM_POST_LIMIT = 5
FORUM_POST_WINDOW_SECONDS = 60.0
_forum_post_hits: dict[str, deque] = defaultdict(deque)


def enforce_forum_rate_limit(username: str = Depends(get_current_user)) -> str:
    now = time.monotonic()
    hits = _forum_post_hits[username]
    while hits and now - hits[0] > FORUM_POST_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= FORUM_POST_LIMIT:
        raise ForumRateLimitExceededError()
    hits.append(now)
    return username


class ForumPostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    reply_to: Optional[str] = None
    anonymous: bool = False


class ForumPostResponse(BaseModel):
    id: str
    display_name: str
    content: str
    reply_to: Optional[str] = None
    created_at: datetime


def _to_response(document: dict) -> ForumPostResponse:
    display_name = "Anonymous" if document.get("anonymous") else document["author_user_id"]
    return ForumPostResponse(
        id=document["_id"],
        display_name=display_name,
        content=document["content"],
        reply_to=document.get("reply_to"),
        created_at=document["created_at"],
    )


@router.post(
    "/forum/posts",
    response_model=ForumPostResponse,
    status_code=201,
    tags=["forum"],
    summary="Create a forum post or reply",
)
async def create_post(
    payload: ForumPostCreate,
    username: str = Depends(enforce_forum_rate_limit),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ForumPostResponse:
    document = {
        "_id": str(uuid.uuid4()),
        "author_user_id": username,
        "anonymous": payload.anonymous,
        "content": payload.content,
        "reply_to": payload.reply_to,
        "created_at": datetime.now(timezone.utc),
    }
    await db.forum_posts.insert_one(document)

    response = _to_response(document)
    await connection_manager.broadcast(response.model_dump(mode="json"))
    return response


@router.get(
    "/forum/posts",
    response_model=List[ForumPostResponse],
    tags=["forum"],
    summary="List forum posts",
)
async def list_posts(
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
    limit: int = Query(100, ge=1, le=500),
) -> List[ForumPostResponse]:
    cursor = db.forum_posts.find().sort("created_at", -1).limit(limit)
    documents = await cursor.to_list(length=limit)
    return [_to_response(doc) for doc in documents]


@router.websocket("/forum/ws")
async def forum_websocket(websocket: WebSocket, token: str = Query(...)) -> None:
    """
    Browsers/Streamlit can't attach custom headers to a WebSocket handshake,
    so the JWT travels as a query param instead - validated with the exact
    same decode_access_token() every REST route uses.
    """
    try:
        decode_access_token(token)
    except InvalidTokenError:
        await websocket.close(code=4401)
        return

    connection_id = str(uuid.uuid4())
    await connection_manager.connect(connection_id, websocket)
    try:
        while True:
            # No client->server messages are expected; this just keeps the
            # connection open (and detects disconnects) until the client leaves.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(connection_id)
