from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from app.database import Base
from sqlalchemy.sql import func

class PackTest(Base):
    __tablename__ = "pack_testing_reports"

    id = Column(Integer, primary_key=True, index=True)
    
    # Mapping "Barcode" to our system's battery_id
    battery_id = Column(String, ForeignKey("batteries.battery_id"), unique=True)
    
    # Core Details
    test_date = Column(DateTime)             # Date column from Excel
    specification = Column(String(255))      # e.g., "60V 29Ah"
    cell_type = Column(String(100))          # e.g., "NMC"
    number_of_series = Column(Integer)       # Number of sreies
    number_of_parallel = Column(Integer)     # Number of parallel

    # Voltage & Capacity Parameters
    ocv_voltage = Column(Float)              # OCV Voltage(V)
    upper_cutoff = Column(Float)             # Upper cut off(V)
    lower_cutoff = Column(Float)             # Lower cut off(V)
    discharging_capacity = Column(Float)     # Discharging Capacity(Ah)
    
    # Result Flags
    capacity_result = Column(String(50))     # Result (PASS/FAIL)
    idle_difference = Column(Float)          # Final idle Different
    soc_result = Column(String(50))          # SOC Result
    final_voltage = Column(Float)            # Final Voltage 
    final_result = Column(String(50))        # final Result (Overall status)

    # Metadata for the record
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<PackTest {self.battery_id} - Result: {self.final_result}>"