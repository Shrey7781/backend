import pandas as pd
import io
import numpy as np
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db

# All models imported
from app.models.cell import Cell, CellGrading
from app.models.battery_pack import Battery, BatteryCellMapping
from app.models.battery import BatteryModel, WeldingType
from app.models.pack_test import PackTest
from app.models.pdi import PDIReport
from app.models.welding import LaserWelding, SpotWelding
from app.models.bms import BMS
from app.models.dispatch import Dispatch

router = APIRouter(prefix="/reports", tags=["Reports"])

def to_dict(obj):
    """Helper to convert SQLAlchemy object to dict and strip timezones for Excel compatibility"""
    if obj is None:
        return {}
    
    # Extract columns and values
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    
    # Critical Fix: Remove timezones from all datetime fields
    for key, value in data.items():
        if isinstance(value, datetime) and value.tzinfo is not None:
            data[key] = value.replace(tzinfo=None)
            
    return data

@router.get("/generate-full-audit/{battery_id}")
async def generate_full_audit(battery_id: str, db: Session = Depends(get_db)):
    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found")
    
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()

    # --- SHEET 1: CELL COMPLETE HISTORY ---
    cells_query = db.query(Cell, CellGrading).join(
        BatteryCellMapping, Cell.cell_id == BatteryCellMapping.cell_id
    ).outerjoin(
        CellGrading, Cell.cell_id == CellGrading.cell_id
    ).filter(BatteryCellMapping.battery_id == battery_id).all()

    cell_list = []
    for cell, grading in cells_query:
        c_dict = {f"cell_{k}": v for k, v in to_dict(cell).items()}
        g_dict = {f"grading_{k}": v for k, v in to_dict(grading).items()}
        cell_list.append({**c_dict, **g_dict})
    
    df_cells = pd.DataFrame(cell_list)

    # --- SHEET 2: MODEL, BMS & TESTING ---
    pack_test = db.query(PackTest).filter(PackTest.battery_id == battery_id).first()
    bms = db.query(BMS).filter(BMS.battery_id == battery_id).first()
    
    combined_summary = {
        **{f"Model_{k}": v for k, v in to_dict(model).items()},
        **{f"Test_{k}": v for k, v in to_dict(pack_test).items()},
        **{f"BMS_{k}": v for k, v in to_dict(bms).items()},
        "NG_History_Flag": battery.had_ng_status
    }
    df_pack = pd.DataFrame([combined_summary])

    # --- SHEET 3: WELDING MACHINE LOGS ---
    if model.welding_type == WeldingType.LASER:
        weld_data = db.query(LaserWelding).filter(LaserWelding.battery_id == battery_id).all()
    else:
        weld_data = db.query(SpotWelding).filter(SpotWelding.battery_id == battery_id).all()
    
    df_welding = pd.DataFrame([to_dict(w) for w in weld_data])

    # --- SHEET 4: PDI & DISPATCH ---
    pdi = db.query(PDIReport).filter(PDIReport.battery_id == battery_id).first()
    dispatch = db.query(Dispatch).filter(Dispatch.battery_id == battery_id).first()
    
    final_dict = {
        **{f"PDI_{k}": v for k, v in to_dict(pdi).items()},
        **{f"Sales_{k}": v for k, v in to_dict(dispatch).items()}
    }
    df_final = pd.DataFrame([final_dict])

    # --- FINAL SAFETY CLEANUP: STRIP ANY REMAINING TIMEZONES ---
    for df in [df_cells, df_pack, df_welding, df_final]:
        if not df.empty:
            for col in df.columns:
                if pd.api.types.is_datetime64tz_dtype(df[col]):
                    df[col] = df[col].dt.tz_localize(None)

    # --- EXCEL GENERATION ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        sheets = {
            'Cells_Complete_History': df_cells,
            'Model_BMS_Testing': df_pack,
            'Welding_Machine_Logs': df_welding,
            'PDI_and_Dispatch': df_final
        }
        
        for name, df in sheets.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
            else:
                pd.DataFrame({"Message": ["No data found"]}).to_excel(writer, sheet_name=name, index=False)

        workbook = writer.book
        for worksheet in writer.sheets.values():
            worksheet.set_column('A:ZZ', 20)

    output.seek(0)
    return StreamingResponse(
        output, 
        headers={'Content-Disposition': f'attachment; filename="Full_Audit_{battery_id}.xlsx"'},
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )