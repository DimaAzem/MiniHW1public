# BoxDrop

A smart package-tracking, subscription-management, and exception-handling platform:
real JWT authentication, a Return-to-Sender expiry tracker, a greedy-TSP Smart Pickup
Route Optimizer, a Predictive Carrier Analytics engine, a validated order/email parser,
dynamic risk re-scoring with automatic exception flagging, and a real-time WebSocket
community forum. Built with FastAPI + MongoDB (backend) and Streamlit (frontend),
running as four network-isolated Docker containers plus a background worker.

## Architecture

```
boxdrop-backend/
├── backend/                 # FastAPI app
│   ├── main.py               # app entrypoint, middleware, exception handlers
│   ├── worker.py             # standalone process: periodic risk re-scoring (its own container)
│   ├── seed_data.py          # idempotent mock users/packages/forum posts
│   ├── api/                  # routers: auth, packages, routing, analytics, parser, exceptions, forum, test_hooks
│   ├── database/              # async MongoDB connection lifecycle
│   ├── services/               # auth, predictive_engine, route_optimizer, carrier_analytics,
│   │                           # order_parser, preference_service, forum_service
│   ├── middleware/              # global rate limiting
│   └── tests/                   # pytest suite (5 categories, see below)
├── frontend/                # Streamlit app
│   └── app.py
├── docker-compose.yml       # 4 services (+ worker), 2 networks (see Network Isolation below)
└── requirements.txt          # convenience file for a single local venv
```

### Network isolation

`docker-compose.yml` defines two Docker networks, not one:

- `public_net` — `frontend` and `backend` both attach here.
- `private_net` (`internal: true`, no route out) — only `backend` and `db` attach here.

`frontend` is **never** attached to `private_net`, so it has no possible network path to
MongoDB, even if compromised. This is enforced by Docker itself, not just by convention
(e.g. "we just don't call it from the frontend code").

## Running it

### Docker (recommended)

```bash
docker compose up --build
```

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:8501
- `db` has no ports published to the host at all — it's reachable only from `backend`.

Optionally, create a `.env` file (see `.env.example`) with a `JWT_SECRET_KEY` you generate
yourself. Without one, the backend falls back to a hardcoded dev-only secret — fine for a
quick local run, but sessions won't survive changing it, and it's not appropriate for
anything beyond a local demo.

Other optional `.env` flags:
- `SEED_ON_STARTUP=true` — populates mock users/packages/forum posts on backend startup
  (safe to leave on; idempotent, skips silently if data already exists).
- `ENABLE_TEST_ENDPOINTS=true` — exposes `/api/test/*` data-injection hooks for external test
  scripts. **Never set this in a real deployment** — these routes have no auth of their own.
  When unset (the default), the routes don't exist on the app at all (`404`, not `403`).
- `WORKER_INTERVAL_SECONDS` (default `30`) — how often the `worker` container re-scores
  in-flight packages.

### Without Docker

```bash
run.bat
```

Creates a local `.venv`, installs `requirements.txt` (which pulls in both
`backend/requirements.txt` and `frontend/requirements.txt`), then starts the FastAPI
backend and the Streamlit frontend in separate windows. Requires a MongoDB instance
reachable at `mongodb://localhost:27017/` (override via `MONGO_URI`).

## Testing

```bash
pytest
```

Runs the full suite in `backend/tests/` against an in-memory `mongomock_motor` database —
no live MongoDB needed. All 5 course-required test categories are covered:

| Category | File | What it proves |
|---|---|---|
| Unit | `test_unit_auth_service.py` | bcrypt hashing/verification, JWT create/decode + expiry, in isolation |
| Unit | `test_unit_route_optimizer.py` | Nearest-neighbor TSP correctness on a fixed graph |
| Unit | `test_unit_carrier_analytics.py` | Delay-forecast model stays in `[0,1]`, reaches genuinely high risk for bad combinations |
| Integration | `test_integration_auth.py` | Register → login through the real HTTP app + real DB queries |
| Integration | `test_integration_packages.py` | Package CRUD through the API; cross-user isolation |
| E2E / System | `test_e2e_user_journey.py` | One full flow: register → login → track packages → optimize route → predict delay |
| Stress | `test_stress_concurrent_requests.py` | 50 concurrent requests handled correctly; rate limiter genuinely returns `429` when exceeded |
| Security | `test_security_auth_required.py` | Protected routes reject missing/invalid tokens; a valid token for user A can't touch user B's data |
| Unit | `test_unit_order_parser.py` | Extraction + the anti-hallucination guardrail rejecting malformed tracking IDs and implausible dates |
| Unit | `test_unit_risk_rescoring.py` | The status-staleness signal correctly pushes an overdue package into "high" risk |
| Integration | `test_integration_forum.py` | Post/reply creation, anonymity never leaking the author, auth required |
| Integration | `test_integration_forum_ws.py` | WebSocket connect + real-time broadcast on a new post (Starlette `TestClient`) |
| Security | `test_security_forum_rate_limit.py` | Forum-specific per-user throttle returns `429`, independent of the global API limiter |
| Integration | `test_integration_test_hooks.py` | `/api/test/*` is a `404` by default; works correctly when `ENABLE_TEST_ENDPOINTS=true` |

## Key design notes

- **Passwords** are bcrypt-hashed, never stored in plaintext.
- **Sessions** are signed JWTs (`Authorization: Bearer <token>`), 24h expiry.
- **Every package** is scoped to its owning user (`user_id`) — enforced on every
  list/get/update/delete query, not just at creation.
- **Two separate predictive models, on purpose**: `predictive_engine.py` scores an
  already-created package and is intentionally conservative (~20% max), while
  `carrier_analytics.py` powers the pre-purchase Carrier Delay Predictor and is
  calibrated to reach genuinely high risk (~80-90%) for bad carrier/day/season
  combinations. They're not meant to agree — they answer different questions.
- **Route optimizer coordinates are simulated**, not real GPS — known Technion/Haifa
  locations get hand-placed coordinates; anything else gets a deterministic
  hash-derived coordinate so the algorithm works for any free-text location a user types.
- **Rate limiting** is a hand-rolled in-memory sliding window (no new dependency),
  exempting `/api/health` so container healthchecks are never throttled.
- **`expiry_hours_left`** (Return-to-Sender countdown) is computed at read-time from
  `arrival_date`, never stored — it can't go stale.
- **The order parser is a regex/heuristic extractor, not an LLM** — there's no generative
  model anywhere in this stack, so there's no LLM-style hallucination risk to guard against.
  "Anti-hallucination guardrail" here concretely means: every extracted field is checked
  against a business rule (tracking-ID format, delivery date within a sane range) before
  it's trusted, and rejected fields are reported back explicitly via `validation_errors`,
  never silently dropped. Parsing never writes to MongoDB by itself — the caller reviews the
  result and separately calls `POST /api/packages` to persist it.
- **A third, independent risk signal, not a third model**: `recompute_risk_with_status()`
  extends the *same* `predictive_engine.py` used at package creation with one new factor —
  how long a package has sat "In Transit" past its estimate — rather than introducing a
  competing model. The background `worker` container calls it on a schedule and only writes
  an `exceptions` record on a *new* crossing into "high" risk, so a still-high-risk package
  doesn't re-flood a user's exception feed every cycle.
- **The forum's WebSocket broadcast is single-process** — `ConnectionManager` is an in-memory
  set of open sockets in the `backend` container. Correct for this project's single-instance
  deployment; a horizontally-scaled deployment would need a pub/sub layer (e.g. Redis) to fan
  broadcasts out across processes.
- **The background worker polls MongoDB directly, no message broker** — consistent with this
  project's preference for hand-rolled solutions over new infrastructure where the scale
  doesn't warrant it (same reasoning as the rate limiter). It reuses the backend's own Docker
  image with a different `command`, so there's no second image to build or keep in sync.

## Known limitations

- The rate limiter's state isn't shared across processes — fine for this single-container
  setup, not suitable for a horizontally-scaled deployment as-is. The same is true of the
  forum's `ConnectionManager` and the forum-specific per-user rate limiter.
- No token revocation/blocklist — a JWT is valid until it expires (24h), even after logout.
- `/api/test/*` has no authentication of its own — it relies entirely on being absent unless
  `ENABLE_TEST_ENDPOINTS=true` is explicitly set. Never set that flag anywhere reachable by
  anyone other than your own test scripts.
