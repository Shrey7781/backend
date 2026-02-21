import pandas as pd
import io
import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
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

# --- CONFIGURATION ---
LOGO_PATH = "assets/maxvolt_logo.png"
WATERMARK_PATH = "assets/maxvolt_watermark.png"

PARAM_MAPPING = {
    "battery_id": "Battery Serial Number",
    "model_id": "Model Configuration ID",
    "cont_charging_current": "Constant Charging Current (A)",
    "max_discharging_current": "Max Discharging Current (A)",
    "nominal_voltage": "Nominal Voltage (V)",
    "target_cap_ah": "Target Capacity (Ah)",
    "Repair_History_NG_Flag": "Repair History (NG Found)",
    "bms_serial_no": "BMS Serial Number",
    "working_mode": "Testing Mode",
    "end_v": "End Voltage (V)",
    "cap_ah": "Final Capacity (Ah)",
    "ocv_volts": "OCV (V)",
    "aclr_mohm": "ACLR (mΩ)",
    "final_status": "Overall Status",
    "customer_name": "Customer Name",
    "remark": "Technical Remarks",
    "welding_point_count": "Total Welding Points"
}

def clean_label(label: str) -> str:
    return PARAM_MAPPING.get(label, label.replace('_', ' ').title())

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
    
    weld_query = db.query(LaserWelding if model.welding_type == WeldingType.LASER else SpotWelding).filter(
        (LaserWelding.battery_id if model.welding_type == WeldingType.LASER else SpotWelding.battery_id) == battery_id).first()
    
    cells_query = db.query(Cell, CellGrading).join(
        BatteryCellMapping, Cell.cell_id == BatteryCellMapping.cell_id
    ).outerjoin(CellGrading, Cell.cell_id == CellGrading.cell_id).filter(BatteryCellMapping.battery_id == battery_id).all()
    
    df_cells = pd.DataFrame([{**{f"Cell_{k}": v for k, v in to_dict(c).items()}, 
                              **{f"Grading_{k}": v for k, v in to_dict(g).items()}} for c, g in cells_query])

    model_info = to_dict(model)
    model_info["Repair_History_NG_Flag"] = "YES (NG FOUND)" if battery.had_ng_status else "NO (CLEAN)"

    summary_list = [
        {"Station": "Cell Traceability", "Status": "PASS" if not df_cells.empty else "PENDING"},
        {"Station": "Welding Process", "Status": "PASS" if weld_query else "PENDING"},
        {"Station": "BMS Configuration", "Status": "PASS" if bms else "PENDING"},
        {"Station": "Pack Testing", "Status": getattr(pack_test, 'final_result', 'PENDING') if pack_test else "PENDING"},
        {"Station": "PDI Inspection", "Status": getattr(pdi, 'test_result', 'PENDING') if pdi else "PENDING"},
        {"Station": "Dispatch Status", "Status": "SHIPPED" if dispatch else "IN STOCK"}
    ]
    df_summary = pd.DataFrame(summary_list)

    vertical_sheets = {
        'Battery Model': pd.DataFrame([model_info]),
        'Welding Data': pd.DataFrame([to_dict(weld_query)]),
        'BMS Details': pd.DataFrame([to_dict(bms)]),
        'Pack Test Results': pd.DataFrame([to_dict(pack_test)]),
        'PDI Report': pd.DataFrame([to_dict(pdi)]),
        'Dispatch Info': pd.DataFrame([to_dict(dispatch)])
    }

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # --- FORMATS ---
        title_format = workbook.add_format({
            'bold': True, 'font_size': 22, 'font_color': '#1B3A5C', 
            'align': 'left', 'valign': 'vcenter'
        })
        meta_format = workbook.add_format({
            'font_size': 12, 'italic': True, 'font_color': '#5A6178', 
            'align': 'left', 'valign': 'vcenter'
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

        def add_branding(ws, title):
            # 1. Row Heights for Logo and Text
            ws.set_row(0, 110) # Logo row
            ws.set_row(1, 40)  # Metadata row
            
            # 2. Column Widths
            ws.set_column('A:A', 28) # Logo Cell
            ws.set_column('B:B', 65) # Text Details Cell (Widened for Company/Station)
            
            # 3. Insert Logo (Centered via offset)
            if os.path.exists(LOGO_PATH):
                ws.insert_image('A1', LOGO_PATH, {
                    'x_scale': 1.0, 
                    'y_scale': 1.0, 
                    'x_offset': 15, 
                    'y_offset': 15,
                    'object_position': 1
                })
            
            # 4. Branding Text (Starting Column B)
            ws.write('B1', "MAXVOLT ENERGY INDUSTRIES LTD.", title_format)
            ws.write('B2', f"STATION: {title} | ID: {battery_id} | DATE: {datetime.now().strftime('%d-%m-%Y %H:%M')}", meta_format)
            
            # 5. Watermark (Only visible in Page Layout/Print View)
            if os.path.exists(WATERMARK_PATH):
                ws.set_header('&C&G', {'image_center': WATERMARK_PATH})

        # --- SHEET GENERATION ---
        
        # 1. EXECUTIVE SUMMARY
        ws_sum = workbook.add_worksheet('EXECUTIVE SUMMARY')
        add_branding(ws_sum, "OVERALL AUDIT SUMMARY")
        ws_sum.write(3, 0, "Production Station", header_format)
        ws_sum.write(3, 1, "Completion Status", header_format)
        for i, row in df_summary.iterrows():
            ws_sum.write(i+4, 0, row['Station'], v_header_format)
            ws_sum.write(i+4, 1, row['Status'], cell_format)
        
        ws_sum.set_column('A:A', 40)
        ws_sum.set_column('B:B', 30)
        ws_sum.conditional_format('B5:B10', {'type': 'cell', 'criteria': 'containing', 'value': 'PASS', 'format': pass_format})
        ws_sum.conditional_format('B5:B10', {'type': 'cell', 'criteria': 'containing', 'value': 'SHIPPED', 'format': pass_format})
        ws_sum.conditional_format('B5:B10', {'type': 'cell', 'criteria': 'containing', 'value': 'FAIL', 'format': fail_format})

        # 2. CELL HISTORY (Centered Data)
        sheet_name = 'Cell History'
        # Write dataframe starting at row 4, without automatic headers
        df_cells.to_excel(writer, sheet_name=sheet_name, startrow=4, index=False, header=False)
        ws_cells = writer.sheets[sheet_name]
        add_branding(ws_cells, "CELL TRACEABILITY")
        
        for col_num, col_name in enumerate(df_cells.columns):
            # Custom Header
            ws_cells.write(3, col_num, clean_label(col_name), header_format)
            # Center all data in this column
            ws_cells.set_column(col_num, col_num, 28, cell_format)

        # 3. VERTICAL SUMMARY SHEETS
        for name, df in vertical_sheets.items():
            ws = workbook.add_worksheet(name)
            add_branding(ws, name.upper())
            if not df.empty:
                v_data = df.T.reset_index()
                v_data.columns = ['Parameter', 'Value']
                for row_num, row in v_data.iterrows():
                    ws.write(row_num + 3, 0, clean_label(str(row['Parameter'])), v_header_format)
                    ws.write(row_num + 3, 1, str(row['Value']) if row['Value'] is not None else "N/A", cell_format)
                
                ws.set_column('A:A', 45) # Parameter Name Column
                ws.set_column('B:B', 65) # Value Column
                
                # Apply Coloring to the Value column
                ws.conditional_format(3, 1, len(v_data)+3, 1, {'type': 'cell', 'criteria': 'containing', 'value': 'PASS', 'format': pass_format})
                ws.conditional_format(3, 1, len(v_data)+3, 1, {'type': 'cell', 'criteria': 'containing', 'value': 'FAIL', 'format': fail_format})
                ws.conditional_format(3, 1, len(v_data)+3, 1, {'type': 'cell', 'criteria': 'containing', 'value': 'NG', 'format': fail_format})
            else:
                ws.write(3, 0, "No data logged for this station.", cell_format)

    output.seek(0)
    return StreamingResponse(
        output, 
        headers={'Content-Disposition': f'attachment; filename="Maxvolt_Audit_{battery_id}.xlsx"'},
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )