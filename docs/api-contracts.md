# DisasterLens — Backend API Contracts & Specification

> **Safety Notice & Research Prototype Disclaimer:**
> DisasterLens is a synthetic-data research prototype designed to evaluate computer vision hazard understanding and decision support. It is **not** a certified navigation, dispatch, or life-safety emergency system.
> The platform never claims that a road or route is "safe". A status of `CLEAR` indicates solely that **no obstruction was detected in imagery captured at a specific timestamp**. Satellite, drone, or ground imagery cannot establish water depth, roadbed stability, structural integrity, or official road closure mandates.

---

## 1. Overview & System Semantics

The DisasterLens backend provides a RESTful API built on FastAPI, SQLite (or PostgreSQL via SQLAlchemy), and NetworkX. It manages road graphs, ingests multi-source observations, calculates temporal freshness decay, executes observation fusion with conservative recovery gates, and computes condition-aware emergency route recommendations.

### 1.1 Base URL & Content Types
- Default Base URL: `http://localhost:8000/api` (configurable via `API_PREFIX` in `.env`).
- Standard Content-Type: `application/json`
- Ingestion Content-Type: Supports both `application/json` and `multipart/form-data` (with image attachment).

### 1.2 Simulated Clock & Timestamp Precedence
All routing and freshness calculations depend on deterministic temporal evaluation:
1. **Explicit Request Parameter (`as_of`):** Highest precedence. Overrides system clock for retrospective routing evaluations.
2. **Configured Simulated Time (`/api/clock`):** Active during scenario timeline demonstrations (T0–T3).
3. **Wall-Clock Fallback:** Real system UTC time, used only when neither simulated time nor an explicit `as_of` parameter is provided.

**Temporal Ordering Rule:** Observations are sorted and evaluated strictly by `captured_at` (the moment physical reality was photographed), never by `uploaded_at`. An older image uploaded later cannot supersede newer ground reality.

### 1.3 Vision Engine Operating Modes
Configured via `VISION_MODE` environment variable (`dl/vision/provider.py`):
- `mock` (**Fully Operational**): Deterministic mock oracle. Translates synthetic scene ground truth and scenario timeline steps (`scenarios/demo_city`) into validated segment observations. Observations are tagged `is_mock: true, model_id: "mock"`.
- `cached` (**Unavailable / Stubbed**): Reserved for pre-recorded vision cache repositories. Returns HTTP 500 `VisionProviderError`.
- `live` (**Unavailable / Stubbed**): Reserved for live model API inference (e.g., Gemini 1.5 Flash). Returns HTTP 500 `VisionProviderError` unless live API keys and network adapters are configured. Ground-truth mock data is **never** silently substituted for real model inference.

---

## 2. API Endpoints Specification

### 2.1 System Health

#### `GET /api/health`
Returns runtime status, database connectivity verification, and prototype disclaimer.

- **Request:** None
- **Response `200 OK`:**
```json
{
  "status": "healthy",
  "service": "DisasterLens Backend API",
  "version": "0.1.0",
  "database": "connected",
  "disclaimer": "DisasterLens is a research prototype evaluating disaster-scene hazard understanding on synthetic data. It is not certified for emergency dispatch or life-safety navigation. It never certifies a route as 'safe' and reports only that no obstruction was detected in evaluated imagery."
}
```

---

### 2.2 Cities & Road Network

#### `GET /api/cities`
Lists all seeded city environments available in the database.

- **Request:** None
- **Response `200 OK`:**
```json
[
  {
    "id": "DEMO-001",
    "name": "DisasterLens Demo City",
    "zone_count": 4,
    "intersection_count": 36,
    "segment_count": 60,
    "hazard_count": 2
  }
]
```

#### `GET /api/cities/{city_id}`
Retrieves complete structural topology, intersections, road segments, zones, and scene image URLs for a specific city.

- **Path Parameters:**
  - `city_id` (string, required): e.g. `DEMO-001`.
- **Response `200 OK`:**
```json
{
  "id": "DEMO-001",
  "name": "Disaster City Alpha",
  "grid_size": 6,
  "bounds": { "x_min": 0.0, "x_max": 1024.0, "y_min": 0.0, "y_max": 1024.0 },
  "zones": ["NE", "NW", "SE", "SW"],
  "scene_image_url": "/scenarios/demo_city/image_plain.png",
  "scene_image_urls": {
    "plain": "/scenarios/demo_city/image_plain.png",
    "labelled": "/scenarios/demo_city/image_labelled.png"
  },
  "graph": {
    "node_count": 36,
    "edge_count": 60,
    "is_connected": true
  },
  "intersections_count": 36,
  "segments_count": 60,
  "intersections": [
    { "id": "N1", "zone": "NW", "x": 0.0, "y": 0.0, "connected_segments": ["SEG-001", "SEG-006"] },
    { "id": "N36", "zone": "SE", "x": 1024.0, "y": 1024.0, "connected_segments": ["SEG-055", "SEG-060"] }
  ],
  "road_segments": [
    {
      "id": "SEG-001",
      "from_intersection": "N1",
      "to_intersection": "N2",
      "node_a": "N1",
      "node_b": "N2",
      "length_m": 34.56,
      "zone": "NW",
      "centerline": [{ "x": 0.0, "y": 0.0 }, { "x": 34.56, "y": 0.0 }],
      "polygon": [{ "x": 0.0, "y": -4.0 }, { "x": 34.56, "y": -4.0 }, { "x": 34.56, "y": 4.0 }, { "x": 0.0, "y": 4.0 }]
    }
  ]
}
```
- **Error `404 Not Found`:** If `city_id` does not exist.

---

### 2.3 Road Segment Conditions & Historical Audit

#### `GET /api/cities/{city_id}/segments`
Computes effective road condition, freshness category, and decay status for every road segment in a city, evaluated at `as_of` or the simulated clock.

- **Path Parameters:**
  - `city_id` (string, required): e.g. `DEMO-001`.
- **Query Parameters:**
  - `as_of` (ISO 8601 datetime string, optional): Reference evaluation timestamp (e.g. `2026-11-27T08:00:00Z`).
- **Response `200 OK`:**
```json
{
  "city_id": "DEMO-001",
  "as_of": "2026-11-27T08:00:00+00:00",
  "clock_mode": "simulated",
  "segments": {
    "SEG-001": {
      "segment_id": "SEG-001",
      "status": "BLOCKED",
      "freshness": "fresh",
      "age_hours": 0.0,
      "is_stale_from_blocked": false,
      "original_verdict": "BLOCKED",
      "captured_at": "2026-11-27T08:00:00+00:00"
    },
    "SEG-002": {
      "segment_id": "SEG-002",
      "status": "UNKNOWN",
      "freshness": "unknown",
      "age_hours": null,
      "is_stale_from_blocked": false,
      "original_verdict": null,
      "captured_at": null
    }
  }
}
```

#### `GET /api/segments/{segment_id}/history`
Retrieves the persistent, immutable audit trail of all historical observations recorded for a road segment.

- **Path Parameters:**
  - `segment_id` (string, required): e.g. `SEG-001`.
- **Query Parameters:**
  - `limit` (integer, default: 50, max: 200).
  - `offset` (integer, default: 0).
- **Response `200 OK`:**
```json
{
  "segment_id": "SEG-001",
  "count": 2,
  "limit": 50,
  "offset": 0,
  "history": [
    {
      "observation_id": "OBS-001",
      "source": "synthetic_camera_1",
      "zone": "NW",
      "verdict": "BLOCKED",
      "confidence": 0.95,
      "max_coverage": 1.0,
      "hazard_type": "flood",
      "near_miss": false,
      "recovery": false,
      "visibility": "full",
      "direct_verdict": "BLOCKED",
      "mapped_verdict": "BLOCKED",
      "captured_at": "2026-11-27T08:00:00+00:00",
      "uploaded_at": "2026-11-27T08:05:00+00:00",
      "evidence": "Synthetic flood covers >=90% of corridor width."
    }
  ]
}
```

---

### 2.4 Observation Ingestion

#### `POST /api/observations`
Ingests a single observation payload, persists it to the database, updates the in-memory fusion engine, and assesses impact on active saved routes. Accepts either a JSON body or a multipart form with an attached image file.

- **Option A: JSON Request Body (`application/json`)**
```json
{
  "observation_id": "OBS-FIELD-01",
  "segment_id": "SEG-001",
  "source": "drone_patrol_nw",
  "zone": "NW",
  "captured_at": "2026-11-27T08:30:00Z",
  "verdict": "BLOCKED",
  "confidence": 0.98,
  "max_coverage": 0.95,
  "hazard_type": "flood",
  "visibility": "full"
}
```
*(Note: `capture_time` is supported as an input alias for `captured_at`)*.

- **Option B: Multipart Form Upload (`multipart/form-data`)**
  - `image` (file, optional): PNG or JPEG file.
    - *Content validation:* Enforced via magic bytes (`\x89PNG` / `\xff\xd8\xff`) and Pillow `Image.verify()`. Corrupted, empty, or non-image files are rejected with `HTTP 400 Bad Request`.
    - *Size limits:* Maximum permitted file size is 10 MB (`MAX_UPLOAD_SIZE_BYTES = 10485760`). Oversized payloads are rejected with `HTTP 400 Bad Request`.
    - *Storage & Sanitization:* Server-controlled unique filename in `uploads/` (`{uuid4}_{timestamp}.{ext}`). Client filenames are sanitized to prevent directory traversal (`..`, null bytes, control characters).
    - *Persistence & Cleanup:* Saved relative path is recorded in `image_path` and original filename in `original_filename`. If database transaction fails, uploaded file is automatically deleted from disk.
  - `segment_id` (string, required): e.g. `SEG-001`. Must match `^SEG-\d{3}$`.
  - `source` (string, required): e.g. `patrol_uav_1`.
  - `zone` (string, required): `NW`, `NE`, `SW`, or `SE`.
  - `verdict` (string, required): `BLOCKED`, `PARTIAL`, `CLEAR`, or `UNCERTAIN`.
  - `confidence` (float, default: 1.0, range: [0.0, 1.0]).
  - `capture_time` or `captured_at` (ISO 8601 string, required): Must not be in the future relative to the simulated clock or current UTC timestamp.
  - `hazard_type` (string, optional): `flood`, `debris`, `fallen_tree`, `road_damage`.
  - `max_coverage` (float, optional, range: [0.0, 1.0]).
  - `visibility` (string, optional): `full`, `partial`, `obscured`.
  - `near_miss` (boolean, optional).
  - `recovery` (boolean, optional).

- **Response `200 OK`:**
```json
{
  "observation_id": "OBS-FIELD-01",
  "affected_segments": ["SEG-001"],
  "previous_statuses": { "SEG-001": "UNKNOWN" },
  "new_statuses": { "SEG-001": "BLOCKED" },
  "alerts": [
    {
      "route_id": "ROUTE-DISPATCH-01",
      "alert_type": "PRIMARY_NOW_BLOCKED",
      "segment_id": "SEG-001",
      "message": "Tracked route ROUTE-DISPATCH-01 is degraded: segment SEG-001 is now BLOCKED.",
      "severity": "critical"
    }
  ]
}
```
- **Error Status Codes:**
  - `400 Bad Request`: Future timestamps or invalid status transitions.
  - `422 Unprocessable Entity`: Missing required fields.

---

### 2.5 Route Recommendation Engine

#### `POST /api/routes/recommend`
Calculates shortest physical baseline, condition-aware recommended route (excluding fresh `BLOCKED` roads and penalizing aged/uncertain segments), and up to 2 alternative paths.

- **Request Body (`application/json`):**
```json
{
  "city_id": "DEMO-001",
  "origin": "N1",
  "destination": "N36",
  "as_of": "2026-11-27T08:00:00Z",
  "risk_mode": "normal",
  "save_as": "ROUTE-ACTIVE-DISPLAY",
  "route_name": "Active Display (N1->N36)"
}
```

- **Response `200 OK`:**
```json
{
  "origin": "N1",
  "destination": "N36",
  "as_of": "2026-11-27T08:00:00+00:00",
  "risk_mode": "normal",
  "baseline_route": {
    "rank": 0,
    "is_baseline": true,
    "node_path": ["N1", "N2", "N3", "N4", "N5", "N6", "N12", "N18", "N24", "N30", "N36"],
    "segment_path": ["SEG-001", "SEG-003", "SEG-005", "SEG-007", "SEG-009", "SEG-011", "SEG-022", "SEG-033", "SEG-044", "SEG-055"],
    "total_length_m": 1200.0,
    "total_cost": 3600.0,
    "unverified_segments_count": 9,
    "has_fresh_blocked": true,
    "is_valid": false,
    "steps": [...]
  },
  "recommended_route": {
    "rank": 1,
    "is_baseline": false,
    "node_path": ["N1", "N7", "N8", "N9", "N10", "N11", "N12", "N18", "N24", "N30", "N36"],
    "segment_path": ["SEG-002", "SEG-012", "SEG-014", "SEG-016", "SEG-018", "SEG-020", "SEG-022", "SEG-033", "SEG-044", "SEG-055"],
    "total_length_m": 1200.0,
    "total_cost": 3600.0,
    "unverified_segments_count": 10,
    "has_fresh_blocked": false,
    "is_valid": true,
    "steps": [...]
  },
  "alternatives": [...],
  "verification": {
    "is_valid": true,
    "is_connected": true,
    "starts_at_origin": true,
    "ends_at_destination": true,
    "has_fresh_blocked_segments": false,
    "blocked_segment_ids": [],
    "unverified_segment_ids": ["SEG-002", "SEG-012", "..."],
    "unverified_count": 10,
    "failure_reasons": []
  },
  "explanation": "Detour recommended avoiding confirmed blockage on SEG-001 (N1 -> N2). Recommended route proceeds via N1 -> N7 -> N8 -> ... -> N36 (+0.0 m distance vs baseline). Note: 10 segments rely on unverified priors or aged observations.",
  "warnings": [
    "Route includes 10 unverified or stale segment(s) (SEG-002, SEG-012, SEG-014, ...). Road conditions have not been confirmed by recent imagery."
  ]
}
```
- **Special Conditions:**
  - If all connecting corridors are blocked: `recommended_route` is `null`, `verification.is_valid` is `false`, and `verification.failure_reasons` contains `["CONTAINS_FRESH_BLOCKED_SEGMENTS", "NO_PATH_FOUND"]`.
  - Origin equals destination: Returns zero-length, zero-cost valid path.

---

### 2.6 Scenario Playback & Orchestration

#### `GET /api/scenarios`
Lists available disaster demonstration scenarios.

- **Response `200 OK`:**
```json
[
  {
    "id": "demo_city",
    "city_id": "DEMO-001",
    "description": "DisasterLens demonstration city — 6x6 grid with T0-T3 timeline.",
    "current_time_step": "T0",
    "current_simulated_time": null
  }
]
```

#### `GET /api/scenarios/{scenario_id}`
Returns scenario metadata, camera viewports, and timeline event definitions.

- **Path Parameters:**
  - `scenario_id` (string, required): e.g. `demo_city`.
- **Response `200 OK`:**
```json
{
  "id": "demo_city",
  "city_id": "DEMO-001",
  "description": "...",
  "current_time_step": "T0",
  "current_simulated_time": null,
  "cameras": [...],
  "timeline_events": [
    { "time_step": "T0", "timestamp": null, "description": "No observations. All roads UNKNOWN.", "observations_count": 0 },
    { "time_step": "T1", "timestamp": "2026-11-27T08:00:00+05:30", "description": "Flood detected across SEG-001. Status: BLOCKED.", "observations_count": 1 },
    { "time_step": "T2", "timestamp": "2026-11-27T09:00:00+05:30", "description": "Debris detected beside SEG-005 (near-miss). Status: CLEAR.", "observations_count": 1 },
    { "time_step": "T3", "timestamp": "2026-11-27T10:00:00+05:30", "description": "Flood receding on SEG-001. Status: UNCERTAIN.", "observations_count": 1 }
  ]
}
```

#### `POST /api/scenarios/{scenario_id}/advance`
Advances or resets the scenario timeline step (e.g. T0 → T1 → T2 → T3 or T3 → T1 backward navigation). Ingests timeline observations, updates the simulated clock, and evaluates route alerts.

- **Request Body (optional):**
```json
{
  "time_step": "T1"
}
```
*(If omitted, advances to next step in sequence).*

- **Response `200 OK`:**
```json
{
  "scenario_id": "demo_city",
  "time_step": "T1",
  "timestamp": "2026-11-27T02:30:00+00:00",
  "description": "Flood detected across SEG-001. Expected outcome: BLOCKED. Saved route raises an alert.",
  "observations_count": 1,
  "affected_segments": ["SEG-001"],
  "previous_statuses": { "SEG-001": "UNKNOWN" },
  "new_statuses": { "SEG-001": "BLOCKED" },
  "alerts": [
    {
      "route_id": "ROUTE-DISPATCH-01",
      "alert_type": "PRIMARY_NOW_BLOCKED",
      "segment_id": "SEG-001",
      "message": "Tracked route ROUTE-DISPATCH-01 is degraded: segment SEG-001 is now BLOCKED.",
      "severity": "critical"
    }
  ]
}
```
*(When reset to `T0`, `timestamp` is `null`, and the clock switches to `wall-clock` mode).*

---

### 2.7 Simulated Clock

#### `GET /api/clock`
Queries current clock operating mode and timestamps.

- **Response `200 OK`:**
```json
{
  "clock_mode": "simulated",
  "simulated_time": "2026-11-27T02:30:00+00:00",
  "wall_clock_time": "2026-11-23T05:58:00+00:00",
  "reference_time": "2026-11-27T02:30:00+00:00"
}
```

#### `POST /api/clock`
Manually sets or resets the simulated clock time.

- **Request Body:**
```json
{
  "simulated_time": "2026-11-27T12:00:00Z"
}
```
*(Pass `null` to reset to wall-clock mode).*

- **Response `200 OK`:** Same structure as `GET /api/clock`.

---

## 3. Freshness & Routing Cost Reference Table

Freshness categories and routing penalty multipliers are configured in `dl/routing/freshness.yaml`:

| Condition | Freshness | Age Window | Avoided? | Cost Multiplier | Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **CLEAR** | Fresh | Age $\le$ 3.0 h | No | 1.0× | Confirmed unobstructed carriageway |
| **CLEAR** | Ageing | 3.0 h < Age $\le$ 12.0 h | No | 1.5× | Minor decay penalty |
| **CLEAR** | Stale | Age > 12.0 h | No | 3.0× | Degrades to stale baseline |
| **PARTIAL** | Fresh | Age $\le$ 12.0 h | No | 1.5× | Partial encroachment (30–90% width) |
| **UNCERTAIN** | Fresh | Age $\le$ 12.0 h | No | 4.0× | Conflicting or weak recovery evidence |
| **UNKNOWN** | Unknown | No observations | No | 3.0× | Cautious baseline exploration penalty |
| **STALE** | Stale | Exceeded threshold | No | 3.0× | General decayed prior |
| **STALE** | Stale (From Blocked) | Prior BLOCKED > 24.0 h | No | **8.0×** | Heavily penalized; advisory warning emitted |
| **BLOCKED** | Fresh | Age $\le$ 24.0 h | **Yes** | **$\infty$ (Excluded)** | Pathfinding algorithm prunes edge completely |
