from sqlalchemy import Column, String, Integer, Float, Enum
from app.database import Base
import enum

class WeldingType(enum.Enum):
    LASER = "Laser"
    SPOT = "Spot"

class BatteryModel(Base):
    __tablename__ = "battery_models"

    model_id = Column(String, primary_key=True, index=True)
    category = Column(String, nullable=False) # e.g., e-Rickshaw, Scooter, Solar

    series_count = Column(Integer, nullable=False)   # e.g., 13 for 48V
    parallel_count = Column(Integer, nullable=False) # e.g., 10 for 26Ah

    # IR Standard (mΩ)
    cell_ir_lower = Column(Float, nullable=False)
    cell_ir_upper = Column(Float, nullable=False)

    # Voltage Standard (V)
    cell_voltage_lower = Column(Float, nullable=False)
    cell_voltage_upper = Column(Float, nullable=False)

    # Capacity Standard (mAh)
    cell_capacity_lower = Column(Float, nullable=False)
    cell_capacity_upper = Column(Float, nullable=False)

    # Manufacturing Process
    welding_type = Column(Enum(WeldingType), default=WeldingType.SPOT)

    def __repr__(self):
        return f"<BatteryModel {self.model_id} - {self.welding_type}>"