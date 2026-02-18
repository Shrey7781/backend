from pydantic import BaseModel
from app.models.battery import WeldingType

class BatteryModelCreate(BaseModel):
    model_id: str
    category: str
    series_count: int
    parallel_count: int
    cell_ir_lower: float
    cell_ir_upper: float
    cell_voltage_lower: float
    cell_voltage_upper: float
    cell_capacity_lower: float
    cell_capacity_upper: float
    welding_type: WeldingType

class BatteryModelResponse(BatteryModelCreate):
    class Config:
        from_attributes = True # This allows it to read from the SQLAlchemy object