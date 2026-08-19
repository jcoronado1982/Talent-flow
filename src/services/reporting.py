import pandas as pd
import os
import time
from datetime import datetime
import src.services.storage.database as db
from src.config.settings import Settings

def generate_excel_report():
    """Generates an Excel report from the database for recent/pending jobs."""
    try:
        conn = db.get_connection()
        # Filter: Include all Matched jobs (score >= 30 as defined in processor)
        query = "SELECT * FROM jobs WHERE status = 'Matched' ORDER BY match_score DESC, created_at DESC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            print("   [Report] No data to report.")
            return None

        # Format Columns for Report
        # Map DB columns to expected Excel columns
        report_df = pd.DataFrame()
        report_df["DB ID"] = df["id"]
        report_df["Company"] = df["company"]
        report_df["Role"] = df["role"]
        report_df["Location"] = df["location"]
        report_df["Link"] = df["url"]
        report_df["Source"] = df["source"]
        report_df["Requirements"] = df["raw_analysis"].apply(lambda x: _extract_analysis_text(x)) # Simple extraction
        
        # Match Score
        report_df["Match %"] = df["match_score"].apply(lambda x: f"{x}%")
        
        # Application Status
        report_df["Application Status"] = df["status"]
        report_df["Applied Salary"] = df["applied_salary"]
        report_df["Currency"] = df["applied_currency"]
        report_df["Priority"] = df["priority_score"]
        report_df["Scan Time"] = df["created_at"]
        report_df["Date"] = df["date_posted"]
        report_df["Work Mode"] = df["work_mode"]
        report_df["Language"] = df["language"]

        # Timestamp for filename
        timestamp = datetime.now().strftime("%d_%m_%Y_%H_%M")
        filename = f"report_FINAL_{timestamp}.xlsx"
        output_dir = "reports"
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)

        # Style and Save (using pandas default for now, can be enhanced with openpyxl if needed)
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            report_df.to_excel(writer, index=False, sheet_name="Jobs")
        
        print(f"   [Report] 📊 Excel report generated: {path}")
        return path

    except Exception as e:
        print(f"   [Report] ❌ Error generating report: {e}")
        return None

def _extract_analysis_text(json_str):
    try:
        import json
        data = json.loads(json_str)
        return data.get("analysis", "") or data.get("summary", "")
    except:
        return ""
