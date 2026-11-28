"""
SQLAlchemy 2.0 declarative database models for DisasterLens.

Persistent entities:
1. City
2. Intersection
3. RoadSegment
4. Observation
5. Scenario
6. ScenarioEvent
7. SavedRoute
8. RouteAlert
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from dl.api.database import Base


def utc_now() -> datetime:
    """Returns current UTC timestamp."""
    return datetime.now(UTC)


class City(Base):
    __tablename__ = "cities"

    id = Column(String(64), primary_key=True)  # e.g. "DEMO-001" or "demo_city"
    name = Column(String(128), nullable=False)
    grid_size = Column(Integer, nullable=False, default=6)
    bounds_x_min = Column(Float, nullable=False, default=0.0)
    bounds_x_max = Column(Float, nullable=False, default=1024.0)
    bounds_y_min = Column(Float, nullable=False, default=0.0)
    bounds_y_max = Column(Float, nullable=False, default=1024.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    intersections = relationship("Intersection", back_populates="city", cascade="all, delete-orphan")
    road_segments = relationship("RoadSegment", back_populates="city", cascade="all, delete-orphan")
    scenarios = relationship("Scenario", back_populates="city", cascade="all, delete-orphan")
    saved_routes = relationship("SavedRoute", back_populates="city", cascade="all, delete-orphan")


class Intersection(Base):
    __tablename__ = "intersections"

    id = Column(String(64), primary_key=True)  # e.g. "INT-001"
    city_id = Column(String(64), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    zone = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    city = relationship("City", back_populates="intersections")


class RoadSegment(Base):
    __tablename__ = "road_segments"

    id = Column(String(64), primary_key=True)  # e.g. "SEG-001"
    city_id = Column(String(64), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    from_intersection_id = Column(String(64), ForeignKey("intersections.id"), nullable=False)
    to_intersection_id = Column(String(64), ForeignKey("intersections.id"), nullable=False)
    length_m = Column(Float, nullable=False)
    zone = Column(String(16), nullable=False)
    centerline_json = Column(Text, nullable=False)  # JSON-encoded coordinates [[x,y], [x,y]]
    polygon_json = Column(Text, nullable=False)     # JSON-encoded polygon coordinates
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    city = relationship("City", back_populates="road_segments")

    __table_args__ = (
        Index("ix_road_segments_city_id_id", "city_id", "id"),
    )


class Observation(Base):
    """
    Complete observation history.
    Preserves captured_at and uploaded_at independently.
    Uploaded_at is ingestion audit metadata and is never used for freshness calculations.
    """
    __tablename__ = "observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    observation_id = Column(String(64), nullable=False, index=True)
    segment_id = Column(String(64), nullable=False, index=True)  # Soft link to avoid history loss on segment delete
    source = Column(String(64), nullable=False)
    zone = Column(String(16), nullable=False)
    verdict = Column(String(32), nullable=False)  # CLEAR, BLOCKED, PARTIAL, UNCERTAIN, UNKNOWN
    confidence = Column(Float, nullable=False, default=1.0)
    max_coverage = Column(Float, nullable=True)
    hazard_type = Column(String(64), nullable=True)
    near_miss = Column(Boolean, nullable=False, default=False)
    recovery = Column(Boolean, nullable=False, default=False)
    visibility = Column(String(32), nullable=False, default="full")
    direct_verdict = Column(String(32), nullable=True)
    mapped_verdict = Column(String(32), nullable=True)
    evidence_json = Column(Text, nullable=True)  # JSON string of raw provenance/evidence
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    analyzed_at = Column(DateTime(timezone=True), nullable=True)
    model_id = Column(String(64), nullable=True)
    is_mock = Column(Boolean, nullable=False, default=True)
    image_path = Column(String(256), nullable=True)
    original_filename = Column(String(256), nullable=True)
    affected_segments_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_observations_segment_captured", "segment_id", "captured_at"),
    )


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(String(64), primary_key=True)  # e.g. "demo_city"
    city_id = Column(String(64), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    current_time_step = Column(String(16), nullable=False, default="T0")
    current_simulated_time = Column(DateTime(timezone=True), nullable=True)
    cameras_json = Column(Text, nullable=True)  # JSON-encoded camera configs
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    city = relationship("City", back_populates="scenarios")
    events = relationship("ScenarioEvent", back_populates="scenario", cascade="all, delete-orphan", order_by="ScenarioEvent.id")


class ScenarioEvent(Base):
    __tablename__ = "scenario_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    time_step = Column(String(16), nullable=False, index=True)  # T0, T1, T2, T3
    timestamp = Column(DateTime(timezone=True), nullable=True)
    description = Column(Text, nullable=False)
    observations_json = Column(Text, nullable=False)  # JSON array of raw observation dicts

    scenario = relationship("Scenario", back_populates="events")

    __table_args__ = (
        Index("ix_scenario_events_scenario_step", "scenario_id", "time_step"),
    )


class SavedRoute(Base):
    __tablename__ = "saved_routes"

    id = Column(String(64), primary_key=True)  # e.g. "ROUTE-DISPATCH-01"
    city_id = Column(String(64), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=True)
    origin_node = Column(String(64), nullable=False)
    destination_node = Column(String(64), nullable=False)
    node_path_json = Column(Text, nullable=False)      # JSON list of intersection IDs
    segment_path_json = Column(Text, nullable=False)   # JSON list of segment IDs
    length_m = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    city = relationship("City", back_populates="saved_routes")


class RouteAlert(Base):
    __tablename__ = "route_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(String(64), nullable=False, index=True)
    segment_id = Column(String(64), nullable=False, index=True)
    alert_type = Column(String(64), nullable=False)  # PRIMARY_NOW_BLOCKED, ROUTE_CLEARED, ROUTE_DEGRADED
    message = Column(Text, nullable=False)
    severity = Column(String(32), nullable=False)    # critical, warning, info
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_route_alerts_route_created", "route_id", "created_at"),
    )
