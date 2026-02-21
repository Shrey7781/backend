import pandas as pd
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db

# Models
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
    if obj is None: return {}
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for key, value in data.items():
        if isinstance(value, datetime) and value.tzinfo is not None:
            data[key] = value.replace(tzinfo=None)
    return data

@router.get("/generate-full-audit/{battery_id}")
async def generate_full_audit(battery_id: str, db: Session = Depends(get_db)):
    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found")
    
    # --- DATA FETCHING ---
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    pack_test = db.query(PackTest).filter(PackTest.battery_id == battery_id).first()
    bms = db.query(BMS).filter(BMS.battery_id == battery_id).first()
    pdi = db.query(PDIReport).filter(PDIReport.battery_id == battery_id).first()
    dispatch = db.query(Dispatch).filter(Dispatch.battery_id == battery_id).first()

    # --- DATAFRAME PREPARATION ---
    
    # 1. Cells (Keep Horizontal because it's a multi-row list)
    cells_query = db.query(Cell, CellGrading).join(
        BatteryCellMapping, Cell.cell_id == BatteryCellMapping.cell_id
    ).outerjoin(CellGrading, Cell.cell_id == CellGrading.cell_id).filter(BatteryCellMapping.battery_id == battery_id).all()
    
    df_cells = pd.DataFrame([{**{f"Cell_{k}": v for k, v in to_dict(c).items()}, 
                              **{f"Grading_{k}": v for k, v in to_dict(g).items()}} for c, g in cells_query])

    # 2. Welding Logs (Keep Horizontal as there are usually many points)
    weld_data = db.query(LaserWelding if model.welding_type == WeldingType.LASER else SpotWelding).filter(
        (LaserWelding.battery_id if model.welding_type == WeldingType.LASER else SpotWelding.battery_id) == battery_id).all()
    df_welding = pd.DataFrame([to_dict(w) for w in weld_data])

    # 3. Vertical Summary DataFrames
    # Injecting NG Status clearly into the Model Data
    model_data = to_dict(model)
    model_data["Repair_History_NG_Flag"] = "YES (NG FOUND)" if battery.had_ng_status else "NO (CLEAN)"
    
    df_model = pd.DataFrame([model_data])
    df_bms = pd.DataFrame([to_dict(bms)])
    df_test = pd.DataFrame([to_dict(pack_test)])
    df_pdi = pd.DataFrame([to_dict(pdi)])
    df_dispatch = pd.DataFrame([to_dict(dispatch)])

    # --- EXCEL GENERATION ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # --- FORMATS ---
        title_format = workbook.add_format({
            'bold': True, 'font_size': 16, 'font_color': '#1B3A5C', 'align': 'center', 'valign': 'vcenter'
        })
        meta_format = workbook.add_format({
            'font_size': 10, 'italic': True, 'font_color': '#5A6178', 'align': 'center'
        })
        header_format = workbook.add_format({
            'bold': True, 'valign': 'vcenter', 'align': 'center',
            'fg_color': '#1B3A5C', 'font_color': 'white', 'border': 1
        })
        v_header_format = workbook.add_format({
            'bold': True, 'valign': 'vcenter', 'align': 'left',
            'fg_color': '#F7F8FA', 'font_color': '#1B3A5C', 'border': 1
        })
        cell_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'text_wrap': True
        })
        pass_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'bold': True})
        fail_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True})

        # --- HELPER TO ADD BRANDING ---
        def add_branding(ws, title):
            ws.merge_range('A1:C1', "MAXVOLT ENERGY INDUSTRIES LTD.", title_format)
            ws.merge_range('A2:C2', f"REPORT: {title} | GENERATED: {datetime.now().strftime('%Y-%m-%d %H:%M')}", meta_format)

        # --- 1. HORIZONTAL SHEETS (Cells & Welding) ---
        horizontal_sheets = {'Cell History': df_cells, 'Welding Logs': df_welding}
        for name, df in horizontal_sheets.items():
            df.to_excel(writer, sheet_name=name, startrow=3, index=False)
            ws = writer.sheets[name]
            add_branding(ws, name.upper())
            for col_num, value in enumerate(df.columns.values):
                ws.set_column(col_num, col_num, 22, cell_format)
                ws.write(3, col_num, value, header_format)

        # --- 2. VERTICAL SHEETS (Model, BMS, Test, PDI, Dispatch) ---
        vertical_sheets = {
            'Battery Model': df_model,
            'BMS Details': df_bms,
            'Pack Test Results': df_test,
            'PDI Report': df_pdi,
            'Dispatch Info': df_dispatch
        }

        for name, df in vertical_sheets.items():
            ws = workbook.add_worksheet(name)
            add_branding(ws, name.upper())
            
            if not df.empty:
                v_data = df.T.reset_index()
                v_data.columns = ['Parameter', 'Value']
                
                # Write vertical data
                for row_num, row in v_data.iterrows():
                    ws.write(row_num + 3, 0, str(row['Parameter']), v_header_format)
                    ws.write(row_num + 3, 1, str(row['Value']), cell_format)
                
                ws.set_column('A:A', 35)
                ws.set_column('B:B', 50)
                
                # Apply conditional color to the Value column
                ws.conditional_format(3, 1, len(v_data) + 3, 1, {
                    'type': 'cell', 'criteria': 'containing', 'value': 'PASS', 'format': pass_format
                })
                ws.conditional_format(3, 1, len(v_data) + 3, 1, {
                    'type': 'cell', 'criteria': 'containing', 'value': 'NG', 'format': fail_format
                })
                ws.conditional_format(3, 1, len(v_data) + 3, 1, {
                    'type': 'cell', 'criteria': 'containing', 'value': 'FAIL', 'format': fail_format
                })
            else:
                ws.write(3, 0, "No data available for this section", cell_format)

    output.seek(0)
    return StreamingResponse(
        output, 
        headers={'Content-Disposition': f'attachment; filename="Maxvolt_Audit_{battery_id}.xlsx"'},
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )