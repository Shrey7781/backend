from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.database import Base

class BMS(Base):
    __tablename__ = "bms_inventory"

    bms_id = Column(String, primary_key=True, index=True)
    bms_model = Column(String, nullable=False)
    battery_id = Column(String, ForeignKey("batteries.battery_id"), nullable=True)
    is_used = Column(Boolean, default=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<BMS {self.bms_id} - {self.bms_model}>"