from sqlalchemy import Column, String, Integer, Boolean, DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.database import Base 
from sqlalchemy.sql import func


class Cell(Base):
    __tablename__ = "cells"

    cell_id = Column(String(100), primary_key=True, index=True)
    registration_date = Column(DateTime(timezone=True), server_default=func.now())
    is_used = Column(Boolean, default=False)

    status = Column(String(50), default="pending") 
    ng_count = Column(Integer, default=0)

   
    discharging_capacity_mah = Column(Float, nullable=True)
    last_test_date = Column(DateTime, nullable=True)

    ir_value_m_ohm = Column(Float, nullable=True)  # IR VALUE
    sorting_voltage = Column(Float, nullable=True)  # VOLTAGE (from sorting machine)
    
   
    sorting_date = Column(DateTime, nullable=True)
    gradings = relationship("CellGrading", back_populates="cell")

class CellGrading(Base):
    __tablename__ = "cell_gradings"

    # Internal primary key for the grading record
    id = Column(Integer, primary_key=True, index=True)
    

    cell_id = Column(String(100), ForeignKey("cells.cell_id"), index=True)
    
    # Parameters from Excel file
    test_date = Column(DateTime)                    # Date
    lot = Column(String(100))                       # Lot
    brand = Column(String(100))                     # Brand
    specification = Column(String(255))             # Specification
    ocv_voltage_mv = Column(Float)                  # OCV Voltage(mV)
    upper_cutoff_mv = Column(Float)                 # Upper cut off(mV)
    lower_cutoff_mv = Column(Float)                 # Lower cut off(mV)
    discharging_capacity_mah = Column(Float)        # Discharging Capacity(mAh)
    result = Column(String(50))                     # Result
    final_soc_mah = Column(Float)                   # Final SOC(mAh)
    soc_result = Column(String(50))                 # SOC Result
    final_cv_capacity = Column(Float)               # Final CV Capacity
    final_result = Column(String(50))               # final Result
    
   
    cell = relationship("Cell", back_populates="gradings")

    __table_args__ = (
        Index('ix_cell_brand_created', 'brand', 'test_date'),
    )