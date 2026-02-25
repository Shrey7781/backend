from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship

class Battery(Base):
    __tablename__ = "batteries"


    battery_id = Column(String, primary_key=True, index=True)
    model_id = Column(String, ForeignKey("battery_models.model_id"), nullable=False)
    had_ng_status = Column(Boolean, default=False)
    overall_status = Column(String(50), default="PROD", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    pdi_reports = relationship("PDIReport", back_populates="battery")
    bms_record = relationship("BMS", back_populates="battery", uselist=False)
    dispatch_record = relationship("Dispatch", back_populates="battery", uselist=False)
    pack_test = relationship("PackTest", back_populates="battery", uselist=False)

    def __repr__(self):
        return f"<Battery {self.battery_id} [Model: {self.model_id}]>"
    

class BatteryCellMapping(Base):
    __tablename__ = "battery_cell_mapping"

    battery_id = Column(String, ForeignKey("batteries.battery_id", ondelete="CASCADE"), primary_key=True)
    cell_id = Column(String, ForeignKey("cells.cell_id"), primary_key=True, unique=True) 
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_mapping_lookup', 'battery_id', 'cell_id'),
    )