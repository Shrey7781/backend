import random
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from app.database import SessionLocal
from app.models.cell import Cell, CellGrading
from app.models.battery_pack import Battery, BatteryCellMapping
from app.models.battery import BatteryModel, WeldingType
from app.models.pack_test import PackTest
from app.models.pdi import PDIReport
from app.models.welding import LaserWelding
from app.models.bms import BMS
from app.models.dispatch import Dispatch

db = SessionLocal()

def generate_dummy_data(count=20):
    try:
        # 1. Ensure a Battery Model exists
        model = db.query(BatteryModel).first()
        if not model:
            model = BatteryModel(
                model_id="MX-48V-30Ah",
                category="Scooter",
                series_count=13,
                parallel_count=12,
                cell_ir_lower=12.0,
                cell_ir_upper=18.0,
                cell_voltage_lower=3.2,
                cell_voltage_upper=4.2,
                cell_capacity_lower=2400.0,
                cell_capacity_upper=2600.0,
                welding_type=WeldingType.LASER
            )
            db.add(model)
            db.commit()
            print("✅ Created default Battery Model")

        print(f"🚀 Generating data for {count} battery packs...")

        for i in range(count):
            start_time = datetime.now() - timedelta(days=random.randint(2, 30))
            # Start IDs at 3000 to avoid conflicts with previous attempts
            batt_id = f"BATT-2026-{3000 + i}" 
            
            # Failure tracking for the battery pack
            pack_has_failure = False
            
            # 2. Create Cells
            cell_ids = []
            for c in range(156):
                c_id = f"CELL-{batt_id}-{c:03d}"
                cell_ids.append(c_id)
                
                # Introduce a 3% random failure rate per cell
                is_ng = random.random() < 0.001
                if is_ng: pack_has_failure = True

                cell = Cell(
                    cell_id=c_id,
                    registration_date=start_time,
                    is_used=True,
                    status="FAILED" if is_ng else "GRADED",
                    ng_count=1 if is_ng else 0,
                    ir_value_m_ohm=round(random.uniform(19.0, 25.0), 2) if is_ng else round(random.uniform(12.5, 17.5), 2),
                    sorting_voltage=round(random.uniform(2.8, 3.4), 3) if is_ng else round(random.uniform(3.7, 4.1), 3),
                    sorting_date=start_time + timedelta(hours=1)
                )
                db.add(cell)
                
                # 3. Cell Grading
                grading = CellGrading(
                    cell_id=c_id,
                    test_date=start_time + timedelta(hours=1),
                    lot="LOT-B4",
                    brand="Samsung",
                    specification="25R",
                    ocv_voltage_mv=3200.0 if is_ng else 3850.0,
                    final_result="FAIL" if is_ng else "PASS"
                )
                db.add(grading)

            # Flush cells so Mapping can find them
            db.flush()

            # 4. Battery Pack
            battery = Battery(
                battery_id=batt_id,
                model_id=model.model_id,
                had_ng_status=pack_has_failure, # Linked to cell failures
                created_at=start_time + timedelta(hours=3)
            )
            db.add(battery)
            db.flush()

            # 5. Mapping
            for c_id in cell_ids:
                db.add(BatteryCellMapping(battery_id=batt_id, cell_id=c_id))

            # 6. BMS, Welding, Test, PDI, Dispatch
            db.add(BMS(
                bms_id=f"BMS-SN-{random.randint(100000, 999999)}",
                bms_model="JK-B2A24S",
                battery_id=batt_id,
                is_used=True
            ))

            db.add(LaserWelding(
                battery_id=batt_id,
                max_speed=120.0,
                scan_speed=100.0,
                power_mode="Continuous",
                pwm_freq=20000
            ))

            db.add(PackTest(
                battery_id=batt_id,
                test_date=start_time + timedelta(hours=5),
                discharging_capacity=22.0 if pack_has_failure else 29.5,
                final_result="Finished FAIL" if pack_has_failure else "Finished PASS"
            ))

            db.add(PDIReport(
                battery_id=batt_id,
                voltage_v=48.2 if pack_has_failure else 52.4,
                resistance_m_ohm=65.0 if pack_has_failure else 42.1,
                test_result="Finished FAIL" if pack_has_failure else "Finished PASS"
            ))

            db.add(Dispatch(
                battery_id=batt_id,
                customer_name=random.choice(["Ola", "Ather", "Hero"]),
                invoice_id=f"INV-{random.randint(1000,9999)}",
                invoice_date=start_time.date() + timedelta(days=1)
            ))

            db.commit()
            status_text = "❌ ISSUE" if pack_has_failure else "✅ PASS"
            print(f"📦 {status_text} | Pack: {batt_id}")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    generate_dummy_data(20)