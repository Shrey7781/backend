from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship


class PackTest(Base):
    __tablename__ = "pack_testing_reports"

    id         = Column(Integer, primary_key=True, index=True)
    battery_id = Column(String, ForeignKey("batteries.battery_id"), unique=True)

    # Core details from Excel
    test_date          = Column(DateTime)       # Date
    specification      = Column(String(255))    # e.g. "60V 29Ah"
    cell_type          = Column(String(100))    # e.g. "NMC"
    # number_of_series   = Column(Integer)        # Number of series
    # number_of_parallel = Column(Integer)        # Number of parallel
    actual_cap = Column(Float)


    # Voltage & capacity parameters
    ocv_voltage          = Column(Float)        # OCV Voltage(V)
    upper_cutoff         = Column(Float)        # Upper cut off(V)
    lower_cutoff         = Column(Float)        # Lower cut off(V)
    discharging_capacity = Column(Float)        # Discharging Capacity(Ah)

    # Result flags
    capacity_result = Column(String(50))        # Result (PASS/FAIL)
    idle_difference = Column(Float)             # Final idle Different
    idle_diff_res      = Column(String(50))        
    final_voltage   = Column(Float)             # Final Voltage
    final_result    = Column(String(50))        # final Result — PASS or FAIL

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    battery = relationship("Battery", back_populates="pack_test")

    def __repr__(self):
        return f"<PackTest {self.battery_id} [{self.final_result}]>"