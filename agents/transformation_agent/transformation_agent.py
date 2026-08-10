import os
import json
import logging
import time
import pandas as pd
import numpy as np
from backend.utils.file_utils import read_dataset, clear_cleaned_data_folder, detect_file_info
from backend.core.llm import query_llm

logger = logging.getLogger("etl_transformation_agent")

class TransformationAgent:
    def __init__(self):
        self.role = "Senior ETL Engineer"
        self.name = "Transformation Agent"

    def run(self, file_path: str, metadata: dict = None, output_dir: str = "cleaned data", clear_output_dir: bool = False) -> dict:
        if metadata is None:
            metadata = {}
        start_time = time.time()
        logger.info(f"Running Data Transformation Agent on {file_path}")
        
        should_clear = clear_output_dir or metadata.get("clear_output_dir", False)
        if metadata.get("preserve_cleaned_dir", False):
            should_clear = False

        if should_clear:
            logger.info(f"Clearing output folder '{output_dir}' prior to storing cleaned data.")
            clear_cleaned_data_folder(output_dir)
            
        # Optimize reading for large files (> 10 MB)
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        file_info = detect_file_info(file_path)
        
        if file_size > 10 * 1024 * 1024 and file_path.lower().endswith(('.csv', '.tsv')):
            logger.info("Large dataset detected (>10MB). Stream profiling row count.")
            row_count = 0
            try:
                with open(file_path, 'r', encoding=file_info.get("encoding", "utf-8"), errors='ignore') as f:
                    for _ in f:
                        row_count += 1
                row_count = max(0, row_count - 1)
            except Exception:
                row_count = 100000  # fallback estimation
            
            df = read_dataset(file_path, nrows=5000)
            original_shape = (row_count, df.shape[1])
        else:
            df = read_dataset(file_path)
            original_shape = df.shape
            
        history = []
        logs = []
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Clean column names (standardize to snake_case)
        old_cols = list(df.columns)
        new_cols = []
        for col in old_cols:
            clean_col = str(col).strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")
            new_cols.append(clean_col)
        df.columns = new_cols
        
        for old_c, new_c in zip(old_cols, new_cols):
            if old_c != new_c:
                history.append({
                    "column_name": old_c,
                    "old_value": old_c,
                    "new_value": new_c,
                    "reason": "Standardized column header naming format"
                })
        logs.append("Standardized all column headers to snake_case.")

        # 2. Trim whitespaces in string columns
        for col in df.columns:
            if df[col].dtype == object:
                # check if there are string values
                try:
                    trimmed = df[col].astype(str).str.strip()
                    # Replace "nan" or "None" back with actual None/null if they were converted
                    trimmed = trimmed.replace({"nan": None, "None": None, "": None})
                    df[col] = trimmed
                except Exception:
                    pass

        # 3. Deduplicate
        if file_size > 10 * 1024 * 1024 and file_path.lower().endswith(('.csv', '.tsv')):
            dups_count = 0
        else:
            dups_count = int(df.duplicated().sum())
            if dups_count > 0:
                df = df.drop_duplicates().reset_index(drop=True)
                history.append({
                    "column_name": "all",
                    "old_value": f"{original_shape[0]} rows",
                    "new_value": f"{original_shape[0] - dups_count} rows",
                    "reason": f"Removed {dups_count} duplicate records"
                })
                logs.append(f"Removed {dups_count} duplicate rows from the dataset.")

        # 4. Standardize date formats
        for col in df.columns:
            if "date" in col or "time" in col:
                # Try parsing as datetime
                try:
                    # Capture original state to log
                    sample_vals = df[col].dropna().head(3).tolist()
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                    # format as ISO string YYYY-MM-DD HH:MM:SS or YYYY-MM-DD
                    df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                    history.append({
                        "column_name": col,
                        "old_value": str(sample_vals),
                        "new_value": "ISO datetime YYYY-MM-DD HH:MM:SS",
                        "reason": f"Standardized date values"
                    })
                    logs.append(f"Standardized date/time values in column '{col}' to ISO format.")
                except Exception as ex:
                    logger.warning(f"Could not standardize dates in '{col}': {ex}")

        # 5. Fill missing values (business-specific logic)
        for col in df.columns:
            null_count = int(df[col].isnull().sum())
            if null_count > 0:
                if col == "quantity":
                    df["quantity"] = df["quantity"].fillna(1)
                    # Convert to numeric
                    df["quantity"] = pd.to_numeric(df["quantity"], errors='coerce').fillna(1).astype(int)
                    history.append({
                        "column_name": col,
                        "old_value": "Nulls present",
                        "new_value": "1",
                        "reason": f"Imputed {null_count} missing quantities to default value of 1"
                    })
                elif col == "unit_price":
                    df["unit_price"] = pd.to_numeric(df["unit_price"], errors='coerce')
                    median_val = float(df["unit_price"].median()) if not df["unit_price"].isnull().all() else 10.0
                    df["unit_price"] = df["unit_price"].fillna(median_val)
                    history.append({
                        "column_name": col,
                        "old_value": "Nulls present",
                        "new_value": str(median_val),
                        "reason": f"Imputed {null_count} missing unit prices to median of {median_val}"
                    })
                elif col == "total_price":
                    # Recalculate if unit_price and quantity exist
                    df["unit_price"] = pd.to_numeric(df["unit_price"], errors='coerce').fillna(10.0)
                    df["quantity"] = pd.to_numeric(df["quantity"], errors='coerce').fillna(1).astype(int)
                    calculated_total = df["quantity"] * df["unit_price"]
                    df["total_price"] = df["total_price"].fillna(calculated_total)
                    df["total_price"] = pd.to_numeric(df["total_price"], errors='coerce').fillna(10.0)
                    history.append({
                        "column_name": col,
                        "old_value": "Nulls present",
                        "new_value": "quantity * unit_price",
                        "reason": f"Recalculated {null_count} missing total prices using product of quantity and unit price"
                    })
                elif col == "customer_name" or col == "customer_id" or col == "order_id":
                    # For PK/FK fields, we can't easily guess, we tag as Unknown or leave null for validation rejects
                    pass
                else:
                    # Generic fill
                    if df[col].dtype in [np.float64, np.int64]:
                        fill_val = 0
                        df[col] = df[col].fillna(fill_val)
                    else:
                        fill_val = "Unknown"
                        df[col] = df[col].fillna(fill_val)
                    history.append({
                        "column_name": col,
                        "old_value": "Nulls present",
                        "new_value": str(fill_val),
                        "reason": f"Filled {null_count} null elements with default '{fill_val}'"
                    })
                logs.append(f"Handled {null_count} missing values in column '{col}'.")

        # 6. Save clean dataset
        base_name = os.path.basename(file_path)
        if not os.path.isabs(output_dir):
            PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            output_dir = os.path.join(PROJECT_ROOT, output_dir)
        os.makedirs(output_dir, exist_ok=True)
        clean_file_path = os.path.join(output_dir, base_name)
        
        _, ext = os.path.splitext(clean_file_path.lower())
        
        if file_size > 10 * 1024 * 1024 and ext in [".csv", ".tsv"]:
            logger.info("Large dataset detected (>10MB). Processing in chunks for memory efficiency.")
            delimiter = file_info.get("delimiter", ",")
            chunk_size = 50000
            first_chunk = True
            
            with open(clean_file_path, 'w', encoding='utf-8', newline='') as out_f:
                for chunk in pd.read_csv(file_path, encoding=file_info.get("encoding", "utf-8"), sep=delimiter, chunksize=chunk_size, on_bad_lines='skip'):
                    # 1. Clean columns
                    chunk.columns = new_cols
                    # 2. Trim whitespaces
                    for col in chunk.columns:
                        if chunk[col].dtype == object:
                            try:
                                chunk[col] = chunk[col].astype(str).str.strip().replace({"nan": None, "None": None, "": None})
                            except Exception:
                                pass
                    # 3. Standardize dates
                    for col in chunk.columns:
                        if "date" in col or "time" in col:
                            try:
                                chunk[col] = pd.to_datetime(chunk[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
                            except Exception:
                                pass
                    # 4. Fill missing values
                    for col in chunk.columns:
                        null_count = int(chunk[col].isnull().sum())
                        if null_count > 0:
                            if col == "quantity":
                                chunk[col] = pd.to_numeric(chunk[col], errors='coerce').fillna(1).astype(int)
                            elif col == "unit_price":
                                chunk[col] = pd.to_numeric(chunk[col], errors='coerce').fillna(10.0)
                            elif col == "total_price":
                                chunk["unit_price"] = pd.to_numeric(chunk["unit_price"], errors='coerce').fillna(10.0)
                                chunk["quantity"] = pd.to_numeric(chunk["quantity"], errors='coerce').fillna(1).astype(int)
                                calculated_total = chunk["quantity"] * chunk["unit_price"]
                                chunk[col] = chunk[col].fillna(calculated_total)
                            else:
                                if chunk[col].dtype in [np.float64, np.int64]:
                                    chunk[col] = chunk[col].fillna(0)
                                else:
                                    chunk[col] = chunk[col].fillna("Unknown")
                                    
                    chunk.to_csv(out_f, sep=delimiter, index=False, header=first_chunk)
                    first_chunk = False
        else:
            # Save based on type
            if ext == ".json":
                df.to_json(clean_file_path, orient='records', indent=2)
            elif ext in [".xlsx", ".xls"]:
                df.to_excel(clean_file_path, index=False)
            elif ext == ".tsv":
                df.to_csv(clean_file_path, sep="\t", index=False)
            elif ext == ".xml":
                df.to_xml(clean_file_path, index=False, parser="etree")
            elif ext == ".ipynb":
                df.to_json(clean_file_path, orient='records', indent=2)
            else:
                df.to_csv(clean_file_path, index=False)

        # Recalculate post-cleaning quality score
        new_row_count, new_col_count = df.shape
        new_missing = int(df.isnull().sum().sum())
        new_dups = int(df.duplicated().sum())
        total_elems = new_row_count * new_col_count
        quality_after = 100.0
        if total_elems > 0:
            quality_after = round(((total_elems - new_missing - new_dups) / total_elems) * 100, 2)

        # Call LLM to summarize/record rationale
        prompt = f"""
        You are a Senior ETL Engineer. You have just cleaned a dataset.
        Original dimensions: {original_shape}
        Cleaned dimensions: {df.shape}
        Calculated Quality Before: {metadata.get("estimated_quality", 80.0)}
        Calculated Quality After: {quality_after}
        Transformation steps applied:
        {json.dumps(history, indent=2)}
        
        Provide a concise transformation summary in JSON format:
        1. quality_before (float, use the Calculated Quality Before value)
        2. quality_after (float, use the Calculated Quality After value)
        3. summary (string explaining rationale and overall cleaning execution)
        
        Return ONLY valid JSON.
        """
        
        system_instruction = "You are the Data Transformation Agent. Provide summary and metrics on cleaning operations as structured JSON."
        
        try:
            llm_response = query_llm(prompt, system_instruction, json_mode=True)
            if "```json" in llm_response:
                llm_response = llm_response.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_response:
                llm_response = llm_response.split("```")[1].split("```")[0].strip()
            summary_info = json.loads(llm_response.strip())
        except Exception:
            summary_info = {
                "quality_before": metadata.get("estimated_quality", 80.0),
                "quality_after": quality_after,
                "summary": f"Cleaned and standardized columns. Dropped duplicates and computed missing elements."
            }

        execution_time = time.time() - start_time
        logger.info(f"Transformation complete. Clean file stored at {clean_file_path}")
        
        return {
            "transformation_steps": history,
            "updated_schema": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "clean_dataset_path": clean_file_path,
            "quality_before": summary_info.get("quality_before"),
            "quality_after": summary_info.get("quality_after"),
            "summary": summary_info.get("summary"),
            "logs": logs,
            "execution_time": execution_time
        }
