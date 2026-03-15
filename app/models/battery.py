from sqlalchemy import Column, String, Integer, Enum
from sqlalchemy.ext.hybrid import hybrid_property
from app.database import Base
import enum


class WeldingType(enum.Enum):
    LASER = "Laser"
    SPOT  = "Spot"


class CellType(enum.Enum):
    NMC = "NMC"
    LFP = "LFP"


class BatteryModel(Base):
    __tablename__ = "battery_models"

    # model_id IS the human-readable name e.g. "MAX-48V-26Ah"
    # Used directly as primary key — no separate auto-increment id needed.
    model_id       = Column(String, primary_key=True, index=True)
    category       = Column(String, nullable=False)         # e.g. e-Rickshaw, Scooter, Solar

    series_count   = Column(Integer, nullable=False)        # cells in series  e.g. 13 for 48V
    parallel_count = Column(Integer, nullable=False)        # cells in parallel e.g. 10 for 26Ah

    cell_type      = Column(Enum(CellType),    nullable=False, default=CellType.NMC)  # NMC or LFP
    bms_model      = Column(String,            nullable=True)   # e.g. "Daly 20S"
    welding_type   = Column(Enum(WeldingType), nullable=False, default=WeldingType.SPOT)

    # IR / Voltage / Capacity ranges removed — entered per-assembly on Battery record.

    @hybrid_property
    def total_cells(self) -> int:
        """Total cells per pack = series × parallel  (e.g. 13 × 10 = 130)."""
        return self.series_count * self.parallel_count

    def __repr__(self):
        return (
            f"<BatteryModel {self.model_id} "
            f"[{self.cell_type.value} {self.series_count}S{self.parallel_count}P] "
            f"{self.welding_type.value}>"
        )