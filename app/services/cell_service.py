from app.models.cell import CellGrading
from app.models.cell import Cell
from sqlalchemy.orm import Session

def update_cell_grading_logic(db: Session, cell: Cell, row_data: dict):
    # 1. Determine if we should skip the Master update
    already_passed = (cell.status == "pass")
    
    # 2. Update Master Cell ONLY if not already passed
    if not already_passed:
        is_pass = str(row_data.get('final Result')).strip().upper() == "PASS"
        if is_pass:
            cell.status = "pass"
            cell.ocv_voltage_mv = row_data.get('OCV Voltage(mV)')
            cell.discharging_capacity_mah = row_data.get('Discharging Capacity(mAh)')
        else:
            cell.status = "ng"
            cell.ng_count += 1
            cell.ocv_voltage_mv = row_data.get('OCV Voltage(mV)')
            cell.discharging_capacity_mah = row_data.get('Discharging Capacity(mAh)')
        
        cell.last_test_date = row_data.get('Date')

    # 3. UPSERT the Grading Record (Keep 1-to-1 relationship)
    existing_grading = db.query(CellGrading).filter(CellGrading.cell_id == cell.cell_id).first()
    
    grading_data = {
        "test_date": row_data.get('Date'),
        "lot": row_data.get('Lot'),
        "brand": row_data.get('Brand'),
        "specification": row_data.get('Specification'),
        "ocv_voltage_mv": row_data.get('OCV Voltage(mV)'),
        "upper_cutoff_mv": row_data.get('Upper cut off(mV)'),
        "lower_cutoff_mv": row_data.get('Lower cut off(mV)'),
        "discharging_capacity_mah": row_data.get('Discharging Capacity(mAh)'),
        "result": row_data.get('Result'),
        "final_soc_mah": row_data.get('Final SOC(mAh)'),
        "soc_result": row_data.get('SOC Result'),
        "final_cv_capacity": row_data.get('Final CV Capacity'),
        "final_result": row_data.get('final Result')
    }

    if existing_grading:
        for key, value in grading_data.items():
            setattr(existing_grading, key, value)
    else:
        new_grading = CellGrading(cell_id=cell.cell_id, **grading_data)
        db.add(new_grading)

    # 4. Return "skipped" if Master wasn't touched, else "updated"
    return "skipped" if already_passed else "updated"

@staticmethod
def update_sorting_data(db: Session, cell: Cell, row_data: dict):
   
    if cell.status != "pass":
        return "error_not_passed"

    cell.ir_value_m_ohm = row_data.get('IR VALUE')
    cell.sorting_voltage = row_data.get('VOLTAGE')
    

    if row_data.get('Date'):
        cell.sorting_date = row_data.get('Date')

    return "sorted"