from app.models.cell import Cell, CellGrading
from sqlalchemy.orm import Session


def update_cell_grading_logic(db: Session, cell: Cell, row_data: dict):
    """
    Upsert grading data for a cell.

    Master cell record:
    - Once a cell has status "pass" the master record is NEVER overwritten
      (status, capacity, last_test_date all locked).
    - If still "ng" or "pending", every new upload overwrites master +
      increments ng_count on fail.

    Grading detail record (cell_gradings):
    - Always overwritten with latest data regardless of pass/fail.

    Returns:
      "skipped"  — master was already passed; detail record still updated
      "updated"  — master was updated (pass or ng)
    """
    already_passed = (cell.status == "pass")

    # 1. Update master Cell record only if not already passed
    if not already_passed:
        is_pass = str(row_data.get('final Result', '')).strip().upper() == "PASS"

        if is_pass:
            cell.status = "pass"
            cell.discharging_capacity_mah = row_data.get('Discharging Capacity(mAh)')
        else:
            cell.status    = "ng"
            cell.ng_count += 1
            cell.discharging_capacity_mah = row_data.get('Discharging Capacity(mAh)')

        cell.last_test_date = row_data.get('Date')

    # 2. Always upsert the CellGrading detail record (latest data wins)
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
        for key, value in grading_data.items():
            setattr(existing_grading, key, value)
    else:
        db.add(CellGrading(cell_id=cell.cell_id, **grading_data))

    # 3. Return action taken
    # NOTE: "skipped" means master was locked (already passed) but detail
    # was still upserted. The router counts this separately from "updated".
    return "skipped" if already_passed else "updated"


def update_sorting_data(db: Session, cell: Cell, row_data: dict):
    """
    Apply sorting machine data (IR + voltage) to a cell.

    Rules:
    - Cell must have status "pass" — sorting is only done on passed cells.
    - Always overwrites with latest sorting data (re-sorting is allowed).
    - Returns "missing_data" if IR VALUE or VOLTAGE is absent in the row.

    Returns:
      "sorted"           — data written successfully
      "error_not_passed" — cell has not passed grading
      "missing_data"     — IR VALUE or VOLTAGE column missing/empty in this row
    """
    if cell.status != "pass":
        return "error_not_passed"

    # FIX #9 — validate IR and voltage values before writing
    ir   = row_data.get('IR VALUE')
    volt = row_data.get('VOLTAGE')

    if ir is None or volt is None:
        return "missing_data"

    cell.ir_value_m_ohm  = ir
    cell.sorting_voltage = volt

    if row_data.get('Date'):
        cell.sorting_date = row_data.get('Date')

    return "sorted"