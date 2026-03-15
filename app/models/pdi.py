from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship


class PDIReport(Base):
    __tablename__ = "pdi_reports"

    id         = Column(Integer, primary_key=True, index=True)
    battery_id = Column(String, ForeignKey("batteries.battery_id"), index=True)

    # ── What this record triggers on Battery ─────────────────────────────────
    # test_result == "Finished PASS"  →  battery.overall_status = "FG PENDING"
    # test_result == anything else    →  battery.overall_status = "FAILED"
    #                                    battery.had_ng_status  = True
    #
    # After FG PENDING, operator scans battery on PDI page to move it to
    # "READY TO DISPATCH" via PATCH /battery-models/{battery_id}/mark-ready
    # ─────────────────────────────────────────────────────────────────────────

    # Columns map directly to Excel columns from PDI machine export
    test_time                  = Column(DateTime)          # Time
    voltage_v                  = Column(Float)             # Voltage(V)
    resistance_m_ohm           = Column(Float)             # Resistance(mΩ)
    cont_charging_current      = Column(Float)             # Continuous Charging Current(A)
    cont_charging_voltage      = Column(Float)             # Continuous Charging Voltage(V)
    cont_discharging_current   = Column(Float)             # Continuous Discharging Current(A)
    cont_discharging_voltage   = Column(Float)             # Continuous Discharging Voltage(V)
    short_circuit_prot_time_us = Column(Integer)           # Short circuit protection time (uS)
    test_result                = Column(String(100))       # Test Result — "Finished PASS" or other

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    battery = relationship("Battery", back_populates="pdi_reports")