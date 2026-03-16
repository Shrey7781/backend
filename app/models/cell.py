from sqlalchemy import Column, String, Integer, Boolean, DateTime, Float, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

# ── Cell status lifecycle ─────────────────────────────────────────────────────
#
#   pending  → default on auto-registration (first grading upload)
#   ng       → failed grading; ng_count incremented on EVERY failed upload
#   pass     → passed grading; master record LOCKED after this (no further overwrites)
#              grading detail (CellGrading) still always updated with latest data
#   is_used  → True once assigned to a battery pack (BatteryCellMapping)
#
# ─────────────────────────────────────────────────────────────────────────────

class Cell(Base):
    __tablename__ = "cells"

    cell_id           = Column(String(100), primary_key=True, index=True)
    registration_date = Column(DateTime(timezone=True), server_default=func.now())
    is_used           = Column(Boolean, default=False)

    status   = Column(String(50), default="pending")  # pending | ng | pass
    ng_count = Column(Integer,    default=0)           # increments each failed upload

    # Set on first grading upload, updated only while status != "pass"
    discharging_capacity_mah = Column(Float, nullable=True)
    last_test_date           = Column(DateTime, nullable=True)

    # Set by sorting machine upload (always overwritten with latest)
    ir_value_m_ohm  = Column(Float, nullable=True)
    sorting_voltage = Column(Float, nullable=True)
    sorting_date    = Column(DateTime, nullable=True)

    gradings = relationship(
        "CellGrading",
        back_populates="cell",
        uselist=False,          # 1-to-1: one master grading record per cell
        lazy="select"
    )

    def __repr__(self):
        return f"<Cell {self.cell_id} [{self.status}] ng:{self.ng_count}>"


class CellGrading(Base):
    __tablename__ = "cell_gradings"

    id      = Column(Integer, primary_key=True, index=True)
    cell_id = Column(String(100), ForeignKey("cells.cell_id"), index=True)

    # All columns map directly to Excel columns from grading report
    test_date                = Column(DateTime)
    lot                      = Column(String(100))
    brand                    = Column(String(100))
    specification            = Column(String(255))
    ocv_voltage_mv           = Column(Float)        # OCV Voltage(mV)
    upper_cutoff_mv          = Column(Float)        # Upper cut off(mV)
    lower_cutoff_mv          = Column(Float)        # Lower cut off(mV)
    discharging_capacity_mah = Column(Float)        # Discharging Capacity(mAh)
    result                   = Column(String(50))   # Result
    final_soc_mah            = Column(Float)        # Final SOC(mAh)
    soc_result               = Column(String(50))   # SOC Result
    final_cv_capacity        = Column(Float)        # Final CV Capacity
    final_result             = Column(String(50))   # final Result

    cell = relationship("Cell", back_populates="gradings")

    __table_args__ = (
        # Enforce 1-to-1 at the DB level — prevents duplicate grading rows per cell
        UniqueConstraint("cell_id", name="uq_cell_grading_cell_id"),
        # Composite index for brand+date queries used by admin cell inventory
        Index("ix_cell_brand_test_date", "brand", "test_date"),
        # Index for fast status-based filtering in bulk queries
        Index("ix_cell_grading_final_result", "final_result"),
    )