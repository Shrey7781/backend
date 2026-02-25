from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.battery import BatteryModel
from app.schemas.battery_schema import BatteryModelCreate, BatteryModelResponse
from typing import List
from app.models.battery_pack import Battery

router = APIRouter(prefix="/battery-models", tags=["Battery Models"])

@router.post("/", response_model=BatteryModelResponse)
def create_battery_model(model: BatteryModelCreate, db: Session = Depends(get_db)):
    # Check if model_id already exists
    db_model = db.query(BatteryModel).filter(BatteryModel.model_id == model.model_id).first()
    if db_model:
        raise HTTPException(status_code=400, detail="Model ID already exists")
    
    new_model = BatteryModel(**model.model_dump())
    db.add(new_model)
    db.commit()
    db.refresh(new_model)
    return new_model

@router.get("/summary")
def get_battery_models_summary(db: Session = Depends(get_db)):
    # 1. Fetch only the necessary columns from the database
    models = db.query(BatteryModel.model_id, BatteryModel.series_count, BatteryModel.parallel_count).all()
    
    # 2. Return a list containing only model_id and the calculated total
    return [
        {
            "model_id": model.model_id,
            "total_count": model.series_count + model.parallel_count
        } 
        for model in models
    ]

@router.get("/{model_id}", response_model=BatteryModelResponse)
def get_battery_model(model_id: str, db: Session = Depends(get_db)):
    db_model = db.query(BatteryModel).filter(BatteryModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Battery model not found")
    return db_model

@router.get("/{battery_id}/welding-info")
def get_welding_type(battery_id: str, db: Session = Depends(get_db)):
    # 1. Join Battery with BatteryModel to get the welding info
    result = db.query(Battery, BatteryModel.welding_type) \
        .join(BatteryModel, Battery.model_id == BatteryModel.model_id) \
        .filter(Battery.battery_id == battery_id) \
        .first()

    # 2. Check if the battery exists
    if not result:
        raise HTTPException(
            status_code=404, 
            detail=f"Battery ID {battery_id} not found in system"
        )

    # result is a tuple (BatteryObject, "WeldingString")
    battery_data, welding_type = result

    return {
        "battery_id": battery_id,
        "welding_type": welding_type,
    }

@router.patch("/{battery_id}/mark-ready")
def update_to_ready(battery_id: str, db: Session = Depends(get_db)):
    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    
    if not battery:
        raise HTTPException(status_code=404, detail="Battery not found")
        
    # Validation: Can only move to Ready if it has passed PDI (FG PENDING)
    if battery.overall_status != "FG PENDING":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot mark as READY. Current status is {battery.overall_status}"
        )

    battery.overall_status = "READY TO DISPATCH"
    db.commit()
    return {"status": "success", "new_status": battery.overall_status}