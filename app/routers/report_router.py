import io
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db

from app.models.cell import Cell, CellGrading
from app.models.battery_pack import Battery, BatteryCellMapping
from app.models.battery import BatteryModel, WeldingType
from app.models.pack_test import PackTest
from app.models.pdi import PDIReport
from app.models.welding import LaserWelding, SpotWelding
from app.models.bms import BMS
from app.models.dispatch import Dispatch

router = APIRouter(prefix="/reports", tags=["Reports"])

LOGO_PATH = "assets/maxvolt_logo.png"

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
C_NAVY       = "#1B3A5C"
C_NAVY_LIGHT = "#2A5280"
C_SLATE      = "#4A5568"
C_ICE        = "#EBF4FF"
C_WHITE      = "#FFFFFF"
C_LIGHT_GREY = "#F7F9FC"
C_MID_GREY   = "#E2E8F0"
C_DARK_GREY  = "#718096"
C_GREEN_BG   = "#D4EDDA";  C_GREEN_FG  = "#155724"
C_RED_BG     = "#F8D7DA";  C_RED_FG    = "#721C24"
C_AMBER_BG   = "#FFF3CD";  C_AMBER_FG  = "#856404"
C_BLUE_BG    = "#D1ECF1";  C_BLUE_FG   = "#0C5460"
CH_BLUE      = "#2D6BCE";  CH_GREEN    = "#27AE60"
CH_ORANGE    = "#E67E22";  CH_RED      = "#E74C3C"

# ─────────────────────────────────────────────────────────────────────────────
# LABELS
# ─────────────────────────────────────────────────────────────────────────────
LABELS = {
    "battery_id": "Battery Serial No.", "model_id": "Model Name",
    "category": "Category", "series_count": "Series Count (S)",
    "parallel_count": "Parallel Count (P)", "total_cells": "Total Cells",
    "cell_type": "Cell Chemistry", "bms_model": "Expected BMS Model",
    "welding_type": "Welding Type", "overall_status": "Production Status",
    "had_ng_status": "NG / Repair History", "created_at": "Created At",
    "cell_ir_lower": "IR Lower Limit (mΩ)", "cell_ir_upper": "IR Upper Limit (mΩ)",
    "cell_voltage_lower": "Voltage Lower (V)", "cell_voltage_upper": "Voltage Upper (V)",
    "cell_capacity_lower": "Capacity Lower (mAh)", "cell_capacity_upper": "Capacity Upper (mAh)",
    "cell_id": "Cell ID", "status": "Status", "ng_count": "NG Count",
    "is_used": "Assigned", "registration_date": "Registered",
    "discharging_capacity_mah": "Capacity (mAh)", "last_test_date": "Last Tested",
    "ir_value_m_ohm": "IR (mΩ)", "sorting_voltage": "Voltage (V)",
    "sorting_date": "Sorted On", "test_date": "Test Date",
    "lot": "Lot", "brand": "Brand", "specification": "Specification",
    "ocv_voltage_mv": "OCV (mV)", "upper_cutoff_mv": "Upper Cutoff (mV)",
    "lower_cutoff_mv": "Lower Cutoff (mV)", "result": "Result",
    "final_soc_mah": "Final SOC (mAh)", "soc_result": "SOC Result",
    "final_cv_capacity": "Final CV Capacity", "final_result": "Final Result",
    "ocv_voltage": "OCV Voltage (V)", "upper_cutoff": "Upper Cutoff (V)",
    "lower_cutoff": "Lower Cutoff (V)", "discharging_capacity": "Discharging Capacity (Ah)",
    "capacity_result": "Capacity Result", "idle_difference": "Idle Difference","idle_diff_res":"Idle Difference Result",
    "final_voltage": "Final Voltage (V)", "test_time": "Test Time",
    "voltage_v": "Voltage (V)", "resistance_m_ohm": "Resistance (mΩ)",
    "cont_charging_current": "Cont. Charging Current (A)",
    "cont_charging_voltage": "Cont. Charging Voltage (V)",
    "cont_discharging_current": "Cont. Discharging Current (A)",
    "cont_discharging_voltage": "Cont. Discharging Voltage (V)",
    "short_circuit_prot_time_us": "Short Circuit Prot. Time (µs)",
    "test_result": "PDI Result", "updated_at": "Updated At",
    "bms_id": "BMS Unit ID", "added_at": "Mounted At",
    "customer_name": "Customer", "invoice_id": "Invoice ID",
    "invoice_date": "Invoice Date", "dispatch_timestamp": "Dispatched At",
    "initial_speed": "Initial Speed (mm/s)", "max_speed": "Max Speed (mm/s)",
    "acceleration": "Acceleration (mm/s²)", "laser_on_delay": "Laser On Delay (ms)",
    "laser_off_delay": "Laser Off Delay (ms)", "point_duration": "Point Duration",
    "power_mode": "Power Mode", "pwm_freq": "PWM Frequency (Hz)",
    "pwm_cycle": "PWM Cycle (ms)", "pwm_duty_rate": "PWM Duty Rate (%)",
    "pwm_width": "PWM Width (ms)", "code": "Code", "dac_power": "DAC Power (%)",
    "scan_speed": "Scan Speed (mm/s)", "lsm_laser_on_delay": "LSM On Delay (µs)",
    "lsm_laser_off_delay": "LSM Off Delay (µs)",
    "solder_joint_mode": "Solder Joint Mode",
    "welding_needle_direction": "Needle Direction",
    "hole_setback_distance": "Hole Setback (mm)",
    "total_stroke_welding_head": "Total Stroke (mm)",
    "start_delay": "Start Delay (ms)", "clamping_delay": "Clamping Delay (ms)",
    "welding_time": "Welding Time (ms)", "air_speed": "Air Speed (%)",
    "working_speed": "Working Speed (%)", "hole_inlet_speed": "Hole Inlet Speed (%)",
    "timestamp": "Recorded At", "id": None,
}
SKIP = {"id"}


def lbl(k):
    v = LABELS.get(k)
    return v if v else k.replace("_", " ").title()


def clean(v):
    if v is None:
        return "—"
    if isinstance(v, datetime):
        return v.strftime("%d %b %Y  %H:%M")
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return v


def obj_pairs(obj, extra=None):
    if obj is None:
        return []
    out = []
    for col in obj.__table__.columns:
        if col.name in SKIP or LABELS.get(col.name) is None:
            continue
        out.append((lbl(col.name), clean(getattr(obj, col.name))))
    if extra:
        for k, v in extra.items():
            out.append((k, clean(v)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT FACTORY
# ─────────────────────────────────────────────────────────────────────────────
def build_formats(wb):
    def f(**kw):
        return wb.add_format({**dict(font_name="Calibri", valign="vcenter"), **kw})

    return {
        "pg_company": f(bold=True, font_size=15, font_color=C_WHITE, bg_color=C_NAVY,
                        align="left", border=0),
        "pg_divider": f(bg_color=C_NAVY_LIGHT, border=0),
        "pg_meta":    f(font_size=9, italic=True, font_color="#A8CAEC",
                        bg_color=C_NAVY, align="left", border=0),
        "sec_hdr":    f(bold=True, font_size=10, font_color=C_WHITE,
                        bg_color=C_NAVY_LIGHT, align="left", border=1,
                        border_color=C_MID_GREY),
        "kv_key":     f(bold=True, font_size=9, font_color=C_NAVY,
                        bg_color=C_ICE, align="left", border=1, border_color=C_MID_GREY),
        "kv_val":     f(font_size=9, font_color=C_SLATE, bg_color=C_WHITE,
                        align="left", border=1, border_color=C_MID_GREY, text_wrap=True),
        "kv_alt":     f(font_size=9, font_color=C_SLATE, bg_color=C_LIGHT_GREY,
                        align="left", border=1, border_color=C_MID_GREY, text_wrap=True),
        "kv_pass":    f(bold=True, font_size=9, font_color=C_GREEN_FG,
                        bg_color=C_GREEN_BG, align="left", border=1, border_color=C_MID_GREY),
        "kv_fail":    f(bold=True, font_size=9, font_color=C_RED_FG,
                        bg_color=C_RED_BG, align="left", border=1, border_color=C_MID_GREY),
        "kv_warn":    f(bold=True, font_size=9, font_color=C_AMBER_FG,
                        bg_color=C_AMBER_BG, align="left", border=1, border_color=C_MID_GREY),
        "kv_info":    f(bold=True, font_size=9, font_color=C_BLUE_FG,
                        bg_color=C_BLUE_BG, align="left", border=1, border_color=C_MID_GREY),
        "kv_num":     f(bold=True, font_size=9, font_color=C_NAVY, bg_color=C_WHITE,
                        align="right", border=1, border_color=C_MID_GREY),
        "th":         f(bold=True, font_size=8, font_color=C_WHITE,
                        bg_color=C_NAVY, align="center", border=1,
                        border_color=C_MID_GREY, text_wrap=True),
        "td":         f(font_size=8, font_color=C_SLATE, bg_color=C_WHITE,
                        align="center", border=1, border_color=C_MID_GREY),
        "td_alt":     f(font_size=8, font_color=C_SLATE, bg_color=C_LIGHT_GREY,
                        align="center", border=1, border_color=C_MID_GREY),
        "td_pass":    f(bold=True, font_size=8, font_color=C_GREEN_FG,
                        bg_color=C_GREEN_BG, align="center", border=1, border_color=C_MID_GREY),
        "td_fail":    f(bold=True, font_size=8, font_color=C_RED_FG,
                        bg_color=C_RED_BG, align="center", border=1, border_color=C_MID_GREY),
        "td_warn":    f(bold=True, font_size=8, font_color=C_AMBER_FG,
                        bg_color=C_AMBER_BG, align="center", border=1, border_color=C_MID_GREY),
        "sc_label":   f(bold=True, font_size=10, font_color=C_SLATE, bg_color=C_ICE,
                        align="left", border=1, border_color=C_MID_GREY),
        "sc_pass":    f(bold=True, font_size=10, font_color=C_GREEN_FG,
                        bg_color=C_GREEN_BG, align="center", border=1, border_color=C_MID_GREY),
        "sc_fail":    f(bold=True, font_size=10, font_color=C_RED_FG,
                        bg_color=C_RED_BG, align="center", border=1, border_color=C_MID_GREY),
        "sc_pend":    f(bold=True, font_size=10, font_color=C_AMBER_FG,
                        bg_color=C_AMBER_BG, align="center", border=1, border_color=C_MID_GREY),
        "kpi_num":    f(bold=True, font_size=22, font_color=C_NAVY, bg_color=C_ICE,
                        align="center", valign="vcenter", border=1, border_color=C_MID_GREY),
        "kpi_pass":   f(bold=True, font_size=22, font_color=C_GREEN_FG,
                        bg_color=C_GREEN_BG, align="center", valign="vcenter",
                        border=1, border_color=C_MID_GREY),
        "kpi_fail":   f(bold=True, font_size=22, font_color=C_RED_FG,
                        bg_color=C_RED_BG, align="center", valign="vcenter",
                        border=1, border_color=C_MID_GREY),
        "kpi_warn":   f(bold=True, font_size=22, font_color=C_AMBER_FG,
                        bg_color=C_AMBER_BG, align="center", valign="vcenter",
                        border=1, border_color=C_MID_GREY),
        "kpi_label":  f(bold=True, font_size=8, font_color=C_DARK_GREY,
                        bg_color=C_WHITE, align="center", valign="vcenter",
                        border=1, border_color=C_MID_GREY,
                        text_wrap=True),
    }


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

HEADER_ROWS = 5   # rows 0–4 consumed by page header + spacer


def add_page_header(ws, wb, fmt, battery_id, sheet_title, subtitle=""):
    ws.set_row(0, 42)
    ws.set_row(1, 5)
    ws.set_row(2, 19)
    ws.set_row(3, 6)
    ws.merge_range("A1:J1",
        f"  MAXVOLT ENERGY INDUSTRIES LTD.   ·   {sheet_title.upper()}",
        fmt["pg_company"])
    ws.merge_range("A2:J2", "", fmt["pg_divider"])
    ws.merge_range("A3:J3",
        f"  Battery: {battery_id}     |     {subtitle or sheet_title}     |     "
        f"Generated: {datetime.now().strftime('%d %b %Y  %H:%M')}",
        fmt["pg_meta"])
    if os.path.exists(LOGO_PATH):
        ws.insert_image("H1", LOGO_PATH, {
            "x_scale": 0.48, "y_scale": 0.48,
            "x_offset": 8, "y_offset": 5, "object_position": 1,
        })
    return HEADER_ROWS


def _vfmt(val_str, fmt, is_alt=False):
    v = val_str.strip().upper()
    if any(x in v for x in ("PASS", "DISPATCHED", "COMPLETE", "CLEAN", "✔", "YES")):
        return fmt["kv_pass"]
    if any(x in v for x in ("FAIL", "NG", "ERROR", "⚠")):
        return fmt["kv_fail"]
    if any(x in v for x in ("PENDING", "NOT ", "—")):
        return fmt["kv_warn"]
    if any(x in v for x in ("LASER", "SPOT", "NMC", "LFP")):
        return fmt["kv_info"]
    return fmt["kv_alt"] if is_alt else fmt["kv_val"]


def write_kv_section(ws, fmt, row, title, pairs, key_w=34, val_w=46):
    """Write section header + KV rows. Returns next free row."""
    if not pairs:
        return row
    ws.set_column(0, 0, key_w)
    ws.set_column(1, 1, val_w)
    ws.set_row(row, 20)
    ws.merge_range(row, 0, row, 1, f"   {title}", fmt["sec_hdr"])
    row += 1
    for i, (key, val) in enumerate(pairs):
        ws.set_row(row, 17)
        ws.write(row, 0, f"  {key}", fmt["kv_key"])
        val_str = str(val) if val is not None else "—"
        try:
            float(val_str.replace(",", "").replace("—", "x"))
            vfmt = fmt["kv_num"]
        except ValueError:
            vfmt = _vfmt(val_str, fmt, i % 2 == 1)
        ws.write(row, 1, val_str, vfmt)
        row += 1
    ws.set_row(row, 8)
    return row + 2


def chart_style(chart, title):
    """Apply consistent minimal chart styling."""
    chart.set_title({"name": title,
                     "name_font": {"size": 10, "bold": True,
                                   "color": C_NAVY, "name": "Calibri"}})
    chart.set_legend({"none": True})
    chart.set_chartarea({"border": {"none": True}, "fill": {"color": C_WHITE}})
    chart.set_plotarea({"fill": {"color": "#F8FAFC"},
                        "border": {"color": C_MID_GREY, "width": 0.5}})
    chart.set_x_axis({"major_gridlines": {"visible": False},
                      "line": {"color": C_MID_GREY},
                      "num_font":  {"size": 7, "color": C_DARK_GREY, "name": "Calibri"},
                      "name_font": {"size": 8, "color": C_SLATE,     "name": "Calibri"}})
    chart.set_y_axis({"major_gridlines": {"visible": True,
                       "line": {"color": C_MID_GREY, "dash_type": "dash", "width": 0.5}},
                      "line": {"none": True},
                      "num_font":  {"size": 7, "color": C_DARK_GREY, "name": "Calibri"},
                      "name_font": {"size": 8, "color": C_SLATE,     "name": "Calibri"}})


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/generate-full-audit/{battery_id}")
async def generate_full_audit(battery_id: str, db: Session = Depends(get_db)):

    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found")

    mdl       = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    pack_test = db.query(PackTest).filter(PackTest.battery_id == battery_id).first()
    bms       = db.query(BMS).filter(BMS.battery_id == battery_id).first()
    pdi       = db.query(PDIReport).filter(PDIReport.battery_id == battery_id).first()
    dispatch  = db.query(Dispatch).filter(Dispatch.battery_id == battery_id).first()

    WeldModel = LaserWelding if (mdl and mdl.welding_type == WeldingType.LASER) else SpotWelding
    weld = db.query(WeldModel).filter(WeldModel.battery_id == battery_id).first()

    cells_raw = (
        db.query(Cell, CellGrading)
        .join(BatteryCellMapping, Cell.cell_id == BatteryCellMapping.cell_id)
        .outerjoin(CellGrading, Cell.cell_id == CellGrading.cell_id)
        .filter(BatteryCellMapping.battery_id == battery_id)
        .all()
    )

    output = io.BytesIO()
    with __import__("xlsxwriter").Workbook(output, {"in_memory": True}) as wb:
        fmt = build_formats(wb)

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 1 — SUMMARY
        # ══════════════════════════════════════════════════════════════════════
        ws1 = wb.add_worksheet("Summary")
        ws1.hide_gridlines(2)
        ws1.set_zoom(90)
        ws1.set_column("A:A", 30)
        ws1.set_column("B:B", 22)
        ws1.set_column("C:C", 3)
        ws1.set_column("D:D", 18)
        ws1.set_column("E:E", 18)
        ws1.set_column("F:F", 18)
        ws1.set_column("G:G", 18)

        row = add_page_header(ws1, wb, fmt, battery_id,
                              "Executive Summary", "Production Status Report")

        stations = [
            ("Cell Assembly",  bool(cells_raw)),
            ("Welding",        weld is not None),
            ("BMS Mounting",   bms  is not None),
            ("Pack Testing",   pack_test is not None
                               and getattr(pack_test, "final_result", "").upper() == "PASS"),
            ("PDI Inspection", pdi is not None
                               and getattr(pdi, "test_result", "") == "Finished PASS"),
            ("Dispatch",       dispatch is not None),
        ]
        done_count = sum(1 for _, d in stations if d)

        # ── Pipeline checklist ────────────────────────────────────────────────
        ws1.set_row(row, 20)
        ws1.merge_range(row, 0, row, 1, "   PRODUCTION PIPELINE", fmt["sec_hdr"])
        row += 1
        pipeline_data_row = row

        for i, (stage, done) in enumerate(stations):
            ws1.set_row(row, 20)
            ws1.write(row, 0, f"  {i+1}.  {stage}", fmt["kv_key"])
            ws1.write(row, 1,
                      "  ✔  COMPLETE" if done else "  ○  PENDING",
                      fmt["sc_pass"] if done else fmt["sc_pend"])
            row += 1

        ws1.set_row(row, 10); row += 1

        ws1.set_row(row, 20)
        ws1.merge_range(row, 0, row, 1,
            f"  {done_count} / {len(stations)} stages complete"
            + ("  —  PRODUCTION COMPLETE ✔" if done_count == len(stations) else ""),
            fmt["sc_pass"] if done_count == len(stations) else fmt["sc_pend"])
        row += 2

        # ── Battery identity ──────────────────────────────────────────────────
        ws1.set_row(row, 20)
        ws1.merge_range(row, 0, row, 1, "   BATTERY IDENTITY", fmt["sec_hdr"])
        row += 1

        identity = [
            ("Serial No.",     battery_id),
            ("Model",          battery.model_id),
            ("Chemistry",      mdl.cell_type.value if mdl else "—"),
            ("Configuration",
             f"{mdl.series_count}S × {mdl.parallel_count}P = "
             f"{mdl.series_count * mdl.parallel_count} cells" if mdl else "—"),
            ("Welding",        mdl.welding_type.value if mdl else "—"),
            ("Status",         battery.overall_status),
            ("NG History",     "⚠  Repair recorded" if battery.had_ng_status else "✔  Clean"),
            ("Cells Assigned", str(len(cells_raw))),
            ("BMS",            bms.bms_id if bms else "Not mounted"),
            ("Customer",       dispatch.customer_name if dispatch else "—"),
            ("Invoice",        dispatch.invoice_id if dispatch else "—"),
        ]
        for i, (k, v) in enumerate(identity):
            ws1.set_row(row, 17)
            ws1.write(row, 0, f"  {k}", fmt["kv_key"])
            ws1.write(row, 1, str(v), _vfmt(str(v), fmt, i % 2 == 1))
            row += 1

        # ── RIGHT SIDE: Cell quality KPI scorecard ────────────────────────────
        cell_pass  = sum(1 for c, _ in cells_raw
                         if getattr(c, "status", "").upper() == "PASS")
        cell_fail  = sum(1 for c, _ in cells_raw
                         if getattr(c, "status", "").upper() in ("NG", "FAIL"))
        cell_pend  = len(cells_raw) - cell_pass - cell_fail

        kpi_row = HEADER_ROWS
        ws1.set_row(kpi_row, 18)
        ws1.merge_range(kpi_row, 3, kpi_row, 6,
                        "   CELL QUALITY SCORECARD", fmt["sec_hdr"])
        kpi_row += 1

        ws1.set_row(kpi_row, 40)
        ws1.write(kpi_row, 3, len(cells_raw), fmt["kpi_num"])
        ws1.write(kpi_row, 4, cell_pass,      fmt["kpi_pass"])
        ws1.write(kpi_row, 5, cell_fail,      fmt["kpi_fail"] if cell_fail else fmt["kpi_num"])
        ws1.write(kpi_row, 6, cell_pend,      fmt["kpi_warn"] if cell_pend else fmt["kpi_num"])
        kpi_row += 1

        ws1.set_row(kpi_row, 22)
        for col_idx, label in enumerate(["TOTAL CELLS", "PASS", "FAIL / NG", "PENDING"]):
            ws1.write(kpi_row, 3 + col_idx, label, fmt["kpi_label"])
        kpi_row += 2

        # ── Pipeline stacked-bar chart data (hidden cols I:K) ─────────────────
        cd_row = HEADER_ROWS
        ws1.write(cd_row, 8, "Stage",   fmt["th"])
        ws1.write(cd_row, 9, "Done",    fmt["th"])
        ws1.write(cd_row, 10, "Pending", fmt["th"])
        for i, (stage, done) in enumerate(stations):
            ws1.write(cd_row + 1 + i, 8,  stage,            fmt["td"])
            ws1.write(cd_row + 1 + i, 9,  1 if done else 0, fmt["td"])
            ws1.write(cd_row + 1 + i, 10, 0 if done else 1, fmt["td"])

        chart_pipe = wb.add_chart({"type": "bar", "subtype": "stacked"})
        chart_pipe.add_series({
            "name":       "Complete",
            "categories": ["Summary", cd_row+1, 8, cd_row+len(stations), 8],
            "values":     ["Summary", cd_row+1, 9, cd_row+len(stations), 9],
            "fill":       {"color": CH_GREEN}, "border": {"none": True},
        })
        chart_pipe.add_series({
            "name":       "Pending",
            "categories": ["Summary", cd_row+1, 8, cd_row+len(stations), 8],
            "values":     ["Summary", cd_row+1, 10, cd_row+len(stations), 10],
            "fill":       {"color": C_MID_GREY}, "border": {"none": True},
        })
        chart_style(chart_pipe, "Production Pipeline")
        chart_pipe.set_legend({"position": "bottom",
                               "font": {"size": 8, "color": C_SLATE, "name": "Calibri"}})
        chart_pipe.set_x_axis({"min": 0, "max": 1, "num_format": "0",
                               "major_gridlines": {"visible": False}})
        chart_pipe.set_size({"width": 460, "height": 250})
        ws1.insert_chart(kpi_row, 3, chart_pipe, {"x_offset": 4, "y_offset": 4})

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 2 — BATTERY & MODEL
        # ══════════════════════════════════════════════════════════════════════
        ws2 = wb.add_worksheet("Battery & Model")
        ws2.hide_gridlines(2)
        ws2.set_zoom(90)

        row = add_page_header(ws2, wb, fmt, battery_id,
                              "Battery & Model", "Assembly Configuration")
        row = write_kv_section(ws2, fmt, row, "Battery Record",
                               obj_pairs(battery, extra={
                                   "NG / Repair History":
                                       "⚠  Repair recorded" if battery.had_ng_status
                                       else "✔  Clean",
                               }))
        if mdl:
            row = write_kv_section(ws2, fmt, row, "Model Template",
                                   obj_pairs(mdl, extra={
                                       "Total Cells": mdl.series_count * mdl.parallel_count,
                                   }))

        row = write_kv_section(ws2, fmt, row, "Assembly-Time Cell Parameter Ranges", [
            ("IR Lower Limit (mΩ)",       clean(battery.cell_ir_lower)),
            ("IR Upper Limit (mΩ)",        clean(battery.cell_ir_upper)),
            ("Voltage Lower Limit (V)",    clean(battery.cell_voltage_lower)),
            ("Voltage Upper Limit (V)",    clean(battery.cell_voltage_upper)),
            ("Capacity Lower Limit (mAh)", clean(battery.cell_capacity_lower)),
            ("Capacity Upper Limit (mAh)", clean(battery.cell_capacity_upper)),
        ])

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 3 — CELLS
        # ══════════════════════════════════════════════════════════════════════
        ws3 = wb.add_worksheet("Cells")
        ws3.hide_gridlines(2)
        ws3.set_zoom(80)

        hdr_row = add_page_header(ws3, wb, fmt, battery_id, "Cell Traceability",
                                  f"{len(cells_raw)} cells assigned")

        CELL_COLS = [
            ("Cell ID",         "cell",    "cell_id"),
            ("Status",          "cell",    "status"),
            ("NG Count",        "cell",    "ng_count"),
            ("IR (mΩ)",         "cell",    "ir_value_m_ohm"),
            ("Voltage (V)",     "cell",    "sorting_voltage"),
            ("Capacity (mAh)",  "cell",    "discharging_capacity_mah"),
            ("Sorted On",       "cell",    "sorting_date"),
            ("Test Date",       "grading", "test_date"),
            ("Lot",             "grading", "lot"),
            ("Brand",           "grading", "brand"),
            ("OCV (mV)",        "grading", "ocv_voltage_mv"),
            ("Upper Cut. (mV)", "grading", "upper_cutoff_mv"),
            ("Lower Cut. (mV)", "grading", "lower_cutoff_mv"),
            ("Grade Cap (mAh)", "grading", "discharging_capacity_mah"),
            ("Result",          "grading", "result"),
            ("SOC Result",      "grading", "soc_result"),
            ("Final Result",    "grading", "final_result"),
        ]
        COL_W = [22, 10, 8, 10, 11, 14, 14, 14, 10, 14, 11, 12, 12, 14, 10, 10, 12]
        for ci, w in enumerate(COL_W):
            ws3.set_column(ci, ci, w)

        ws3.set_row(hdr_row, 28)
        for ci, (hdr, _, _) in enumerate(CELL_COLS):
            ws3.write(hdr_row, ci, hdr, fmt["th"])
        ws3.freeze_panes(hdr_row + 1, 1)

        for ri, (cell, grading) in enumerate(cells_raw):
            dr = hdr_row + 1 + ri
            ws3.set_row(dr, 16)
            is_alt = ri % 2 == 1
            for ci, (_, src, field) in enumerate(CELL_COLS):
                obj = cell if src == "cell" else grading
                raw = getattr(obj, field, None) if obj else None
                val = str(clean(raw))
                vl  = val.upper()
                if field in ("status", "final_result", "result", "soc_result"):
                    cf = fmt["td_pass"] if "PASS" in vl \
                         else fmt["td_fail"] if ("NG" in vl or "FAIL" in vl) \
                         else fmt["td_warn"]
                elif field == "ng_count" and isinstance(raw, int) and raw > 0:
                    cf = fmt["td_warn"]
                else:
                    cf = fmt["td_alt"] if is_alt else fmt["td"]
                ws3.write(dr, ci, val, cf)

        # ── Chart data zone ────────────────────────────────────────────────────
        n_cells = len(cells_raw)
        last_data_row  = hdr_row + n_cells
        chart_data_row = last_data_row + 4
        chart_row      = chart_data_row + n_cells + 3

        if n_cells > 0:
            ir_lo   = battery.cell_ir_lower
            ir_hi   = battery.cell_ir_upper
            volt_lo = battery.cell_voltage_lower
            volt_hi = battery.cell_voltage_upper
            cap_lo  = battery.cell_capacity_lower
            cap_hi  = battery.cell_capacity_upper

            DC = 18   # hidden data columns start here

            headers = ["Index", "IR (mΩ)", "Volt (V)", "Cap (mAh)",
                       "IR Lo", "IR Hi", "V Lo", "V Hi", "Cap Lo", "Cap Hi"]
            for i, h in enumerate(headers):
                ws3.write(chart_data_row, DC + i, h, fmt["th"])

            for i, (cell, _) in enumerate(cells_raw):
                r = chart_data_row + 1 + i
                ws3.write(r, DC,     i + 1)
                ws3.write(r, DC + 1, cell.ir_value_m_ohm          or 0)
                ws3.write(r, DC + 2, cell.sorting_voltage          or 0)
                ws3.write(r, DC + 3, cell.discharging_capacity_mah or 0)
                ws3.write(r, DC + 4, ir_lo   if ir_lo   else "")
                ws3.write(r, DC + 5, ir_hi   if ir_hi   else "")
                ws3.write(r, DC + 6, volt_lo if volt_lo else "")
                ws3.write(r, DC + 7, volt_hi if volt_hi else "")
                ws3.write(r, DC + 8, cap_lo  if cap_lo  else "")
                ws3.write(r, DC + 9, cap_hi  if cap_hi  else "")

            def scatter_band(title, val_dc, lo_dc, hi_dc, color):
                c = wb.add_chart({"type": "scatter",
                                  "subtype": "straight_with_markers"})
                c.add_series({
                    "name":       title,
                    "categories": ["Cells", chart_data_row+1, DC,
                                   chart_data_row+n_cells,   DC],
                    "values":     ["Cells", chart_data_row+1, val_dc,
                                   chart_data_row+n_cells,   val_dc],
                    "line":   {"color": color, "width": 1.5},
                    "marker": {"type": "circle", "size": 4,
                               "fill": {"color": color},
                               "border": {"color": color}},
                })
                if lo_dc is not None:
                    c.add_series({
                        "name":       "Lower Limit",
                        "categories": ["Cells", chart_data_row+1, DC,
                                       chart_data_row+n_cells,   DC],
                        "values":     ["Cells", chart_data_row+1, lo_dc,
                                       chart_data_row+n_cells,   lo_dc],
                        "line":   {"color": CH_RED, "width": 1,
                                   "dash_type": "dash"},
                        "marker": {"type": "none"},
                    })
                if hi_dc is not None:
                    c.add_series({
                        "name":       "Upper Limit",
                        "categories": ["Cells", chart_data_row+1, DC,
                                       chart_data_row+n_cells,   DC],
                        "values":     ["Cells", chart_data_row+1, hi_dc,
                                       chart_data_row+n_cells,   hi_dc],
                        "line":   {"color": CH_RED, "width": 1,
                                   "dash_type": "dash"},
                        "marker": {"type": "none"},
                    })
                chart_style(c, title)
                c.set_x_axis({"name": "Cell Index",
                              "major_gridlines": {"visible": False}})
                c.set_y_axis({"name": title})
                c.set_legend({"position": "bottom",
                              "font": {"size": 7, "color": C_SLATE,
                                       "name": "Calibri"}})
                c.set_size({"width": 380, "height": 230})
                return c

            ws3.insert_chart(chart_row, 0,
                scatter_band("IR Values (mΩ)",
                    DC+1,
                    DC+4 if ir_lo   else None,
                    DC+5 if ir_hi   else None,
                    CH_BLUE),
                {"x_offset": 4, "y_offset": 4})

            ws3.insert_chart(chart_row, 6,
                scatter_band("Sorting Voltage (V)",
                    DC+2,
                    DC+6 if volt_lo else None,
                    DC+7 if volt_hi else None,
                    CH_GREEN),
                {"x_offset": 4, "y_offset": 4})

            ws3.insert_chart(chart_row, 12,
                scatter_band("Capacity (mAh)",
                    DC+3,
                    DC+8 if cap_lo  else None,
                    DC+9 if cap_hi  else None,
                    CH_ORANGE),
                {"x_offset": 4, "y_offset": 4})

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 4 — PACK TEST
        # ══════════════════════════════════════════════════════════════════════
        ws4 = wb.add_worksheet("Pack Test")
        ws4.hide_gridlines(2)
        ws4.set_zoom(90)
        ws4.set_column("A:A", 34)
        ws4.set_column("B:B", 46)
        ws4.set_column("C:C", 3)
        ws4.set_column("D:G", 16)

        row = add_page_header(ws4, wb, fmt, battery_id,
                              "Pack Testing", "Battery-Level Test Results")

        if pack_test:
            row = write_kv_section(ws4, fmt, row, "Pack Test Report",
                                   obj_pairs(pack_test))

            # Chart 1 data — voltage comparison (cols I:J)
            vdata = [
                ("OCV Voltage (V)",   pack_test.ocv_voltage    or 0),
                ("Upper Cutoff (V)",  pack_test.upper_cutoff   or 0),
                ("Lower Cutoff (V)",  pack_test.lower_cutoff   or 0),
                ("Final Voltage (V)", pack_test.final_voltage  or 0),
            ]
            vdr = HEADER_ROWS
            for i, (lb, vv) in enumerate(vdata):
                ws4.write(vdr + i, 8, lb, fmt["td"])
                ws4.write(vdr + i, 9, vv, fmt["td"])

            chart_v = wb.add_chart({"type": "column"})
            chart_v.add_series({
                "name":       "Voltage (V)",
                "categories": ["Pack Test", vdr, 8, vdr + len(vdata) - 1, 8],
                "values":     ["Pack Test", vdr, 9, vdr + len(vdata) - 1, 9],
                "fill":       {"color": CH_BLUE},
                "border":     {"none": True},
                "data_labels": {"value": True,
                                "font": {"size": 8, "bold": True, "color": C_NAVY}},
            })
            chart_style(chart_v, "Voltage Parameters (V)")
            chart_v.set_y_axis({"name": "Volts (V)"})
            chart_v.set_size({"width": 380, "height": 230})
            ws4.insert_chart(HEADER_ROWS, 3, chart_v, {"x_offset": 4, "y_offset": 4})

            # Chart 2 data — measured voltage vs cutoff limits
            # ── FIX: zip labels and values into (label, value) pairs ──────────
            margin_row    = HEADER_ROWS + 16
            margin_labels = ["OCV", "Final Voltage"]
            margin_vals   = [pack_test.ocv_voltage or 0, pack_test.final_voltage or 0]
            hi_val        = pack_test.upper_cutoff or 0
            lo_val        = pack_test.lower_cutoff or 0

            for i, (lb, vv) in enumerate(zip(margin_labels, margin_vals)):   # ← FIXED
                ws4.write(margin_row + i, 8,  lb,     fmt["td"])
                ws4.write(margin_row + i, 9,  vv,     fmt["td"])
                ws4.write(margin_row + i, 10, hi_val, fmt["td"])
                ws4.write(margin_row + i, 11, lo_val, fmt["td"])

            chart_m = wb.add_chart({"type": "column"})
            chart_m.add_series({
                "name":       "Measured Voltage",
                "categories": ["Pack Test", margin_row, 8, margin_row+1, 8],
                "values":     ["Pack Test", margin_row, 9, margin_row+1, 9],
                "fill":       {"color": CH_BLUE}, "border": {"none": True},
                "data_labels": {"value": True,
                                "font": {"size": 8, "bold": True, "color": C_NAVY}},
            })
            chart_m.add_series({
                "name":       "Upper Cutoff",
                "categories": ["Pack Test", margin_row, 8, margin_row+1, 8],
                "values":     ["Pack Test", margin_row, 10, margin_row+1, 10],
                "fill":       {"color": C_RED_BG},
                "border":     {"color": CH_RED, "width": 1},
            })
            chart_m.add_series({
                "name":       "Lower Cutoff",
                "categories": ["Pack Test", margin_row, 8, margin_row+1, 8],
                "values":     ["Pack Test", margin_row, 11, margin_row+1, 11],
                "fill":       {"color": C_AMBER_BG},
                "border":     {"color": CH_ORANGE, "width": 1},
            })
            chart_style(chart_m, "Measured Voltage vs Cutoff Limits")
            chart_m.set_legend({"position": "bottom",
                                "font": {"size": 8, "color": C_SLATE,
                                         "name": "Calibri"}})
            chart_m.set_y_axis({"name": "Volts (V)"})
            chart_m.set_size({"width": 380, "height": 230})
            ws4.insert_chart(HEADER_ROWS + 16, 3, chart_m,
                             {"x_offset": 4, "y_offset": 4})
        else:
            ws4.merge_range(row, 0, row, 1, "  No pack test data recorded.",
                            fmt["kv_warn"])

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 5 — PDI REPORT
        # ══════════════════════════════════════════════════════════════════════
        ws5 = wb.add_worksheet("PDI Report")
        ws5.hide_gridlines(2)
        ws5.set_zoom(90)
        ws5.set_column("A:A", 34)
        ws5.set_column("B:B", 46)
        ws5.set_column("C:C", 3)
        ws5.set_column("D:G", 16)

        row = add_page_header(ws5, wb, fmt, battery_id,
                              "PDI Inspection", "Pre-Delivery Inspection")

        if pdi:
            row = write_kv_section(ws5, fmt, row, "PDI Test Results",
                                   obj_pairs(pdi))

            edata = [
                ("Cont. Charging Current (A)",   pdi.cont_charging_current    or 0),
                ("Cont. Charging Voltage (V)",    pdi.cont_charging_voltage    or 0),
                ("Cont. Discharging Current (A)", pdi.cont_discharging_current or 0),
                ("Cont. Discharging Voltage (V)", pdi.cont_discharging_voltage or 0),
                ("Voltage (V)",                   pdi.voltage_v                or 0),
                ("Resistance (mΩ)",               pdi.resistance_m_ohm         or 0),
            ]
            edr = HEADER_ROWS
            for i, (lb, vv) in enumerate(edata):
                ws5.write(edr + i, 8, lb, fmt["td"])
                ws5.write(edr + i, 9, vv, fmt["td"])

            chart_e = wb.add_chart({"type": "bar"})
            chart_e.add_series({
                "name":       "Parameter Value",
                "categories": ["PDI Report", edr, 8, edr+len(edata)-1, 8],
                "values":     ["PDI Report", edr, 9, edr+len(edata)-1, 9],
                "fill":       {"color": CH_GREEN}, "border": {"none": True},
                "data_labels": {"value": True,
                                "font": {"size": 8, "bold": True, "color": C_NAVY}},
            })
            chart_style(chart_e, "PDI Electrical Parameters")
            chart_e.set_size({"width": 400, "height": 280})
            ws5.insert_chart(HEADER_ROWS, 3, chart_e,
                             {"x_offset": 4, "y_offset": 4})
        else:
            ws5.merge_range(row, 0, row, 1, "  No PDI data recorded.",
                            fmt["kv_warn"])

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 6 — WELDING
        # ══════════════════════════════════════════════════════════════════════
        ws6 = wb.add_worksheet("Welding")
        ws6.hide_gridlines(2)
        ws6.set_zoom(90)

        weld_lbl = ("Laser Welding"
                    if mdl and mdl.welding_type == WeldingType.LASER
                    else "Spot Welding")
        row = add_page_header(ws6, wb, fmt, battery_id,
                              "Welding Process", weld_lbl)
        if weld:
            row = write_kv_section(ws6, fmt, row,
                                   weld_lbl + " Parameters", obj_pairs(weld))
        else:
            ws6.merge_range(row, 0, row, 1, "  No welding data recorded.",
                            fmt["kv_warn"])

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 7 — BMS
        # ══════════════════════════════════════════════════════════════════════
        ws7 = wb.add_worksheet("BMS")
        ws7.hide_gridlines(2)
        ws7.set_zoom(90)

        row = add_page_header(ws7, wb, fmt, battery_id,
                              "BMS Mounting", "Battery Management System")
        if bms:
            bms_p = obj_pairs(bms)
            if mdl and mdl.bms_model:
                bms_p.insert(1, ("Expected BMS Model", mdl.bms_model))
            row = write_kv_section(ws7, fmt, row, "BMS Unit Record", bms_p)
        else:
            ws7.merge_range(row, 0, row, 1, "  BMS not yet mounted.",
                            fmt["kv_warn"])

        # ══════════════════════════════════════════════════════════════════════
        # SHEET 8 — DISPATCH
        # ══════════════════════════════════════════════════════════════════════
        ws8 = wb.add_worksheet("Dispatch")
        ws8.hide_gridlines(2)
        ws8.set_zoom(90)

        row = add_page_header(ws8, wb, fmt, battery_id,
                              "Dispatch Record", "Customer Delivery")
        if dispatch:
            row = write_kv_section(ws8, fmt, row, "Dispatch Details",
                                   obj_pairs(dispatch))
        else:
            ws8.merge_range(row, 0, row, 1, "  Battery not yet dispatched.",
                            fmt["kv_warn"])

    output.seek(0)
    filename = (f"Maxvolt_Audit_{battery_id}_"
                f"{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
    return StreamingResponse(
        output,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )