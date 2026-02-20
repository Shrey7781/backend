from sqlalchemy import text
from app.database import SessionLocal

def clear_all_data():
    db = SessionLocal()
    try:
        print("🗑️  Preparing to wipe all production data...")
        
        # List your tables in order or use CASCADE
        # CASCADE ensures that if you wipe 'batteries', 
        # it automatically wipes linked 'pdi_reports', etc.
        tables = [
            "battery_cell_mapping",
            "pdi_reports",
            "pack_testing_reports",
            "laser_welding_data",
            "spot_welding_data",
            "dispatch_records",
            "bms_inventory",
            "cell_gradings",
            "batteries",
            "cells",
            "battery_models"
        ]

        for table in tables:
            # TRUNCATE is faster than DELETE
            # RESTART IDENTITY resets the ID counters to 1
            db.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;"))
            print(f"✅ Cleared table: {table}")

        db.commit()
        print("\n✨ Database is now empty and IDs are reset.")

    except Exception as e:
        db.rollback()
        print(f"❌ Error during reset: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    confirm = input("Are you sure you want to delete ALL data? (y/n): ")
    if confirm.lower() == 'y':
        clear_all_data()
    else:
        print("Reset cancelled.")