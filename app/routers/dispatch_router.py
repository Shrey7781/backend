from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date
from app.database import get_db
from app.models.dispatch import Dispatch
from app.models.battery_pack import Battery
from app.models.pdi import PDIReport
from app.core.signals import trigger_dashboard_update

router = APIRouter(prefix="/dispatch", tags=["Dispatch & Sales"])


class DispatchRequest(BaseModel):
    battery_id:    str
    customer_name: str
    invoice_id:    str
    invoice_date:  date


# ── Page 9: Dispatch ──────────────────────────────────────────────────────────

@router.get("/check/{battery_id}")
def check_dispatch_eligibility(battery_id: str, db: Session = Depends(get_db)):
    """
    Pre-check before dispatch form submission.
    Returns battery status and whether it is eligible for dispatch.
    """
    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found")

    pdi = db.query(PDIReport).filter(PDIReport.battery_id == battery_id).first()

    already_dispatched = db.query(Dispatch).filter(Dispatch.battery_id == battery_id).first()

    eligible = (
        battery.overall_status == "READY TO DISPATCH"
        and pdi is not None
        and pdi.test_result == "Finished PASS"
        and not already_dispatched
    )

    return {
        "battery_id":        battery_id,
        "overall_status":    battery.overall_status,
        "pdi_result":        pdi.test_result if pdi else None,
        "had_ng_status":     battery.had_ng_status,
        "already_dispatched":bool(already_dispatched),
        "eligible":          eligible,
    }


@router.post("/submit")
async def register_dispatch(data: DispatchRequest, db: Session = Depends(get_db)):
    """
    Submit dispatch record.

    Quality gates (all must pass):
    1. Battery must exist.
    2. PDI must exist and be "Finished PASS".
    3. Battery overall_status must be "READY TO DISPATCH".
    4. Must not have been dispatched before.
    """
    # 1. Battery exists
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found in system")

    # 2. PDI passed
    pdi = db.query(PDIReport).filter(PDIReport.battery_id == data.battery_id).first()
    if not pdi or pdi.test_result != "Finished PASS":
        raise HTTPException(
            status_code=400,
            detail="Quality Gate Failed: Battery cannot be dispatched without a PASS PDI report."
        )

    # 3. Status check
    if battery.overall_status != "READY TO DISPATCH":
        reason = (
            "PDI not passed"      if battery.overall_status == "PROD"       else
            "FG scan pending"     if battery.overall_status == "FG PENDING"  else
            f"status is {battery.overall_status}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Dispatch Denied: Current status is {battery.overall_status}. ({reason})"
        )

    # 4. Not already dispatched
    existing = db.query(Dispatch).filter(Dispatch.battery_id == data.battery_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Battery has already been dispatched/invoiced")

    try:
        db.add(Dispatch(
            battery_id=data.battery_id,
            customer_name=data.customer_name,
            invoice_id=data.invoice_id,
            invoice_date=data.invoice_date,
        ))
        battery.overall_status = "DISPATCHED"
        db.commit()
        await trigger_dashboard_update()
        return {
            "status":  "Success",
            "message": f"Battery {data.battery_id} dispatched to {data.customer_name}",
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))