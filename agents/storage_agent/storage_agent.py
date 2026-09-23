import os
import json
import re
import logging
import time
import datetime
import pandas as pd
from sqlalchemy import text
from docx import Document
from backend.database.mysql import SessionLocal
from backend.database.repository import log_agent_decision
from backend.core.llm import query_llm
from backend.utils.file_utils import read_dataset

logger = logging.getLogger("etl_storage_agent")

# Relational target tables: loadable columns and primary keys
TABLE_COLUMNS = {
    "customers": ["customer_id", "customer_name", "email", "phone", "region"],
    "orders": ["order_id", "customer_id", "order_date", "status", "total_amount"],
    "sales": ["sale_id", "order_id", "product_id", "quantity", "unit_price", "total_price", "sale_date"],
}
PRIMARY_KEYS = {"customers": "customer_id", "orders": "order_id", "sales": "sale_id"}


def detect_dataset_type(cols: list) -> str:
    """
    Maps a cleaned dataset onto a relational table by its key columns. A file that has its own
    identifier (e.g. transaction_id) and merely references customer_id is not a customer master
    list, so it is stored as a generic dataset rather than overwriting customers.
    """
    col_set = set(cols)
    if "sale_id" in col_set:
        return "sales"
    if "order_id" in col_set:
        return "orders"
    if "customer_id" in col_set:
        other_ids = [c for c in col_set if c.endswith("_id") and c != "customer_id"]
        return "dataset" if other_ids else "customers"
    return "dataset"


def _is_missing(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _clean_key(v) -> str:
    if _is_missing(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _to_text(v):
    if _is_missing(v):
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime.datetime) else v.isoformat()
    return v if isinstance(v, str) else str(v)


def _to_float(v, col: str):
    if _is_missing(v) or (isinstance(v, str) and not v.strip()):
        return None, None
    try:
        return float(str(v).replace(",", "").strip()), None
    except (TypeError, ValueError):
        return None, f"Invalid numeric value in '{col}': {v!r}"


def _to_int(v, col: str):
    number, err = _to_float(v, col)
    if err or number is None:
        return None, err
    if not number.is_integer():
        return None, f"Non-integer value in '{col}': {v!r}"
    return int(number), None


def _to_datetime(v, col: str):
    if _is_missing(v) or (isinstance(v, str) and not v.strip()):
        return None, None
    parsed = pd.to_datetime(v, errors="coerce")
    if pd.isna(parsed):
        return None, f"Unparseable date in '{col}': {v!r}"
    return parsed.to_pydatetime(), None


def _upsert_sql(is_sqlite: bool, table: str, cols: list, pk: str) -> str:
    col_list = ", ".join(cols)
    values = ", ".join(f":{c}" for c in cols)
    updates = [c for c in cols if c != pk]
    if is_sqlite:
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in updates)
        return f"INSERT INTO {table} ({col_list}) VALUES ({values}) ON CONFLICT({pk}) DO UPDATE SET {set_clause}"
    set_clause = ", ".join(f"{c}=VALUES({c})" for c in updates)
    return f"INSERT INTO {table} ({col_list}) VALUES ({values}) ON DUPLICATE KEY UPDATE {set_clause}"


def _upsert_ignore_sql(is_sqlite: bool, table: str, cols_and_values: str, pk: str) -> str:
    if is_sqlite:
        return f"INSERT OR IGNORE INTO {table} {cols_and_values}"
    return f"INSERT INTO {table} {cols_and_values} ON DUPLICATE KEY UPDATE {pk}={pk}"


def _xml_safe(value) -> str:
    """python-docx rejects control characters; strip them so odd source data cannot break the export."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value))


class StorageAgent:
    def __init__(self):
        self.role = "Senior Database & Storage Architect"
        self.name = "Intelligent Storage Agent"

    def run(self, clean_file_path: str, batch_id: str, metadata: dict = None) -> dict:
        start_time = time.time()
        logger.info(f"Running Intelligent Storage Agent on {clean_file_path} for batch {batch_id}")
        
        # 1. Read clean dataset
        df = read_dataset(clean_file_path)
        cols = list(df.columns)
        
        # 2. Analyze characteristics and select format
        # Heuristics:
        # - Relational entity datasets (e.g. containing customer_id or order_id) -> SQL
        # - Tabular datasets containing numerical/metric properties (e.g., quantities, prices, amounts) -> CSV
        # - Textual or unstructured datasets -> Word
        
        preview_data = df.head(3).to_dict(orient='records')
        col_types = {col: str(df[col].dtype) for col in cols}
        
        prompt = f"""
        You are a Senior Storage Architect. Analyze the characteristics of this clean dataset:
        Columns: {cols}
        Column Data Types: {col_types}
        Preview: {json.dumps(preview_data, default=str)}
        
        Select the optimal storage format among:
        - "CSV": Best for mostly numerical, statistical, or ledger tabular information.
        - "Word": Best for primarily textual, descriptive, or document-oriented datasets.
        - "SQL": Best for highly structured, relational databases requiring query scalability (e.g. master customer data, order lists).
        
        Return a JSON response with:
        1. format_selected: 'CSV', 'Word', or 'SQL'
        2. reason: clear technical justification for selecting this format.
        3. summary: a brief summary of the dataset.
        
        Return ONLY valid JSON.
        """
        
        system_instruction = "You are the Intelligent Storage Agent. Analyze dataset properties and determine optimal storage format as valid JSON."
        
        # Default fallback decisions
        if "customer_id" in cols or "order_id" in cols or "sale_id" in cols:
            # Let's check if it has lots of numerical values
            if "total_price" in cols or "quantity" in cols:
                default_format = "CSV"
                default_reason = "Dataset contains numerical transaction ledger information (quantity, unit_price, total_price) suited for flat CSV reports."
            else:
                default_format = "SQL"
                default_reason = "Dataset contains highly structured relational database keys (customer_id, order_id) mapping to specific entities."
        elif "text" in str(cols).lower() or "description" in str(cols).lower():
            default_format = "Word"
            default_reason = "Dataset is primarily textual or document-oriented."
        else:
            default_format = "CSV"
            default_reason = "Tabular data containing statistics and tabular attributes suited for spreadsheet-based CSV exports."
            
        try:
            llm_response = query_llm(prompt, system_instruction, json_mode=True)
            if "```json" in llm_response:
                llm_response = llm_response.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_response:
                llm_response = llm_response.split("```")[1].split("```")[0].strip()
            decision = json.loads(llm_response.strip())
            format_selected = decision.get("format_selected", default_format).upper()
            storage_reason = decision.get("reason", default_reason)
        except Exception as e:
            logger.error(f"Error calling LLM in StorageAgent: {e}")
            format_selected = default_format.upper()
            storage_reason = default_reason

        # Standardize format naming
        if format_selected not in ["CSV", "WORD", "SQL"]:
            format_selected = default_format.upper()

        logger.info(f"Selected format: {format_selected}. Reason: {storage_reason}")
        
        # 3. Detect the target relational table from the dataset's key columns
        dataset_type = detect_dataset_type(cols)

        db = SessionLocal()
        user_email = None
        try:
            user_email = db.execute(
                text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": batch_id}
            ).scalar()
        except Exception as e:
            logger.warning(f"Failed to query uploaded_by in StorageAgent: {e}")

        formatted_file_path = self._save_formatted_file_to_clean_folder(clean_file_path, format_selected, dataset_type, df, batch_id, user_email=user_email)
        logger.info(f"Storage agent saved formatted dataset ({format_selected}) to clean folder: {formatted_file_path}")

        sql_logs = []
        rejected_records = []
        rows_loaded = 0
        rows_rejected = 0

        # Pull existing FKs
        existing_customers = set()
        existing_orders = set()
        try:
            if dataset_type == "orders":
                res = db.execute(text("SELECT customer_id FROM customers")).fetchall()
                existing_customers = {row[0] for row in res}
            elif dataset_type == "sales":
                res = db.execute(text("SELECT order_id FROM orders")).fetchall()
                existing_orders = {row[0] for row in res}
        except Exception as e:
            logger.warning(f"Failed to fetch relational primary keys, using blank: {e}")

        staging_records = []
        production_records = []
        seen_pks = set()

        # Auto-provision missing parent entity keys if needed so foreign key constraints pass seamlessly
        missing_customers_to_stub = set()
        missing_orders_to_stub = set()

        table_columns = TABLE_COLUMNS.get(dataset_type, [])
        pk_col = PRIMARY_KEYS.get(dataset_type)

        for idx, raw_record in enumerate(df.to_dict(orient='records')):
            row_num = idx + 1
            row_dict = {str(k): (None if _is_missing(v) else v) for k, v in raw_record.items()}
            # Columns the target table expects but the file lacks are loaded as NULL
            for col in table_columns:
                row_dict.setdefault(col, None)

            reject_reasons = []
            prod_row = None

            if pk_col:
                pk_val = _clean_key(row_dict.get(pk_col))
                if not pk_val:
                    reject_reasons.append(f"Missing primary key '{pk_col}'")
                elif pk_val in seen_pks:
                    reject_reasons.append(f"Duplicate primary key '{pk_col}'={pk_val} within the batch")
                else:
                    seen_pks.add(pk_val)
                row_dict[pk_col] = pk_val

            if dataset_type == "customers":
                if not _clean_key(row_dict.get("customer_name")):
                    reject_reasons.append("Missing required field 'customer_name'")
                prod_row = {c: _to_text(row_dict.get(c)) for c in table_columns}

            elif dataset_type == "orders":
                fk_val = _clean_key(row_dict.get("customer_id")) or "CUST_DEFAULT"
                row_dict["customer_id"] = fk_val
                total_amount, err_amt = _to_float(row_dict.get("total_amount"), "total_amount")
                order_date, err_date = _to_datetime(row_dict.get("order_date"), "order_date")
                reject_reasons += [e for e in (err_amt, err_date) if e]
                prod_row = {
                    "order_id": row_dict["order_id"],
                    "customer_id": fk_val,
                    "order_date": order_date,
                    "status": _to_text(row_dict.get("status")),
                    "total_amount": total_amount
                }
                if not reject_reasons and fk_val not in existing_customers:
                    missing_customers_to_stub.add(fk_val)
                    existing_customers.add(fk_val)

            elif dataset_type == "sales":
                fk_val = _clean_key(row_dict.get("order_id")) or "ORD_DEFAULT"
                row_dict["order_id"] = fk_val
                quantity, err_qty = _to_int(row_dict.get("quantity"), "quantity")
                unit_price, err_up = _to_float(row_dict.get("unit_price"), "unit_price")
                total_price, err_tp = _to_float(row_dict.get("total_price"), "total_price")
                sale_date, err_date = _to_datetime(row_dict.get("sale_date"), "sale_date")
                reject_reasons += [e for e in (err_qty, err_up, err_tp, err_date) if e]
                prod_row = {
                    "sale_id": row_dict["sale_id"],
                    "order_id": fk_val,
                    "product_id": _to_text(row_dict.get("product_id")),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_price": total_price,
                    "sale_date": sale_date
                }
                if not reject_reasons and fk_val not in existing_orders:
                    missing_orders_to_stub.add(fk_val)
                    existing_orders.add(fk_val)
            else:
                prod_row = {k: v for k, v in row_dict.items()}

            is_valid = not reject_reasons
            status = "Valid" if is_valid else "Rejected"
            if is_valid:
                rows_loaded += 1
                prod_row["uploaded_by"] = user_email
                production_records.append(prod_row)
            else:
                rows_rejected += 1
                rejected_records.append({
                    "row_number": row_num,
                    "record": {k: _to_text(v) for k, v in row_dict.items()},
                    "reason": "; ".join(reject_reasons)
                })

            if dataset_type in TABLE_COLUMNS:
                staging_row = {c: _to_text(row_dict.get(c)) for c in table_columns}
            else:
                staging_row = {"data_json": json.dumps(row_dict, default=str)}
            staging_row.update({"batch_id": batch_id, "row_number": row_num, "validation_status": status})
            staging_records.append(staging_row)

        # Database Loading Transaction
        is_sqlite = db.get_bind().dialect.name == "sqlite"
        staging_table = f"staging_{dataset_type}"
        try:
            # Replace any staging rows from a previous run of this batch
            db.execute(text(f"DELETE FROM {staging_table} WHERE batch_id = :b"), {"b": batch_id})
            sql_logs.append(f"DELETE FROM {staging_table} WHERE batch_id = '{batch_id}'")

            if staging_records:
                staging_cols = list(staging_records[0].keys())
                col_list = ", ".join(f"`{c}`" if c == "row_number" else c for c in staging_cols)
                values_list = ", ".join(f":{c}" for c in staging_cols)
                db.execute(text(f"INSERT INTO {staging_table} ({col_list}) VALUES ({values_list})"), staging_records)
            sql_logs.append(f"INSERTED {len(staging_records)} records into {staging_table} ({rows_rejected} flagged Rejected).")

            # Auto-provision parent stub records if referenced foreign keys are missing in DB
            if missing_customers_to_stub or missing_orders_to_stub:
                customer_stubs = set(missing_customers_to_stub)
                if missing_orders_to_stub:
                    customer_stubs.add("CUST_DEFAULT")
                for mc in customer_stubs:
                    db.execute(text(_upsert_ignore_sql(
                        is_sqlite, "customers",
                        "(customer_id, customer_name, email, phone, region, uploaded_by) VALUES (:c, 'Auto-Provisioned Customer', 'auto@customer.internal', 'N/A', 'Global', :u)",
                        "customer_id"
                    )), {"c": mc, "u": user_email})
                for mo in missing_orders_to_stub:
                    db.execute(text(_upsert_ignore_sql(
                        is_sqlite, "orders",
                        "(order_id, customer_id, order_date, status, total_amount, uploaded_by) VALUES (:o, 'CUST_DEFAULT', CURRENT_TIMESTAMP, 'Auto-Provisioned', 0.0, :u)",
                        "order_id"
                    )), {"o": mo, "u": user_email})
                sql_logs.append(f"Auto-provisioned {len(customer_stubs)} parent customer(s) and {len(missing_orders_to_stub)} parent order(s) referenced by foreign keys.")

            if production_records:
                if dataset_type in TABLE_COLUMNS:
                    prod_cols = table_columns + ["uploaded_by"]
                    db.execute(text(_upsert_sql(is_sqlite, dataset_type, prod_cols, pk_col)), production_records)
                else:
                    db.execute(
                        text("INSERT INTO production_dataset (business_columns) VALUES (:business_columns)"),
                        [{"business_columns": json.dumps({k: v for k, v in r.items() if k != "uploaded_by"}, default=str)} for r in production_records]
                    )

            sql_logs.append(f"INSERTED/UPDATED {len(production_records)} valid records into production {dataset_type} table.")
            db.commit()
        except Exception as db_err:
            db.rollback()
            logger.error(f"Database load failed: {db_err}")
            sql_logs.append(f"TRANSACTION ROLLBACK due to: {str(db_err)[:500]}")
            rows_rejected = len(df)
            rows_loaded = 0
            rejected_records = [
                {"row_number": i + 1, "record": {str(k): _to_text(v) for k, v in rec.items()}, "reason": f"DB Load Crash: {str(db_err)[:300]}"}
                for i, rec in enumerate(df.to_dict(orient="records"))
            ]
        finally:
            db.close()

        validation_status = "Success" if rows_rejected == 0 else "Passed with Warnings"
        if rows_loaded == 0:
            validation_status = "Failed"

        execution_time = time.time() - start_time
        
        # Log agent decision in DB using existing session
        try:
            log_agent_decision(
                db,
                batch_id=batch_id,
                agent_name=self.name,
                task="Format dataset and synchronize DB",
                reasoning=f"Selected storage format {format_selected} based on content structure. Loaded {rows_loaded} rows successfully, rejected {rows_rejected} rows.",
                confidence=95.0,
                execution_time=execution_time
            )
            db.commit()
        except Exception as e:
            logger.error(f"Failed logging agent decision: {e}")
        finally:
            db.close()

        logger.info(f"Storage agent processing complete. Format: {format_selected}. Saved at: {formatted_file_path}")

        return {
            "format_selected": format_selected,
            "formatted_file_path": formatted_file_path,
            "storage_reason": storage_reason,
            "storage_status": "Success" if formatted_file_path else "Failed",
            "rows_loaded": rows_loaded,
            "rows_rejected": rows_rejected,
            "validation_results": {
                "rows_loaded": rows_loaded,
                "rows_rejected": rows_rejected,
                "validation_status": validation_status,
                "sql_logs": sql_logs,
                "rejected_records": rejected_records,
                "staging_status": "Success" if rows_loaded > 0 or rows_rejected > 0 else "Failed",
                "production_status": "Success" if rows_loaded > 0 else "Failed",
                "dataset_type": dataset_type,
                "execution_time": execution_time
            }
        }

    def _save_formatted_file_to_clean_folder(self, clean_file_path: str, format_selected: str, dataset_type: str, df: pd.DataFrame, batch_id: str, user_email: str = None) -> str:
        try:
            from backend.utils.account_utils import get_user_path
            if user_email is None:
                from backend.database.mysql import SessionLocal
                db_user = SessionLocal()
                try:
                    user_email = db_user.execute(
                        text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                        {"b": batch_id}
                    ).scalar()
                except Exception as e:
                    logger.warning(f"StorageAgent failed to query uploaded_by: {e}")
                finally:
                    db_user.close()
                
            clean_dir = os.path.dirname(get_user_path(user_email, "cleaned data/dummy.txt"))
            os.makedirs(clean_dir, exist_ok=True)
            
            base_name = os.path.basename(clean_file_path)
            base_no_ext, _ = os.path.splitext(base_name)
            
            # Always save/export a copy in Microsoft Word (.docx) format to the Cleaned Data folder
            try:
                word_export_path = os.path.join(clean_dir, f"{base_no_ext}.docx")
                docx_doc = Document()
                docx_doc.add_heading(_xml_safe(f"Cleaned Dataset: {base_no_ext}"), level=0)
                docx_doc.add_paragraph(f"Formatted and structured dataset generated by Intelligent Storage Agent ({format_selected} format).")
                
                # Create Table (limit to 100 rows for size / speed reasons)
                rows_count, cols_count = df.shape
                preview_limit = min(100, rows_count)
                table = docx_doc.add_table(rows=preview_limit + 1, cols=cols_count)
                table.style = 'Table Grid'
                
                # Add Header
                hdr_cells = table.rows[0].cells
                for i, col in enumerate(df.columns):
                    hdr_cells[i].text = _xml_safe(col)
                    
                # Add Data Rows
                for r_idx in range(preview_limit):
                    row_cells = table.rows[r_idx + 1].cells
                    for c_idx in range(cols_count):
                        val = df.iloc[r_idx, c_idx]
                        row_cells[c_idx].text = "" if _is_missing(val) else _xml_safe(val)
                        
                docx_doc.save(word_export_path)
                logger.info(f"Saved formatted Word document to: {word_export_path}")
            except Exception as e_docx:
                logger.error(f"Failed exporting docx backup copy: {e_docx}")

            if format_selected == "WORD":
                return os.path.join(clean_dir, f"{base_no_ext}.docx").replace("\\", "/")

            elif format_selected == "SQL":
                target_path = os.path.join(clean_dir, f"{base_no_ext}.sql")
                sql_statements = [
                    f"-- Structured SQL Script Export for {base_no_ext}\n",
                    f"-- Table: {dataset_type}\n\n"
                ]
                
                col_defs = []
                for col in df.columns:
                    dtype_str = str(df[col].dtype)
                    if "int" in dtype_str:
                        col_type = "INT"
                    elif "float" in dtype_str:
                        col_type = "DECIMAL(10, 2)"
                    elif "date" in dtype_str or "time" in dtype_str:
                        col_type = "DATETIME"
                    else:
                        col_type = "VARCHAR(255)"
                    col_defs.append(f"  `{col}` {col_type}")
                    
                create_stmt = f"CREATE TABLE IF NOT EXISTS `{dataset_type}` (\n" + ",\n".join(col_defs) + "\n);\n\n"
                sql_statements.append(create_stmt)
                
                col_names_str = '`, `'.join(df.columns)
                for row in df.itertuples(index=False):
                    val_strs = []
                    for v in row:
                        if pd.isna(v) or v is None:
                            val_strs.append("NULL")
                        elif isinstance(v, (int, float)):
                            val_strs.append(str(v))
                        else:
                            safe_val = str(v).replace("'", "''")
                            val_strs.append(f"'{safe_val}'")
                    stmt = f"INSERT INTO `{dataset_type}` (`{col_names_str}`) VALUES ({', '.join(val_strs)});\n"
                    sql_statements.append(stmt)
                    
                with open(target_path, "w", encoding="utf-8") as sf:
                    sf.write("".join(sql_statements))
                logger.info(f"Saved formatted SQL script to: {target_path}")
                return target_path.replace("\\", "/")
 
            else: # Default CSV
                target_path = os.path.join(clean_dir, f"{base_no_ext}.csv")
                df.to_csv(target_path, index=False)
                logger.info(f"Saved formatted CSV dataset to: {target_path}")
                return target_path.replace("\\", "/")
 
        except Exception as e:
            logger.error(f"Failed generating formatted file in clean folder: {e}")
            return clean_file_path
