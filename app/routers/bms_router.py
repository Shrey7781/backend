from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.bms import BMS
from app.models.battery_pack import Battery
from pydantic import BaseModel
from typing import List

# --- SCHEMAS (Makes Swagger work) ---
class BMSRegistrationRequest(BaseModel):
    bms_id: str
    bms_model: str

class BMSMappingRequest(BaseModel):
    bms_id: str
    battery_id: str

router = APIRouter(prefix="/bms", tags=["BMS Management"])

# --- ENDPOINTS ---

@router.post("/register")
async def register_bms(data: BMSRegistrationRequest, db: Session = Depends(get_db)):
    existing = db.query(BMS).filter(BMS.bms_id == data.bms_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="BMS ID already exists in inventory")

    new_bms = BMS(bms_id=data.bms_id, bms_model=data.bms_model)
    db.add(new_bms)
    db.commit()
    return {"status": "Success", "message": f"BMS {data.bms_id} added to inventory"}

@router.post("/map-to-battery")
async def map_bms_to_battery(data: BMSMappingRequest, db: Session = Depends(get_db)):
    bms = db.query(BMS).filter(BMS.bms_id == data.bms_id).first()
    if not bms:
        raise HTTPException(status_code=404, detail="BMS not found")
    if bms.is_used:
        raise HTTPException(status_code=400, detail=f"BMS already assigned to {bms.battery_id}")

    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery not found")

    bms.battery_id = data.battery_id
    bms.is_used = True
    db.commit()
    return {"status": "Success", "message": f"BMS {data.bms_id} linked to Battery {data.battery_id}"}

@router.get("/models", response_model=List[str])
def get_unique_bms_models(db: Session = Depends(get_db)):
    # We remove the .filter(BMS.is_used == False) to see EVERYTHING
    models = db.query(BMS.bms_model).distinct().all()
    
    # SQLAlchemy returns a list of tuples like [('Daly',), ('JK',)], 
    # so we extract the first element of each tuple.
    return [m.bms_model for m in models]