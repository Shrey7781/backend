from sqlalchemy import Column, String, Integer, Date, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship


class Dispatch(Base):
    __tablename__ = "dispatch_records"

    id         = Column(Integer, primary_key=True, index=True)
    battery_id = Column(String, ForeignKey("batteries.battery_id"), unique=True)  # one dispatch per battery

    customer_name = Column(String(255), nullable=False)
    invoice_id    = Column(String(100), nullable=False)
    invoice_date  = Column(Date,        nullable=False)

    dispatch_timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # On dispatch: battery.overall_status is set to "DISPATCHED"
    battery = relationship("Battery", back_populates="dispatch_record")