from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.welding import LaserWelding, SpotWelding
from app.models.battery_pack import Battery
from app.models.battery import BatteryModel, WeldingType
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/welding", tags=["Welding Operations"])

# ── Default parameters per welding type ──────────────────────────────────────
# Shown on the frontend when battery is scanned — operator can override before submit.

LASER_DEFAULTS = {
    "initial_speed":      50.0,
    "max_speed":          100.0,
    "acceleration":       500.0,
    "laser_on_delay":     100,
    "laser_off_delay":    100,
    "point_duration":     5,
    "power_mode":         "CW",
    "pwm_freq":           20000,
    "pwm_cycle":          100,
    "pwm_duty_rate":      80.0,
    "pwm_width":          0.05,
    "code":               1,
    "dac_power":          80.0,
    "scan_speed":         500.0,
    "lsm_laser_on_delay": 50,
    "lsm_laser_off_delay":50,
}

SPOT_DEFAULTS = {
    "solder_joint_mode":        "Single",
    "welding_needle_direction": "Down",
    "hole_setback_distance":    2.0,
    "total_stroke_welding_head":10.0,
    "start_delay":              100,
    "clamping_delay":           50,
    "welding_time":             200,
    "air_speed":                5.0,
    "working_speed":            3.0,
    "hole_inlet_speed":         2.0,
}


class WeldingSubmission(BaseModel):
    battery_id: str
    parameters: dict  # operator sends back (possibly modified) parameters


# ── Page 5: Welding — scan battery ID, get type + defaults, submit params ────

@router.get("/info/{battery_id}")
def get_welding_info(battery_id: str, db: Session = Depends(get_db)):
    """
    Scan battery ID → returns welding type (auto-detected from model)
    and default parameters for that welding type.
    Frontend pre-fills the form; operator adjusts if needed before submitting.
    """
    result = (
        db.query(Battery, BatteryModel.welding_type)
        .join(BatteryModel, Battery.model_id == BatteryModel.model_id)
        .filter(Battery.battery_id == battery_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Battery ID '{battery_id}' not found")

    _, welding_type = result
    weld_str     = welding_type.value.lower()   # "laser" or "spot"
    defaults     = LASER_DEFAULTS if weld_str == "laser" else SPOT_DEFAULTS

    return {
        "battery_id":   battery_id,
        "welding_type": weld_str,
        "defaults":     defaults,
    }


@router.post("/submit")
async def submit_welding_data(data: WeldingSubmission, db: Session = Depends(get_db)):
    """
    Submit welding parameters for a battery.
    Welding type is auto-detected from the battery model — not sent by client.
    """
    # 1. Fetch battery + welding type in one join
    result = (
        db.query(Battery, BatteryModel.welding_type)
        .join(BatteryModel, Battery.model_id == BatteryModel.model_id)
        .filter(Battery.battery_id == data.battery_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Battery ID not found")

    battery, welding_type = result
    p      = data.parameters
    w_type = welding_type.value.lower()

    if w_type == "laser":
        db.add(LaserWelding(
            battery_id=data.battery_id,
            initial_speed=p.get("initial_speed"),
            max_speed=p.get("max_speed"),
            acceleration=p.get("acceleration"),
            laser_on_delay=p.get("laser_on_delay"),
            laser_off_delay=p.get("laser_off_delay"),
            point_duration=p.get("point_duration"),
            power_mode=p.get("power_mode"),
            pwm_freq=p.get("pwm_freq"),
            pwm_cycle=p.get("pwm_cycle"),
            pwm_duty_rate=p.get("pwm_duty_rate"),
            pwm_width=p.get("pwm_width"),
            code=p.get("code"),
            dac_power=p.get("dac_power"),
            scan_speed=p.get("scan_speed"),
            lsm_laser_on_delay=p.get("lsm_laser_on_delay"),
            lsm_laser_off_delay=p.get("lsm_laser_off_delay"),
        ))
    elif w_type == "spot":
        db.add(SpotWelding(
            battery_id=data.battery_id,
            solder_joint_mode=p.get("solder_joint_mode"),
            welding_needle_direction=p.get("welding_needle_direction"),
            hole_setback_distance=p.get("hole_setback_distance"),
            total_stroke_welding_head=p.get("total_stroke_welding_head"),
            start_delay=p.get("start_delay"),
            clamping_delay=p.get("clamping_delay"),
            welding_time=p.get("welding_time"),
            air_speed=p.get("air_speed"),
            working_speed=p.get("working_speed"),
            hole_inlet_speed=p.get("hole_inlet_speed"),
        ))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown welding type '{w_type}' on model")

    db.commit()
    return {
        "status":       "Success",
        "message":      f"Welding data saved for {data.battery_id}",
        "welding_type": w_type,
    }