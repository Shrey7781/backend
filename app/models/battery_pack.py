from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database import Base

class Battery(Base):
    __tablename__ = "batteries"


    battery_id = Column(String, primary_key=True, index=True)
    model_id = Column(String, ForeignKey("battery_models.model_id"), nullable=False)
    had_ng_status = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Battery {self.battery_id} [Model: {self.model_id}]>"
    

class BatteryCellMapping(Base):
    __tablename__ = "battery_cell_mapping"

 
    battery_id = Column(String, ForeignKey("batteries.battery_id"), primary_key=True)
    cell_id = Column(String, ForeignKey("cells.cell_id"), primary_key=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())