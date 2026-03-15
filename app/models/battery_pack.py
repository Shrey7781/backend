from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship

# ── Battery overall_status lifecycle ─────────────────────────────────────────
#
#   PROD              → default on creation (bulk Excel import)
#   FG PENDING        → set automatically when PDI upload result = "Finished PASS"
#   READY TO DISPATCH → set manually by operator scanning battery on PDI page
#                       (PATCH /battery-models/{battery_id}/mark-ready)
#   DISPATCHED        → set automatically on POST /dispatch/submit
#   FAILED            → set when PDI result is NOT "Finished PASS"
#
# had_ng_status = True is SET ONCE and never reversed — permanent repair flag.
# ─────────────────────────────────────────────────────────────────────────────

class Battery(Base):
    __tablename__ = "batteries"

    battery_id     = Column(String, primary_key=True, index=True)
    model_id       = Column(String, ForeignKey("battery_models.model_id"), nullable=False)
    had_ng_status  = Column(Boolean, default=False)   # True = had NG at any stage, never reset
    overall_status = Column(String(50), default="PROD", index=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    # ── Assembly-time cell parameter ranges ──────────────────────────────────
    # Stored here (not on BatteryModel) so audit report always reflects the
    # exact tolerances used for THIS specific assembly batch.
    # Nullable — a None range means that parameter was not checked.
    cell_ir_lower       = Column(Float, nullable=True)
    cell_ir_upper       = Column(Float, nullable=True)
    cell_voltage_lower  = Column(Float, nullable=True)
    cell_voltage_upper  = Column(Float, nullable=True)
    cell_capacity_lower = Column(Float, nullable=True)
    cell_capacity_upper = Column(Float, nullable=True)

    # Relationships
    pdi_reports     = relationship("PDIReport", back_populates="battery")
    bms_record      = relationship("BMS",       back_populates="battery", uselist=False)
    dispatch_record = relationship("Dispatch",  back_populates="battery", uselist=False)
    pack_test       = relationship("PackTest",  back_populates="battery", uselist=False)

    def __repr__(self):
        return f"<Battery {self.battery_id} [{self.overall_status}] Model:{self.model_id}>"


class BatteryCellMapping(Base):
    __tablename__ = "battery_cell_mapping"

    battery_id  = Column(String, ForeignKey("batteries.battery_id", ondelete="CASCADE"),
                         primary_key=True)
    cell_id     = Column(String, ForeignKey("cells.cell_id"),
                         primary_key=True, unique=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mapping_lookup", "battery_id", "cell_id"),
    )