from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class LaserWelding(Base):
    __tablename__ = "laser_welding_data"

    id = Column(Integer, primary_key=True, index=True)
    battery_id = Column(String, ForeignKey("batteries.battery_id"), index=True)
    
    # Parameters from Laser Machine
    initial_speed = Column(Float)
    max_speed = Column(Float)
    acceleration = Column(Float)
    laser_on_delay = Column(Integer)
    laser_off_delay = Column(Integer)
    point_duration = Column(Integer)
    power_mode = Column(String(50))
    pwm_freq = Column(Integer)
    pwm_cycle = Column(Integer)
    pwm_duty_rate = Column(Float)
    pwm_width = Column(Float)
    code = Column(Integer)
    dac_power = Column(Float)
    scan_speed = Column(Float)
    lsm_laser_on_delay = Column(Integer)
    lsm_laser_off_delay = Column(Integer)
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

class SpotWelding(Base):
    __tablename__ = "spot_welding_data"

    id = Column(Integer, primary_key=True, index=True)
    battery_id = Column(String, ForeignKey("batteries.battery_id"), index=True)
    
    # Parameters from Spot Machine
    solder_joint_mode = Column(String(100))
    welding_needle_direction = Column(String(100))
    hole_setback_distance = Column(Float)
    total_stroke_welding_head = Column(Float)
    start_delay = Column(Integer)
    clamping_delay = Column(Integer)
    welding_time = Column(Integer)
    air_speed = Column(Float)
    working_speed = Column(Float)
    hole_inlet_speed = Column(Float)
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now())