from app.models.cell import Cell, CellGrading
from sqlalchemy.orm import Session

# ─────────────────────────────────────────────────────────────────────────────
# NOTE: These functions are NO LONGER called by the upload endpoints.
# The upload endpoints (cell_router.py) now do bulk in-memory processing
# directly for performance at 40,000+ rows/day.
#
# These functions are kept here for:
#   - replace-cell endpoint (single-record operations)
#   - any future single-record grading/sorting needs
#   - unit testing individual cell logic
# ─────────────────────────────────────────────────────────────────────────────


def update_cell_grading_logic(db: Session, cell: Cell, row_data: dict) -> str:
    """
    Upsert grading data for a single cell.

    Used by: replace-cell, unit tests.
    NOT used by: /upload-grading (handled in bulk directly in cell_router.py)

    Returns:
      "skipped"  — master already passed; detail record still updated
      "updated"  — master updated (pass or ng)
    """
    already_passed = (cell.status == "pass")

    if not already_passed:
        is_pass = str(row_data.get('final Result', '')).strip().upper() == "PASS"

        if is_pass:
            cell.status                   = "pass"
            cell.discharging_capacity_mah = row_data.get('Discharging Capacity(mAh)')
        else:
            cell.status                   = "ng"
            cell.ng_count                 = (cell.ng_count or 0) + 1
            cell.discharging_capacity_mah = row_data.get('Discharging Capacity(mAh)')

        cell.last_test_date = row_data.get('Date')

    # Always upsert the CellGrading detail record
    existing_grading = db.query(CellGrading).filter(
        CellGrading.cell_id == cell.cell_id
    ).first()

    grading_data = {
        "test_date":                row_data.get('Date'),
        "lot":                      row_data.get('Lot'),
        "brand":                    row_data.get('Brand'),
        "specification":            row_data.get('Specification'),
        "ocv_voltage_mv":           row_data.get('OCV Voltage(mV)'),
        "upper_cutoff_mv":          row_data.get('Upper cut off(mV)'),
        "lower_cutoff_mv":          row_data.get('Lower cut off(mV)'),
        "discharging_capacity_mah": row_data.get('Discharging Capacity(mAh)'),
        "result":                   row_data.get('Result'),
        "final_soc_mah":            row_data.get('Final SOC(mAh)'),
        "soc_result":               row_data.get('SOC Result'),
        "final_cv_capacity":        row_data.get('Final CV Capacity'),
        "final_result":             row_data.get('final Result'),
    }

    if existing_grading:
        for k, v in grading_data.items():
            setattr(existing_grading, k, v)
    else:
        db.add(CellGrading(cell_id=cell.cell_id, **grading_data))

    return "skipped" if already_passed else "updated"


def update_sorting_data(db: Session, cell: Cell, row_data: dict) -> str:
    """
    Apply sorting machine data (IR + voltage) to a single cell.

    Used by: replace-cell, unit tests.
    NOT used by: /upload-sorting (handled in bulk directly in cell_router.py)

    Returns:
      "sorted"           — data written successfully
      "error_not_passed" — cell has not passed grading
      "missing_data"     — IR VALUE or VOLTAGE missing/empty in row
    """
    if cell.status != "pass":
        return "error_not_passed"

    ir   = row_data.get('IR VALUE')
    volt = row_data.get('VOLTAGE')

    if ir is None or volt is None:
        return "missing_data"

    cell.ir_value_m_ohm  = float(ir)
    cell.sorting_voltage = float(volt)

    date = row_data.get('Date')
    if date:
        cell.sorting_date = date

    return "sorted"