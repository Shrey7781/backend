from pydantic import BaseModel, computed_field
from typing import Optional
from app.models.battery import WeldingType, CellType


class BatteryModelCreate(BaseModel):
    model_id:       str
    category:       str
    series_count:   int
    parallel_count: int
    cell_type:      CellType = CellType.NMC   # NMC or LFP
    bms_model:      Optional[str] = None      # expected BMS model for this battery template
    welding_type:   WeldingType

    # NOTE: Cell parameter ranges (IR / Voltage / Capacity) are no longer part
    # of the model template. They are submitted per-assembly via the
    # POST /batteries/assign-cells endpoint so the same model can accommodate
    # different cell batches with different tolerance bands.


class BatteryModelResponse(BatteryModelCreate):
    total_cells: int   # series_count × parallel_count — computed, read-only

    class Config:
        from_attributes = True