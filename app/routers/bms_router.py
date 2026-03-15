from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.bms import BMS
from app.models.battery_pack import Battery
from app.models.battery import BatteryModel
from pydantic import BaseModel
from app.core.signals import trigger_dashboard_update

router = APIRouter(prefix="/bms", tags=["BMS Management"])


class BMSMappingRequest(BaseModel):
    bms_id:     str
    battery_id: str


# ── Page 6: BMS Mounting — scan battery ID + BMS ID ─────────────────────────

@router.get("/info/{battery_id}")
def get_bms_info(battery_id: str, db: Session = Depends(get_db)):
    """
    Scan battery ID → returns expected BMS model (from battery model template).
    Frontend shows this so operator can confirm before scanning BMS unit.
    """
    result = (
        db.query(Battery, BatteryModel.bms_model)
        .join(BatteryModel, Battery.model_id == BatteryModel.model_id)
        .filter(Battery.battery_id == battery_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Battery ID '{battery_id}' not found")

    battery, bms_model = result

    # Check if BMS already mounted
    existing_bms = db.query(BMS).filter(BMS.battery_id == battery_id).first()

    return {
        "battery_id":       battery_id,
        "model_id":         battery.model_id,
        "expected_bms_model": bms_model or "Not specified",
        "bms_already_mounted": existing_bms.bms_id if existing_bms else None,
    }


@router.post("/map-to-battery")
async def map_bms_to_battery(data: BMSMappingRequest, db: Session = Depends(get_db)):
    """
    Link a BMS unit to a battery.
    - BMS units do NOT need pre-registration — auto-created on first scan.
    - BMS model is inherited from the battery model template, not entered manually.
    - Prevents same BMS being assigned to two different batteries.
    """
    # 1. Verify battery exists
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found")

    # 2. Get expected BMS model from template
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    expected_bms_model = model.bms_model if model else None

    # 3. Fetch or auto-create BMS unit
    bms = db.query(BMS).filter(BMS.bms_id == data.bms_id).first()
    if bms:
        if bms.is_used and bms.battery_id != data.battery_id:
            raise HTTPException(
                status_code=400,
                detail=f"BMS {data.bms_id} is already assigned to battery {bms.battery_id}"
            )
    else:
        bms = BMS(bms_id=data.bms_id)
        db.add(bms)

    # 4. Link
    bms.battery_id = data.battery_id
    bms.is_used    = True

    db.commit()
    await trigger_dashboard_update()

    return {
        "status":             "Success",
        "message":            f"BMS {data.bms_id} linked to Battery {data.battery_id}",
        "expected_bms_model": expected_bms_model or "Not specified for this model",
    }