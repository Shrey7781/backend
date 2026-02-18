from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date
from app.database import get_db
from app.models.dispatch import Dispatch
from app.models.battery_pack import Battery
from app.models.pdi import PDIReport

router = APIRouter(prefix="/dispatch", tags=["Dispatch & Sales"])

class DispatchRequest(BaseModel):
    battery_id: str
    customer_name: str
    invoice_id: str
    invoice_date: date

@router.post("/submit")
async def register_dispatch(data: DispatchRequest, db: Session = Depends(get_db)):
    # 1. Verify Battery exists
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found in system")

    # 2. Safety Check: Only allow dispatch if PDI is PASSED
    pdi = db.query(PDIReport).filter(PDIReport.battery_id == data.battery_id).first()
    if not pdi or pdi.test_result != "Finished PASS":
        raise HTTPException(
            status_code=400, 
            detail="Quality Gate Failed: Battery cannot be dispatched without a PASS PDI report."
        )

    # 3. Check if already dispatched
    existing = db.query(Dispatch).filter(Dispatch.battery_id == data.battery_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Battery has already been dispatched/invoiced")

    # 4. Create record
    try:
        new_dispatch = Dispatch(
            battery_id=data.battery_id,
            customer_name=data.customer_name,
            invoice_id=data.invoice_id,
            invoice_date=data.invoice_date
        )
        db.add(new_dispatch)
        db.commit()
        return {"status": "Success", "message": f"Battery {data.battery_id} dispatched to {data.customer_name}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))