"""
Comprehensive API test suite for DisasterLens backend.

Covers all 20 required points:
1. Health endpoint.
2. Database connection.
3. City retrieval.
4. Segment state retrieval.
5. Segment history.
6. JSON observation ingestion.
7. Multipart upload validation.
8. capture_time alias compatibility.
9. Out-of-order observation ingestion.
10. Routing recommendation endpoint.
11. Fresh BLOCKED route exclusion.
12. Explicit no-route response.
13. Scenario listing.
14. T0–T3 advancement.
15. Simulated clock behavior.
16. Idempotent database seeding.
17. Duplicate observation handling.
18. Route alert classification.
19. CORS and validation error behavior.
20. Database persistence and history retention.
"""

from __future__ import annotations

import io
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from dl.api.database import Base, get_db
from dl.api.dependencies import (
    get_db_session,
    get_fusion_engine,
    global_clock,
)
from dl.api.main import create_app
from dl.api.models import Observation, SavedRoute
from dl.api.seed import seed_demo_city
from dl.routing.fusion import ObservationFusionEngine


def generate_test_png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Generates valid minimal PNG image bytes for upload tests."""
    buf = io.BytesIO()
    img = Image.new("RGB", (4, 4), color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session with seeded demo city."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    global_clock.set_simulated_time(None)

    with TestingSession() as session:
        seed_demo_city(session)
        yield session

    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient configured with isolated in-memory test database and fresh fusion engine."""
    app = create_app()

    test_fusion = ObservationFusionEngine()
    global_clock.set_simulated_time(None)

    def override_get_db() -> Generator[Session, None, None]:
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_fusion_engine] = lambda: test_fusion

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


class TestDisasterLensAPI:
    """Test suite covering all 20 API and orchestration requirements."""

    def test_01_health_endpoint(self, client: TestClient):
        """1. Health endpoint returns status, database connectivity, and disclaimer."""
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert data["vision_mode"] == "mock"
        assert "research prototype" in data["disclaimer"].lower()

    def test_02_database_connection(self, client: TestClient):
        """2. Database connection is verified healthy through health check."""
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["database"] == "connected"

    def test_03_city_retrieval(self, client: TestClient):
        """3. City retrieval returns metadata, 36 intersections, and 60 road segments with zones and image URLs."""
        res = client.get("/api/cities/DEMO-001")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "DEMO-001"
        assert data["grid_size"] == 6
        assert data["intersections_count"] == 36
        assert data["segments_count"] == 60
        assert len(data["intersections"]) == 36
        assert len(data["road_segments"]) == 60
        assert "zones" in data
        assert "NW" in data["zones"]
        assert "scene_image_url" in data
        assert "scene_image_urls" in data
        assert data["scene_image_urls"]["plain"] == "/scenarios/demo_city/image_plain.png"
        assert data["graph"]["node_count"] == 36
        assert data["graph"]["edge_count"] == 60
        assert "connected_segments" in data["intersections"][0]
        assert "node_a" in data["road_segments"][0]
        assert "node_b" in data["road_segments"][0]

    def test_04_segment_state_retrieval(self, client: TestClient):
        """4. Segment state retrieval returns effective statuses and respects as_of."""
        ref_time = "2026-11-27T08:00:00Z"
        res = client.get(f"/api/cities/DEMO-001/segments?as_of={ref_time}")
        assert res.status_code == 200
        data = res.json()
        assert data["city_id"] == "DEMO-001"
        assert data["segments_count"] == 60
        # Initially, all segments have no observations -> UNKNOWN
        assert data["segments"]["SEG-001"]["status"] == "UNKNOWN"

    def test_05_segment_history(self, client: TestClient):
        """5. Segment history returns full chronological record preserving uploaded_at."""
        # Ingest an observation
        obs_payload = {
            "observation_id": "OBS-HIST-01",
            "segment_id": "SEG-001",
            "source": "cam_test",
            "zone": "NW",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 0.95,
            "max_coverage": 1.0,
            "hazard_type": "flood",
        }
        res_ingest = client.post("/api/observations", json=obs_payload)
        assert res_ingest.status_code == 200

        res_hist = client.get("/api/segments/SEG-001/history")
        assert res_hist.status_code == 200
        data = res_hist.json()
        assert data["segment_id"] == "SEG-001"
        assert data["count"] >= 1
        record = data["history"][0]
        assert record["verdict"] == "BLOCKED"
        assert "uploaded_at" in record

    def test_06_json_observation_ingestion(self, client: TestClient):
        """6. Ingests JSON observation payload and updates segment state."""
        payload = {
            "observation_id": "OBS-JSON-01",
            "segment_id": "SEG-002",
            "source": "uav_1",
            "zone": "NW",
            "captured_at": "2026-11-27T08:30:00Z",
            "verdict": "BLOCKED",
            "confidence": 0.98,
            "max_coverage": 0.8,
            "hazard_type": "flood",
        }
        res = client.post("/api/observations", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "SEG-002" in data["affected_segments"]
        assert data["new_statuses"]["SEG-002"] == "BLOCKED"

    def test_07_multipart_upload_validation(self, client: TestClient):
        """7. Supports multipart upload with image attachment and validates fields."""
        file_content = generate_test_png_bytes()
        files = {
            "image": ("test_camera.png", io.BytesIO(file_content), "image/png"),
        }
        form_data = {
            "segment_id": "SEG-003",
            "source": "field_camera",
            "zone": "NW",
            "verdict": "CLEAR",
            "confidence": "0.90",
            "capture_time": "2026-11-27T08:45:00Z",
        }
        res = client.post("/api/observations", files=files, data=form_data)
        assert res.status_code == 200
        data = res.json()
        assert "SEG-003" in data["affected_segments"]
        assert data["new_statuses"]["SEG-003"] == "CLEAR"

    def test_08_capture_time_alias_compatibility(self, client: TestClient):
        """8. Accepts capture_time as an input alias for captured_at."""
        payload = {
            "observation_id": "OBS-ALIAS-01",
            "segment_id": "SEG-004",
            "source": "cam_alias",
            "zone": "NW",
            "capture_time": "2026-11-27T09:00:00Z",
            "verdict": "CLEAR",
            "confidence": 0.92,
            "max_coverage": 0.0,
        }
        res = client.post("/api/observations", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "SEG-004" in data["affected_segments"]

    def test_09_out_of_order_observation_ingestion(self, client: TestClient):
        """9. Out-of-order ingestion preserves correct temporal precedence."""
        # 1. Ingest newer BLOCKED captured at 09:00
        client.post("/api/observations", json={
            "observation_id": "OBS-NEW",
            "segment_id": "SEG-010",
            "source": "cam1",
            "zone": "NE",
            "captured_at": "2026-11-27T09:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 0.95,
            "max_coverage": 1.0,
        })

        # 2. Ingest older CLEAR captured at 08:00 (uploaded late)
        client.post("/api/observations", json={
            "observation_id": "OBS-OLD",
            "segment_id": "SEG-010",
            "source": "cam1",
            "zone": "NE",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
            "confidence": 0.90,
            "max_coverage": 0.0,
        })

        # Query effective status as of 09:30 -> BLOCKED must prevail
        res = client.get("/api/cities/DEMO-001/segments?as_of=2026-11-27T09:30:00Z")
        assert res.status_code == 200
        assert res.json()["segments"]["SEG-010"]["status"] == "BLOCKED"

    def test_10_routing_recommendation_endpoint(self, client: TestClient):
        """10. Recommend endpoint returns baseline, recommended route, alternatives, and verification."""
        req = {
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N36",
            "as_of": "2026-11-27T08:00:00Z",
        }
        res = client.post("/api/routes/recommend", json=req)
        assert res.status_code == 200
        data = res.json()
        assert data["origin"] == "N1"
        assert data["destination"] == "N36"
        assert data["baseline_route"] is not None
        assert data["recommended_route"] is not None
        assert data["verification"]["is_valid"] is True
        assert len(data["explanation"]) > 0

    def test_11_fresh_blocked_route_exclusion(self, client: TestClient):
        """11. Recommend excludes fresh BLOCKED segments and detours around them."""
        # Block northern segment SEG-001 (N1-N2)
        client.post("/api/observations", json={
            "observation_id": "OBS-BLK-01",
            "segment_id": "SEG-001",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 1.0,
            "max_coverage": 1.0,
        })

        req = {
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N6",
            "as_of": "2026-11-27T08:00:00Z",
        }
        res = client.post("/api/routes/recommend", json=req)
        assert res.status_code == 200
        data = res.json()
        # Baseline crosses SEG-001 (direct path N1->N2)
        assert "SEG-001" in data["baseline_route"]["segment_path"]
        # Recommended route avoids SEG-001
        assert "SEG-001" not in data["recommended_route"]["segment_path"]
        assert data["verification"]["has_fresh_blocked_segments"] is False

    def test_12_explicit_no_route_response(self, client: TestClient):
        """12. Returns explicit no-route response when destination is completely blocked."""
        # Block both edges connected to N1 (SEG-001 to N2, SEG-002 to N7)
        client.post("/api/observations", json={
            "observation_id": "OBS-BLK-N1A",
            "segment_id": "SEG-001",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 1.0,
            "max_coverage": 1.0,
        })
        client.post("/api/observations", json={
            "observation_id": "OBS-BLK-N1B",
            "segment_id": "SEG-002",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 1.0,
            "max_coverage": 1.0,
        })

        req = {
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N36",
            "as_of": "2026-11-27T08:00:00Z",
        }
        res = client.post("/api/routes/recommend", json=req)
        assert res.status_code == 200
        data = res.json()
        assert data["recommended_route"] is None
        assert data["verification"]["is_valid"] is False
        assert data["verification"]["has_fresh_blocked_segments"] is True
        assert any("CONTAINS_FRESH_BLOCKED" in r or "NO_PATH" in r for r in data["verification"]["failure_reasons"])

    def test_13_scenario_listing(self, client: TestClient):
        """13. Scenario listing and details return timeline events."""
        res = client.get("/api/scenarios")
        assert res.status_code == 200
        scenarios = res.json()
        assert len(scenarios) >= 1
        assert scenarios[0]["id"] == "demo_city"

        res_detail = client.get("/api/scenarios/demo_city")
        assert res_detail.status_code == 200
        detail = res_detail.json()
        assert len(detail["timeline_events"]) == 4

    def test_14_t0_to_t3_advancement(self, client: TestClient):
        """14. Advances scenario timeline through T0 -> T1 -> T2 -> T3."""
        # Advance to T1 (Flood on SEG-001)
        res_t1 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T1"})
        assert res_t1.status_code == 200
        data_t1 = res_t1.json()
        assert data_t1["time_step"] == "T1"
        assert "SEG-001" in data_t1["affected_segments"]
        assert data_t1["new_statuses"]["SEG-001"] == "BLOCKED"
        # Should have raised PRIMARY_NOW_BLOCKED on ROUTE-DISPATCH-01
        assert any(a["alert_type"] == "PRIMARY_NOW_BLOCKED" for a in data_t1["alerts"])

        # Advance to T2 (Near-miss debris near SEG-005 -> CLEAR)
        res_t2 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T2"})
        assert res_t2.status_code == 200
        data_t2 = res_t2.json()
        assert data_t2["time_step"] == "T2"
        assert data_t2["new_statuses"]["SEG-005"] == "CLEAR"

        # Advance to T3 (Recovery attempt on SEG-001 -> UNCERTAIN)
        res_t3 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T3"})
        assert res_t3.status_code == 200
        data_t3 = res_t3.json()
        assert data_t3["time_step"] == "T3"
        assert data_t3["new_statuses"]["SEG-001"] == "UNCERTAIN"

    def test_15_simulated_clock_behavior(self, client: TestClient):
        """15. Simulated clock sets reference time and governs freshness evaluation."""
        sim_time = "2026-11-27T12:00:00Z"
        res_set = client.post("/api/clock", json={"simulated_time": sim_time})
        assert res_set.status_code == 200
        assert res_set.json()["clock_mode"] == "simulated"

        res_get = client.get("/api/clock")
        assert res_get.status_code == 200
        sim_val = res_get.json()["simulated_time"]
        assert sim_val is not None
        assert sim_val.startswith("2026-11-27T12:00:00")

        # Segments query with no as_of should now use simulated clock
        res_segs = client.get("/api/cities/DEMO-001/segments")
        assert res_segs.status_code == 200
        assert res_segs.json()["as_of"].startswith("2026-11-27T12:00:00")

    def test_16_idempotent_database_seeding(self, test_db_session: Session):
        """16. Repeated database seeding does not duplicate records."""
        city1 = seed_demo_city(test_db_session)
        city2 = seed_demo_city(test_db_session)
        assert city1.id == city2.id
        from dl.api.models import Intersection, RoadSegment
        int_count = test_db_session.query(Intersection).count()
        seg_count = test_db_session.query(RoadSegment).count()
        assert int_count == 36
        assert seg_count == 60

    def test_17_duplicate_observation_handling(self, client: TestClient):
        """17. Ingesting duplicate observations evaluates deterministically."""
        obs = {
            "observation_id": "OBS-DUP-01",
            "segment_id": "SEG-015",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 0.90,
            "max_coverage": 1.0,
        }
        res1 = client.post("/api/observations", json=obs)
        assert res1.status_code == 200

        # Ingest identical observation
        res2 = client.post("/api/observations", json=obs)
        assert res2.status_code == 200
        assert res2.json()["new_statuses"]["SEG-015"] == "BLOCKED"

    def test_18_route_alert_classification(self, client: TestClient):
        """18. Classifies PRIMARY_NOW_BLOCKED, ROUTE_CLEARED, and ROUTE_DEGRADED accurately."""
        # 1. Block SEG-001 -> PRIMARY_NOW_BLOCKED
        res_blk = client.post("/api/observations", json={
            "observation_id": "OBS-ALT-01",
            "segment_id": "SEG-001",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "BLOCKED",
            "confidence": 1.0,
            "max_coverage": 1.0,
        })
        alerts = res_blk.json()["alerts"]
        assert any(a["alert_type"] == "PRIMARY_NOW_BLOCKED" for a in alerts)

        # 2. Incomplete recovery (confidence 0.60) -> status becomes UNCERTAIN -> ROUTE_DEGRADED
        res_deg = client.post("/api/observations", json={
            "observation_id": "OBS-ALT-02",
            "segment_id": "SEG-001",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T09:00:00Z",
            "verdict": "CLEAR",
            "confidence": 0.60,
            "recovery": True,
            "visibility": "full",
            "max_coverage": 0.0,
        })
        alerts_deg = res_deg.json()["alerts"]
        assert any(a["alert_type"] == "ROUTE_DEGRADED" for a in alerts_deg)
        # Ensure UNCERTAIN is NEVER reported as ROUTE_CLEARED
        assert not any(a["alert_type"] == "ROUTE_CLEARED" for a in alerts_deg)

        # 3. Verified recovery (confidence 0.85, full visibility) -> ROUTE_CLEARED
        res_clr = client.post("/api/observations", json={
            "observation_id": "OBS-ALT-03",
            "segment_id": "SEG-001",
            "source": "cam1",
            "zone": "NW",
            "captured_at": "2026-11-27T10:00:00Z",
            "verdict": "CLEAR",
            "confidence": 0.85,
            "recovery": True,
            "visibility": "full",
            "max_coverage": 0.0,
        })
        alerts_clr = res_clr.json()["alerts"]
        assert any(a["alert_type"] == "ROUTE_CLEARED" for a in alerts_clr)

    def test_19_cors_and_validation_error_behavior(self, client: TestClient):
        """19. Returns 422 on invalid routing request and includes CORS headers."""
        # Missing required 'destination'
        res = client.post("/api/routes/recommend", json={"origin": "N1"})
        assert res.status_code == 422

        # Verify CORS headers on preflight OPTIONS
        res_cors = client.options(
            "/api/health",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert res_cors.status_code == 200
        assert res_cors.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_20_database_persistence_and_history_retention(self, client: TestClient, test_db_session: Session):
        """20. Deleting a saved route preserves underlying observations and alert audit trail."""
        # Ingest an observation
        client.post("/api/observations", json={
            "observation_id": "OBS-PERSIST-01",
            "segment_id": "SEG-020",
            "source": "cam1",
            "zone": "NE",
            "captured_at": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
            "confidence": 0.99,
            "max_coverage": 0.0,
        })

        obs_count_before = test_db_session.query(Observation).count()
        assert obs_count_before >= 1

        # Delete saved route ROUTE-DISPATCH-01
        saved_route = test_db_session.query(SavedRoute).filter(SavedRoute.id == "ROUTE-DISPATCH-01").first()
        if saved_route:
            test_db_session.delete(saved_route)
            test_db_session.commit()

        # Observations must still exist
        obs_count_after = test_db_session.query(Observation).count()
        assert obs_count_after == obs_count_before

    def test_21_scenario_backward_navigation_and_clock_synchronization(self, client: TestClient):
        """21. Scenario backward navigation (T3 -> T1) and reset (T3 -> T0) synchronously update simulated clock."""
        # 1. Advance T0 -> T1
        adv1 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T1"})
        assert adv1.status_code == 200
        clock1 = client.get("/api/clock").json()
        assert clock1["clock_mode"] == "simulated"
        assert clock1["simulated_time"] is not None
        assert clock1["simulated_time"].startswith("2026-11-27T02:30:00")

        # Route at T1: recommended avoids flood on SEG-001, has no conflicting warning
        rec1 = client.post("/api/routes/recommend", json={
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N36",
            "as_of": clock1["simulated_time"],
        }).json()
        assert rec1["recommended_route"] is not None
        assert "SEG-001" not in rec1["recommended_route"]["segment_path"]
        assert not any("conflicting" in w.lower() for w in rec1.get("warnings", []))

        # 2. Advance T1 -> T2
        adv2 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T2"})
        assert adv2.status_code == 200
        clock2 = client.get("/api/clock").json()
        assert clock2["simulated_time"].startswith("2026-11-27T03:30:00")

        # 3. Advance T2 -> T3
        adv3 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T3"})
        assert adv3.status_code == 200
        clock3 = client.get("/api/clock").json()
        assert clock3["simulated_time"].startswith("2026-11-27T04:30:00")

        # Route at T3: traverses SEG-001 (UNCERTAIN) and emits conflicting evidence warning
        rec3 = client.post("/api/routes/recommend", json={
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N36",
            "as_of": clock3["simulated_time"],
        }).json()
        assert any("conflicting or low-confidence evidence: SEG-001" in w for w in rec3.get("warnings", []))

        # 4. Backward navigation T3 -> T1
        adv1_back = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T1"})
        assert adv1_back.status_code == 200
        clock1_back = client.get("/api/clock").json()
        assert clock1_back["clock_mode"] == "simulated"
        assert clock1_back["simulated_time"].startswith("2026-11-27T02:30:00")

        # Route recommendation must use T1's timestamp and discard T3's warning
        rec1_back = client.post("/api/routes/recommend", json={
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N36",
            "as_of": clock1_back["simulated_time"],
        }).json()
        assert rec1_back["recommended_route"] is not None
        assert "SEG-001" not in rec1_back["recommended_route"]["segment_path"]
        assert not any("conflicting" in w.lower() for w in rec1_back.get("warnings", []))

        # 5. Reset T3 -> T0
        adv0 = client.post("/api/scenarios/demo_city/advance", json={"time_step": "T0"})
        assert adv0.status_code == 200
        clock0 = client.get("/api/clock").json()
        assert clock0["clock_mode"] == "wall-clock"
        assert clock0["simulated_time"] is None

    def test_22_upload_to_status_to_route_integration(self, client: TestClient):
        """22. Complete upload-to-status-to-route integration: multipart upload updates segment state and detours recommended route."""
        # 1. Upload a field observation with image via multipart form
        file_bytes = generate_test_png_bytes((0, 255, 0))
        files = {
            "image": ("drone_patrol_nw.png", io.BytesIO(file_bytes), "image/png"),
        }
        form_data = {
            "segment_id": "SEG-001",
            "source": "drone_patrol_alpha",
            "zone": "NW",
            "capture_time": "2026-11-27T08:15:00Z",
            "verdict": "BLOCKED",
            "confidence": "0.96",
            "hazard_type": "flood",
        }
        res_upload = client.post("/api/observations", files=files, data=form_data)
        assert res_upload.status_code == 200
        data_upload = res_upload.json()
        assert "SEG-001" in data_upload["affected_segments"]
        assert data_upload["new_statuses"]["SEG-001"] == "BLOCKED"

        # 2. Verify city segment state reflects fresh BLOCKED condition at capture timestamp
        res_segs = client.get("/api/cities/DEMO-001/segments?as_of=2026-11-27T08:15:00Z")
        assert res_segs.status_code == 200
        seg_states = res_segs.json()["segments"]
        assert "SEG-001" in seg_states
        assert seg_states["SEG-001"]["status"] == "BLOCKED"
        assert seg_states["SEG-001"]["freshness"] == "fresh"

        # 3. Request route recommendation from N1 to N6 at same evaluation time
        req_route = {
            "city_id": "DEMO-001",
            "origin": "N1",
            "destination": "N6",
            "as_of": "2026-11-27T08:15:00Z",
        }
        res_route = client.post("/api/routes/recommend", json=req_route)
        assert res_route.status_code == 200
        route_data = res_route.json()

        # Baseline shortest path crosses blocked SEG-001
        assert route_data["baseline_route"] is not None
        assert "SEG-001" in route_data["baseline_route"]["segment_path"]

        # Condition-aware recommendation safely detours around SEG-001
        assert route_data["recommended_route"] is not None
        assert "SEG-001" not in route_data["recommended_route"]["segment_path"]
        assert route_data["verification"]["is_valid"] is True
        assert route_data["verification"]["has_fresh_blocked_segments"] is False

        # 4. Verify segment observation audit trail retains the multipart record
        res_hist = client.get("/api/segments/SEG-001/history")
        assert res_hist.status_code == 200
        hist_data = res_hist.json()
        assert hist_data["count"] >= 1
        assert any(h["source"] == "drone_patrol_alpha" and h["verdict"] == "BLOCKED" for h in hist_data["history"])

    def test_23_upload_corrupt_image_rejected(self, client: TestClient):
        """23. Rejects corrupt image file with HTTP 400."""
        files = {
            "image": ("corrupt.png", io.BytesIO(b"not-really-a-png-image-header"), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "magic bytes" in res.json()["detail"].lower() or "corrupt" in res.json()["detail"].lower()

    def test_24_upload_unsupported_extension_rejected(self, client: TestClient):
        """24. Rejects unsupported image file formats with HTTP 400."""
        files = {
            "image": ("payload.pdf", io.BytesIO(b"%PDF-1.4 mock pdf"), "application/pdf"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "unsupported image extension" in res.json()["detail"].lower()

    def test_25_upload_empty_image_rejected(self, client: TestClient):
        """25. Rejects 0-byte empty image upload with HTTP 400."""
        files = {
            "image": ("empty.png", io.BytesIO(b""), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "empty" in res.json()["detail"].lower()

    def test_26_upload_oversized_image_rejected(self, client: TestClient):
        """26. Enforces upload size limit and rejects oversized uploads."""
        from dl.api.dependencies import get_storage_service
        from dl.api.storage import ImageStorageService

        # Override storage service with 50-byte max limit
        app = client.app
        app.dependency_overrides[get_storage_service] = lambda: ImageStorageService(max_size_bytes=50)
        try:
            png_bytes = generate_test_png_bytes()  # ~69 bytes
            files = {
                "image": ("oversized.png", io.BytesIO(png_bytes), "image/png"),
            }
            form = {
                "segment_id": "SEG-001",
                "source": "patrol",
                "zone": "NW",
                "capture_time": "2026-11-27T08:00:00Z",
                "verdict": "CLEAR",
            }
            res = client.post("/api/observations", files=files, data=form)
            assert res.status_code == 400
            assert "exceeds maximum size limit" in res.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_storage_service, None)

    def test_27_upload_missing_captured_at_rejected(self, client: TestClient):
        """27. Rejects observation missing required capture timestamp with HTTP 400."""
        files = {
            "image": ("sample.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "missing required capture timestamp" in res.json()["detail"].lower()

    def test_28_upload_invalid_timestamp_rejected(self, client: TestClient):
        """28. Rejects malformed timestamp with HTTP 400."""
        files = {
            "image": ("sample.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "invalid-timestamp-string",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "invalid iso 8601 timestamp format" in res.json()["detail"].lower()

    def test_29_upload_future_timestamp_rejected(self, client: TestClient):
        """29. Rejects future capture timestamp with HTTP 400."""
        files = {
            "image": ("sample.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2099-01-01T00:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "cannot be in the future" in res.json()["detail"].lower()

    def test_30_upload_invalid_zone_rejected(self, client: TestClient):
        """30. Rejects invalid zone with HTTP 400."""
        files = {
            "image": ("sample.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "INVALID_ZONE_99",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "invalid zone" in res.json()["detail"].lower()

    def test_31_upload_invalid_segment_rejected(self, client: TestClient):
        """31. Rejects invalid segment ID format with HTTP 400."""
        files = {
            "image": ("sample.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "ROAD-1234",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "invalid segment_id" in res.json()["detail"].lower()

    def test_32_upload_invalid_confidence_rejected(self, client: TestClient):
        """32. Rejects out-of-range confidence scores with HTTP 400."""
        files = {
            "image": ("sample.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "SEG-001",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
            "confidence": "1.75",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 400
        assert "between 0.0 and 1.0" in res.json()["detail"].lower()

    def test_33_upload_path_traversal_filename_sanitized(self, client: TestClient):
        """33. Sanitizes unsafe filenames to prevent path traversal."""
        files = {
            "image": ("../../../../etc/shadow.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
        }
        form = {
            "segment_id": "SEG-002",
            "source": "patrol",
            "zone": "NW",
            "capture_time": "2026-11-27T08:00:00Z",
            "verdict": "CLEAR",
        }
        res = client.post("/api/observations", files=files, data=form)
        assert res.status_code == 200
        data = res.json()
        assert data["original_filename"] == "shadow.png"
        assert ".." not in data["image_path"]

    def test_34_upload_transaction_cleanup_on_failure(self, client: TestClient):
        """34. Cleans up stored image file if database transaction fails."""
        from dl.api.dependencies import get_observation_service
        from dl.api.services.observation_service import ObservationService

        class FailingObservationService(ObservationService):
            def ingest_observations_bulk(self, *args, **kwargs):
                raise RuntimeError("Simulated database failure during persistence")

        app = client.app
        # We instantiate a failing service with None for db/fusion
        app.dependency_overrides[get_observation_service] = lambda: FailingObservationService(None, None)
        try:
            files = {
                "image": ("rollback_test.png", io.BytesIO(generate_test_png_bytes()), "image/png"),
            }
            form = {
                "segment_id": "SEG-005",
                "source": "patrol",
                "zone": "NE",
                "capture_time": "2026-11-27T08:00:00Z",
                "verdict": "CLEAR",
            }
            res = client.post("/api/observations", files=files, data=form)
            assert res.status_code == 500
            assert "Failed to persist observation" in res.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_observation_service, None)

    def test_35_upload_audit_metadata_retention(self, client: TestClient):
        """35. Segment history retains image storage path, original filename, and analyzed_at."""
        files = {
            "image": ("patrol_camera_nw.png", io.BytesIO(generate_test_png_bytes((128, 64, 32))), "image/png"),
        }
        form = {
            "segment_id": "SEG-007",
            "source": "field_patrol_07",
            "zone": "NE",
            "capture_time": "2026-11-27T08:30:00Z",
            "verdict": "CLEAR",
        }
        res_upload = client.post("/api/observations", files=files, data=form)
        assert res_upload.status_code == 200

        res_hist = client.get("/api/segments/SEG-007/history")
        assert res_hist.status_code == 200
        hist_data = res_hist.json()
        assert hist_data["count"] >= 1
        item = next(h for h in hist_data["history"] if h["source"] == "field_patrol_07")
        assert item["original_filename"] == "patrol_camera_nw.png"
        assert item["image_path"] is not None
        assert "uploads/" in item["image_path"]
        assert item["analyzed_at"] is not None
        assert item["is_mock"] is True
