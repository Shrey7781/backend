from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class PDIReport(Base):
    __tablename__ = "pdi_reports"

    id = Column(Integer, primary_key=True, index=True)
    # Unique constraint allows us to find and overwrite specific battery data
    battery_id = Column(String, ForeignKey("batteries.battery_id"), unique=True)
    
    # Core Parameters
    test_time = Column(DateTime)                      # 'Time' in Excel
    voltage_v = Column(Float)                         # 'Voltage(V)'
    resistance_m_ohm = Column(Float)                  # 'Resistance(m¦¸)'
    cont_charging_current = Column(Float)             # 'Continuous Charging Current(A)'
    cont_charging_voltage = Column(Float)             # 'Continuous Charging Voltage(V)'
    cont_discharging_current = Column(Float)          # 'Continuous Discharging Current(A)'
    cont_discharging_voltage = Column(Float)          # 'Continuous Discharging Voltage(V)'
    short_circuit_prot_time_us = Column(Integer)      # 'Short circuit protection time (uS)'
    test_result = Column(String(100))                 # 'Test Result'

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())