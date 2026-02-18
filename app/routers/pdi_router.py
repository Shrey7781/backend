import pandas as pd
import io
import numpy as np
from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.pdi import PDIReport
from app.models.battery_pack import Battery

router = APIRouter(prefix="/pdi", tags=["Pre-Delivery Inspection"])

@router.post("/upload-batch")
async def upload_batch_pdi(files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    summary = {"updated": [], "created": [], "errors": []}

    for file in files:
        try:
            contents = await file.read()
            df = pd.read_excel(io.BytesIO(contents))
            df = df.replace({np.nan: None})
            df.columns = df.columns.str.strip()

            for _, row in df.iterrows():
                bid = str(row['Internal SN']).strip()
                
                # 1. Verify battery exists in the system
                battery = db.query(Battery).filter(Battery.battery_id == bid).first()
                if not battery:
                    summary["errors"].append({"file": file.filename, "id": bid, "reason": "Not registered"})
                    continue

                # 2. OVERWRITE LOGIC: Check for existing PDI record
                report = db.query(PDIReport).filter(PDIReport.battery_id == bid).first()
                
                if report:
                    # OVERWRITE existing entry with new data
                    summary["updated"].append(bid)
                else:
                    # Create NEW entry
                    report = PDIReport(battery_id=bid)
                    db.add(report)
                    summary["created"].append(bid)

                # 3. Apply the latest values from the Excel file
                report.test_time = row.get('Time')
                report.voltage_v = row.get('Voltage(V)')
                report.resistance_m_ohm = row.get('Resistance(m¦¸)')
                report.cont_charging_current = row.get('Continuous Charging Current(A)')
                report.cont_charging_voltage = row.get('Continuous Charging Voltage(V)')
                report.cont_discharging_current = row.get('Continuous Discharging Current(A)')
                report.cont_discharging_voltage = row.get('Continuous Discharging Voltage(V)')
                report.short_circuit_prot_time_us = row.get('Short circuit protection time (uS)')
                report.test_result = str(row.get('Test Result', 'Unknown'))

        except Exception as e:
            summary["errors"].append({"file": file.filename, "reason": str(e)})

    # Single commit for all 150 files makes this very fast
    db.commit()

    return {
        "status": "Process Complete",
        "stats": {
            "total_files": len(files),
            "new_entries": len(summary["created"]),
            "overwritten_entries": len(summary["updated"]),
            "failed": len(summary["errors"])
        },
        "errors": summary["errors"]
    }