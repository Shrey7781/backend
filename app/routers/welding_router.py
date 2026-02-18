from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.welding import LaserWelding, SpotWelding
from app.models.battery_pack import Battery
from pydantic import BaseModel

router = APIRouter(prefix="/welding", tags=["Welding Operations"])

class WeldingSubmission(BaseModel):
    battery_id: str
    weld_type: str  # "laser" or "spot"
    parameters: dict

@router.post("/submit")
async def submit_welding_data(data: WeldingSubmission, db: Session = Depends(get_db)):
    # 1. Verify Battery Exists
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not registered")

    p = data.parameters
    w_type = data.weld_type.lower().strip()

    # 2. Route to Laser Table
    if w_type == "laser":
        new_entry = LaserWelding(
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
            lsm_laser_off_delay=p.get("lsm_laser_off_delay")
        )
        db.add(new_entry)

    # 3. Route to Spot Table
    elif w_type == "spot":
        new_entry = SpotWelding(
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
            hole_inlet_speed=p.get("hole_inlet_speed")
        )
        db.add(new_entry)

    else:
        raise HTTPException(status_code=400, detail="Invalid weld_type. Use 'laser' or 'spot'.")

    db.commit()
    return {"status": "Success", "message": f"Data saved to {w_type} welding table"}