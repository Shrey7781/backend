from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship


class BMS(Base):
    __tablename__ = "bms_inventory"

    bms_id     = Column(String, primary_key=True, index=True)

    # bms_model NOT stored here — inherited from BatteryModel.bms_model when
    # this unit is linked to a battery.  Operator only scans bms_id at mounting.
    battery_id = Column(String, ForeignKey("batteries.battery_id"), nullable=True)
    is_used    = Column(Boolean, default=False)
    added_at   = Column(DateTime(timezone=True), server_default=func.now())

    battery = relationship("Battery", back_populates="bms_record")

    def __repr__(self):
        return f"<BMS {self.bms_id} → Battery:{self.battery_id}>"