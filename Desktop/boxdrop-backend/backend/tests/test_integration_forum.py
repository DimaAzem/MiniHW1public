"""
Integration tests: forum post/reply creation and listing through the real
ASGI app and real Motor queries against mongomock.
"""

import pytest


@pytest.mark.asyncio
async def test_create_and_list_post(authed_client):
    client, headers = authed_client
    response = await client.post(
        "/api/forum/posts", json={"content": "Hello forum", "anonymous": False}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "Hello forum"
    assert body["display_name"] == "test_user_1"

    listing = await client.get("/api/forum/posts", headers=headers)
    assert listing.status_code == 200
    assert any(post["id"] == body["id"] for post in listing.json())


@pytest.mark.asyncio
async def test_anonymous_post_never_reveals_the_author(authed_client):
    client, headers = authed_client
    response = await client.post(
        "/api/forum/posts", json={"content": "Anonymous gripe", "anonymous": True}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "Anonymous"
    assert "author_user_id" not in body
    assert "test_user_1" not in response.text


@pytest.mark.asyncio
async def test_reply_references_the_parent_post(authed_client):
    client, headers = authed_client
    root = await client.post("/api/forum/posts", json={"content": "Root post", "anonymous": False}, headers=headers)
    root_id = root.json()["id"]

    reply = await client.post(
        "/api/forum/posts", json={"content": "A reply", "reply_to": root_id, "anonymous": False}, headers=headers
    )
    assert reply.status_code == 201
    assert reply.json()["reply_to"] == root_id


@pytest.mark.asyncio
async def test_forum_requires_authentication(client):
    post_response = await client.post("/api/forum/posts", json={"content": "no auth", "anonymous": False})
    assert post_response.status_code == 401

    list_response = await client.get("/api/forum/posts")
    assert list_response.status_code == 401
