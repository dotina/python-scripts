import os
import io
import logging
import pandas as pd
from flask import Flask, render_template, request, jsonify
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

if not all([PG_HOST, PG_DBNAME, PG_USER, PG_PASSWORD]):
    raise ValueError("One or more required PostgreSQL environment variables are missing!")

# =========================
# LOGGING CONFIG
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bulk_upload_web.log", encoding="utf-8"),
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
# FLASK APP
# =========================

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# =========================
# ROUTES - UI
# =========================

@app.route('/')
def index():
    return render_template('index.html')

# =========================
# ROUTES - API
# =========================

@app.route('/api/companies', methods=['GET'])
def get_companies():
    """Get all active companies"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, name, industry
                FROM companies
                WHERE deleted_at IS NULL AND status = 'ACTIVE'
                ORDER BY name
            """))
            companies = [{"id": row.id, "name": row.name, "industry": row.industry} for row in result]
        return jsonify({"success": True, "data": companies})
    except Exception as e:
        logger.exception("Error fetching companies")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/sections', methods=['GET'])
def get_sections():
    """Get sections for a company"""
    company_id = request.args.get('company_id')
    
    if not company_id:
        return jsonify({"success": False, "error": "company_id is required"}), 400
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, name
                FROM sections
                WHERE company_id = :company_id AND deleted_at IS NULL
                ORDER BY name
            """), {"company_id": int(company_id)})
            sections = [{"id": row.id, "name": row.name} for row in result]
        return jsonify({"success": True, "data": sections})
    except Exception as e:
        logger.exception("Error fetching sections")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/assets', methods=['GET'])
def get_assets():
    """Get assets for a company, optionally filtered by sections"""
    company_id = request.args.get('company_id')
    section_ids = request.args.get('section_ids', '')
    
    if not company_id:
        return jsonify({"success": False, "error": "company_id is required"}), 400
    
    try:
        params = {"company_id": int(company_id)}
        
        if section_ids:
            # Filter by specific sections
            section_id_list = [int(x.strip()) for x in section_ids.split(',') if x.strip()]
            if section_id_list:
                query = """
                    SELECT a.id, a.name, s.name as section_name
                    FROM assets a
                    JOIN sections s ON a.section_id = s.id
                    WHERE a.company_id = :company_id 
                      AND a.deleted_at IS NULL
                      AND a.section_id = ANY(:section_ids)
                    ORDER BY s.name, a.name
                """
                params["section_ids"] = section_id_list
            else:
                query = """
                    SELECT a.id, a.name, s.name as section_name
                    FROM assets a
                    JOIN sections s ON a.section_id = s.id
                    WHERE a.company_id = :company_id AND a.deleted_at IS NULL
                    ORDER BY s.name, a.name
                """
        else:
            # All assets for company
            query = """
                SELECT a.id, a.name, s.name as section_name
                FROM assets a
                JOIN sections s ON a.section_id = s.id
                WHERE a.company_id = :company_id AND a.deleted_at IS NULL
                ORDER BY s.name, a.name
            """
        
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            assets = [{"id": row.id, "name": row.name, "section_name": row.section_name} for row in result]
        
        return jsonify({"success": True, "data": assets})
    except Exception as e:
        logger.exception("Error fetching assets")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/upload/parse', methods=['POST'])
def parse_file():
    """Parse uploaded Excel/CSV file and return columns + preview"""
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"success": False, "error": "No file selected"}), 400
    
    filename = file.filename.lower()
    
    try:
        # Read file into DataFrame
        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            df = pd.read_excel(io.BytesIO(file.read()))
        elif filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file.read()))
        else:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload .xlsx, .xls, or .csv"}), 400
        
        if df.empty:
            return jsonify({"success": False, "error": "Uploaded file contains no data"}), 400
        
        # Clean column names
        df.columns = df.columns.astype(str).str.strip()
        
        # Get columns and preview rows
        columns = list(df.columns)
        preview_rows = df.head(5).fillna('').astype(str).values.tolist()
        
        # Also get all values for each column (for reason extraction)
        column_data = {}
        for col in columns:
            values = df[col].dropna().astype(str).str.strip()
            values = values[values != ''].unique().tolist()
            column_data[col] = values
        
        return jsonify({
            "success": True,
            "data": {
                "columns": columns,
                "preview_rows": preview_rows,
                "column_data": column_data,
                "total_rows": len(df)
            }
        })
    except Exception as e:
        logger.exception("Error parsing file")
        return jsonify({"success": False, "error": f"Error parsing file: {str(e)}"}), 400


@app.route('/api/upload/process', methods=['POST'])
def process_upload():
    """Bulk upsert downtime reasons for selected assets"""
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400
    
    reason_names = data.get('reason_names', [])
    asset_ids = data.get('asset_ids', [])
    
    # Validation
    if not reason_names:
        return jsonify({"success": False, "error": "No reason names provided"}), 400
    
    if not asset_ids:
        return jsonify({"success": False, "error": "No assets selected"}), 400
    
    # Clean and deduplicate reason names
    reason_names = list(set([str(r).strip() for r in reason_names if str(r).strip()]))
    asset_ids = [int(a) for a in asset_ids]
    
    if not reason_names:
        return jsonify({"success": False, "error": "No valid reason names found after cleaning"}), 400
    
    logger.info(f"Processing {len(reason_names)} reasons for {len(asset_ids)} assets")
    
    # Expand reasons × assets
    records = []
    for reason in reason_names:
        for asset_id in asset_ids:
            records.append({
                "name": reason,
                "asset_id": asset_id,
                "delete_status_id": 0
            })
    
    try:
        with engine.begin() as conn:
            # Create temporary table
            conn.execute(text("""
                CREATE TEMP TABLE temp_downtime_reason (
                    name TEXT,
                    asset_id BIGINT,
                    delete_status_id BIGINT
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
        
        return jsonify({
            "success": True,
            "data": {
                "inserted": inserted,
                "updated": updated,
                "total_processed": len(records)
            }
        })
    
    except Exception as e:
        logger.exception("Error processing upload")
        return jsonify({"success": False, "error": f"Database error: {str(e)}"}), 500


# =========================
# MAIN
# =========================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
