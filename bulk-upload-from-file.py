import os
import logging
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# =========================
# LOAD ENVIRONMENT
# =========================

load_dotenv()

PG_HOST = os.getenv("PG_HOST")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DBNAME = os.getenv("PG_DBNAME")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")

FILE_PATH = os.getenv("FILE_PATH")
ASSET_IDS = os.getenv("ASSET_IDS", "")

# ✅ NEW: Allow column override from .env
REASON_COLUMN = os.getenv("REASON_COLUMN", "").strip().lower()

if not all([PG_HOST, PG_DBNAME, PG_USER, PG_PASSWORD]):
    raise ValueError("One or more required PostgreSQL environment variables are missing!")

if not FILE_PATH:
    raise ValueError("FILE_PATH is required in .env")

if not ASSET_IDS:
    raise ValueError("ASSET_IDS is required in .env")

ASSET_IDS = [int(x.strip()) for x in ASSET_IDS.split(",")]

# =========================
# LOGGING CONFIG (NO EMOJIS)
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bulk_upload.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# =========================
# DATABASE CONNECTION
# =========================

DATABASE_URL = (
    f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@"
    f"{PG_HOST}:{PG_PORT}/{PG_DBNAME}"
    "?sslmode=require&connect_timeout=10"
)

logger.info("Attempting to connect to PostgreSQL database...")

try:
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=15,
        pool_timeout=30
    )

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    logger.info("Successfully connected to PostgreSQL database")

except Exception as e:
    logger.exception("FAILED to connect to PostgreSQL database")
    raise e

# =========================
# LOAD EXCEL (AUTO COLUMN DETECT)
# =========================

def load_excel():
    logger.info("Loading Excel file...")

    df = pd.read_excel(FILE_PATH)
    df.columns = df.columns.str.lower().str.strip()

    logger.info(f"Detected columns: {list(df.columns)}")

    # ✅ If column not explicitly provided, auto-pick first column
    if REASON_COLUMN:
        if REASON_COLUMN not in df.columns:
            raise ValueError(
                f"Configured REASON_COLUMN='{REASON_COLUMN}' not found in Excel columns: {list(df.columns)}"
            )
        reason_col = REASON_COLUMN
    else:
        reason_col = df.columns[0]
        logger.info(f"No REASON_COLUMN provided. Using first column: '{reason_col}'")

    df[reason_col] = df[reason_col].astype(str).str.strip()
    df = df[df[reason_col] != ""]

    logger.info(f"Loaded {len(df)} reasons from Excel")

    return df[[reason_col]].rename(columns={reason_col: "name"})

# =========================
# EXPAND REASONS × ASSETS
# =========================

def expand_per_asset(df):
    logger.info("Expanding reasons per asset...")

    expanded_rows = []

    for _, row in df.iterrows():
        for asset_id in ASSET_IDS:
            expanded_rows.append({
                "name": row["name"],
                "asset_id": asset_id,
                "delete_status_id": 0
            })

    expanded_df = pd.DataFrame(expanded_rows)
    expanded_df.drop_duplicates(subset=["name", "asset_id"], inplace=True)

    logger.info(f"Expanded to {len(expanded_df)} total records")
    return expanded_df

# =========================
# UPSERT SQL (using temp table approach)
# =========================

def upsert_data(df):
    logger.info("Uploading data to PostgreSQL...")

    records = df.to_dict(orient="records")

    try:
        with engine.begin() as conn:
            # Create temporary table
            conn.execute(text("""
                CREATE TEMP TABLE temp_downtime_reason (
                    name TEXT,
                    asset_id INTEGER,
                    delete_status_id INTEGER
                ) ON COMMIT DROP
            """))
            
            # Insert all records into temp table
            conn.execute(
                text("""
                    INSERT INTO temp_downtime_reason (name, asset_id, delete_status_id)
                    VALUES (:name, :asset_id, :delete_status_id)
                """),
                records
            )
            
            # Insert new records (that don't exist in main table)
            result_insert = conn.execute(text("""
                INSERT INTO tbl_downtime_reason (name, asset_id, delete_status_id, created_at, updated_at)
                SELECT t.name, t.asset_id, t.delete_status_id, NOW(), NOW()
                FROM temp_downtime_reason t
                WHERE NOT EXISTS (
                    SELECT 1 FROM tbl_downtime_reason m
                    WHERE m.name = t.name AND m.asset_id = t.asset_id
                )
            """))
            inserted = result_insert.rowcount
            
            # Update existing records
            result_update = conn.execute(text("""
                UPDATE tbl_downtime_reason m
                SET delete_status_id = t.delete_status_id, updated_at = NOW()
                FROM temp_downtime_reason t
                WHERE m.name = t.name AND m.asset_id = t.asset_id
            """))
            updated = result_update.rowcount
            
            logger.info(f"Inserted {inserted} new records, updated {updated} existing records")

        logger.info(f"{len(records)} records processed successfully")

    except Exception as e:
        logger.exception("Upload failed during database operation")
        raise e

# =========================
# MAIN
# =========================

def main():
    logger.info("========== BULK UPLOAD STARTED ==========")

    reasons_df = load_excel()
    expanded_df = expand_per_asset(reasons_df)
    upsert_data(expanded_df)

    logger.info("Bulk upload completed successfully")

if __name__ == "__main__":
    main()
