from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.pack_test import PackTest
from app.models.battery_pack import Battery, BatteryCellMapping
from app.models.battery import BatteryModel
from app.models.cell import Cell, CellGrading
from pydantic import BaseModel
from typing import List
import io
import pandas as pd
from app.core.signals import trigger_dashboard_update

# --- SCHEMAS (To make Swagger work) ---
class BatteryRegistrationRequest(BaseModel):
    battery_id: str
    model_id: str

class AssignCellsRequest(BaseModel):
    battery_id: str
    cell_ids: List[str]

router = APIRouter(prefix="/batteries", tags=["Battery Production"])

# --- ENDPOINTS ---

@router.post("/register")
async def register_battery(data: BatteryRegistrationRequest, db: Session = Depends(get_db)):

    battery_id = data.battery_id
    model_id = data.model_id

    # 1. Verify the Model ID exists
    model_exists = db.query(BatteryModel).filter(BatteryModel.model_id == model_id).first()
    if not model_exists:
        raise HTTPException(status_code=404, detail="Battery Model template not found")

    # 2. Check if this Battery ID is already registered
    existing_battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if existing_battery:
        raise HTTPException(status_code=400, detail="Battery ID already registered")

    # 3. Create the new Battery record
    new_battery = Battery(battery_id=battery_id, model_id=model_id)
    db.add(new_battery)
    db.commit()
    db.refresh(new_battery)
    await trigger_dashboard_update()

    return {
        "status": "Success",
        "message": f"Battery {battery_id} registered successfully",
        "data": {
            "battery_id": new_battery.battery_id,
            "model_id": new_battery.model_id
        }
    }

@router.post("/assign-cells")
async def assign_cells_to_battery(data: AssignCellsRequest, db: Session = Depends(get_db)):
    battery_id = data.battery_id
    cell_ids = data.cell_ids 

    # 1. Fetch Battery and Model
    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery Serial Number not found")
    
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Associated Model template missing")

    invalid_cells = []
    valid_mappings = []
    cells_to_update = []

    # 2. Validate each Cell
    for cid in cell_ids:
        cell = db.query(Cell).filter(Cell.cell_id == cid).first()
        if not cell:
            invalid_cells.append({"cell_id": cid, "reason": "Cell ID not registered"})
            continue
        
        if cell.is_used:
            invalid_cells.append({"cell_id": cid, "reason": "Already assigned elsewhere"})
            continue

        # Safety Check: Ensure the cell actually has test values to compare
        if any(v is None for v in [cell.ir_value_m_ohm, cell.sorting_voltage, cell.discharging_capacity_mah]):
            invalid_cells.append({"cell_id": cid, "reason": "Cell missing required sorting/grading data"})
            continue

        # 3. Parameter Range Checks
        is_valid = (
            model.cell_ir_lower <= cell.ir_value_m_ohm <= model.cell_ir_upper and 
            model.cell_voltage_lower <= cell.sorting_voltage <= model.cell_voltage_upper and
            model.cell_capacity_lower <= cell.discharging_capacity_mah <= model.cell_capacity_upper
        )

        if not is_valid:
            invalid_cells.append({
                "cell_id": cid,
                "reason": "Parameter mismatch",
                "actual_values": {
                    "ir": cell.ir_value_m_ohm,
                    "voltage": cell.sorting_voltage,
                    "capacity": cell.discharging_capacity_mah
                },
                "expected_ranges": {
                    "ir": f"{model.cell_ir_lower}-{model.cell_ir_upper}",
                    "vol": f"{model.cell_voltage_lower}-{model.cell_voltage_upper}",
                    "cap": f"{model.cell_capacity_lower}-{model.cell_capacity_upper}"
                }
            })
        else:
            # Everything looks good, prepare for update
            valid_mappings.append(BatteryCellMapping(battery_id=battery_id, cell_id=cid))
            cells_to_update.append(cell)

    # 4. Final Processing
    if invalid_cells:
        # If even ONE cell is bad, we don't commit anything (Atomicity)
        return {"status": "Error", "message": "Validation failed", "invalid_cells": invalid_cells}

    try:
        # Create the mapping entries
        db.add_all(valid_mappings)
        # Update the availability status in the cells table
        for cell in cells_to_update:
            cell.is_used = True
        
        db.commit()
        await trigger_dashboard_update()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {
        "status": "Success", 
        "message": f"Assigned {len(valid_mappings)} cells to {battery_id}"
    }

@router.post("/upload-report")
async def upload_pack_report_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")

    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # Clean column names
        df.columns = df.columns.str.strip()

        skipped_batteries = []
        ng_marked = []
        passed_and_updated = []

        for _, row in df.iterrows():
            bid = str(row['Barcode']).strip()
            
            # 1. Fetch Battery Record from the master batteries table
            battery = db.query(Battery).filter(Battery.battery_id == bid).first()
            
            if not battery:
                skipped_batteries.append(bid)
                continue

            # 2. Extract Final Result
            current_status = str(row['final Result']).strip().upper()

            # 3. Handle NG Flag Persistence on the Battery model
            if current_status == "FAIL":
                battery.had_ng_status = True
                ng_marked.append(bid)
            elif current_status == "PASS":
                passed_and_updated.append(bid)

            # 4. UPSERT LOGIC: Check if this battery already has a test record
            report = db.query(PackTest).filter(PackTest.battery_id == bid).first()

            if report:
                # UPDATE existing record with latest data
                report.test_date = row['Date']
                report.specification = str(row['Specification'])
                report.cell_type = str(row['Cell type'])
                report.number_of_series = int(row['Number of sreies'])
                report.number_of_parallel = int(row['Number of parallel'])
                report.ocv_voltage = float(row['OCV Voltage(V)'])
                report.upper_cutoff = float(row['Upper cut off(V)'])
                report.lower_cutoff = float(row['Lower cut off(V)'])
                report.discharging_capacity = float(row['Discharging Capacity(Ah)'])
                report.capacity_result = str(row['Result'])
                report.idle_difference = float(row['Final idle Different'])
                report.soc_result = str(row['SOC Result'])
                report.final_voltage = float(row['Final Voltage'])
                report.final_result = current_status
            else:
                # INSERT new record if it doesn't exist
                new_report = PackTest(
                    battery_id=bid,
                    test_date=row['Date'],
                    specification=str(row['Specification']),
                    cell_type=str(row['Cell type']),
                    number_of_series=int(row['Number of sreies']),
                    number_of_parallel=int(row['Number of parallel']),
                    ocv_voltage=float(row['OCV Voltage(V)']),
                    upper_cutoff=float(row['Upper cut off(V)']),
                    lower_cutoff=float(row['Lower cut off(V)']),
                    discharging_capacity=float(row['Discharging Capacity(Ah)']),
                    capacity_result=str(row['Result']),
                    idle_difference=float(row['Final idle Different']),
                    soc_result=str(row['SOC Result']),
                    final_voltage=float(row['Final Voltage']),
                    final_result=current_status
                )
                db.add(new_report)

        db.commit()
        await trigger_dashboard_update()

        return {
            "status": "Success",
            "summary": {
                "total_rows": len(df),
                "processed": len(ng_marked) + len(passed_and_updated),
                "marked_as_ng": len(ng_marked),
                "passed_and_updated": len(passed_and_updated),
                "skipped_unregistered": skipped_batteries
            }
        }

    except Exception as e:
        db.rollback()
        print(f"Excel Processing Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing Excel file: {str(e)}")
    
from pydantic import BaseModel

class ReplaceCellRequest(BaseModel):
    battery_id: str
    old_cell_id: str
    new_cell_id: str

@router.post("/replace-cell")
async def replace_leaked_cell(data: ReplaceCellRequest, db: Session = Depends(get_db)):
    # 1. Fetch Battery and its Model Template
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery Serial Number not found")
    
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Battery Model template not found")

    # 2. Verify the Old Cell is actually in this battery
    old_mapping = db.query(BatteryCellMapping).filter(
        BatteryCellMapping.battery_id == data.battery_id,
        BatteryCellMapping.cell_id == data.old_cell_id
    ).first()
    
    if not old_mapping:
        raise HTTPException(status_code=404, detail="The old cell is not linked to this battery")

    # 3. Fetch and Validate the New Replacement Cell
    new_cell = db.query(Cell).filter(Cell.cell_id == data.new_cell_id).first()
    if not new_cell:
        raise HTTPException(status_code=404, detail="New Replacement Cell ID not found in inventory")
    
    if new_cell.is_used:
        raise HTTPException(status_code=400, detail="This replacement cell is already assigned to another pack")

    # 4. Quality Parameter Validation (Same as Assign Cells)
    if any(v is None for v in [new_cell.ir_value_m_ohm, new_cell.sorting_voltage, new_cell.discharging_capacity_mah]):
        raise HTTPException(status_code=400, detail="Replacement cell is missing Grading/Sorting data")

    is_valid = (
        model.cell_ir_lower <= new_cell.ir_value_m_ohm <= model.cell_ir_upper and 
        model.cell_voltage_lower <= new_cell.sorting_voltage <= model.cell_voltage_upper and
        model.cell_capacity_lower <= new_cell.discharging_capacity_mah <= model.cell_capacity_upper
    )

    if not is_valid:
        raise HTTPException(status_code=400, detail={
            "error": "Replacement cell does not meet quality standards for this model",
            "required_ranges": {
                "ir": f"{model.cell_ir_lower}-{model.cell_ir_upper}",
                "voltage": f"{model.cell_voltage_lower}-{model.cell_voltage_upper}",
                "capacity": f"{model.cell_capacity_lower}-{model.cell_capacity_upper}"
            },
            "actual_values": {
                "ir": new_cell.ir_value_m_ohm,
                "voltage": new_cell.sorting_voltage,
                "capacity": new_cell.discharging_capacity_mah
            }
        })

    # 5. Atomic Swap Process
    try:
        # a. Remove old cell mapping and mark it as unused (or scrap)
        db.delete(old_mapping)
        old_cell_record = db.query(Cell).filter(Cell.cell_id == data.old_cell_id).first()
        if old_cell_record:
            old_cell_record.is_used = False
            # Optional: old_cell_record.status = "LEAKED"

        # b. Create new cell mapping
        new_mapping = BatteryCellMapping(battery_id=data.battery_id, cell_id=data.new_cell_id)
        db.add(new_mapping)
        
        # c. Mark new cell as used
        new_cell.is_used = True
        
        # d. Flag the Battery as having a repair history
        battery.had_ng_status = True

        db.commit()
        return {
            "status": "Success",
            "message": f"Successfully replaced {data.old_cell_id} with {data.new_cell_id}",
            "pack_id": data.battery_id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")