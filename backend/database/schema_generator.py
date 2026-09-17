import re
from typing import Dict, Any, List
import pandas as pd


class DynamicSQLSchemaGenerator:
    """
    Generates dynamic SQL DDL statements (MySQL and SQLite compliant)
    and migration definitions from ingested pandas dataframes.
    """

    PANDAS_TO_SQL_MYSQL: Dict[str, str] = {
        "int64": "BIGINT",
        "int32": "INT",
        "float64": "DOUBLE",
        "float32": "FLOAT",
        "bool": "BOOLEAN",
        "datetime64[ns]": "DATETIME",
        "object": "VARCHAR(255)",
    }

    PANDAS_TO_SQL_SQLITE: Dict[str, str] = {
        "int64": "INTEGER",
        "int32": "INTEGER",
        "float64": "REAL",
        "float32": "REAL",
        "bool": "INTEGER",
        "datetime64[ns]": "TEXT",
        "object": "TEXT",
    }

    @classmethod
    def generate_ddl(
        cls, 
        table_name: str, 
        df: pd.DataFrame, 
        dialect: str = "mysql",
        primary_key: str = None
    ) -> str:
        """Generates CREATE TABLE IF NOT EXISTS DDL script."""
        safe_table = re.sub(r"[^\w]", "_", table_name).lower()
        mapping = cls.PANDAS_TO_SQL_MYSQL if dialect.lower() == "mysql" else cls.PANDAS_TO_SQL_SQLITE
        
        column_defs: List[str] = []
        for col, dtype in df.dtypes.items():
            safe_col = re.sub(r"[^\w]", "_", str(col)).lower()
            sql_type = mapping.get(str(dtype), "VARCHAR(255)" if dialect == "mysql" else "TEXT")
            
            # If string length exceeds standard 255, expand to TEXT
            if str(dtype) == "object" and dialect == "mysql":
                max_len = df[col].dropna().astype(str).str.len().max() if len(df[col].dropna()) > 0 else 0
                if max_len > 255:
                    sql_type = "TEXT"

            pk_clause = " PRIMARY KEY" if primary_key and safe_col == primary_key.lower() else ""
            column_defs.append(f"    `{safe_col}` {sql_type}{pk_clause}")

        # Add tracking metadata columns
        column_defs.append("    `_ingested_at` DATETIME DEFAULT CURRENT_TIMESTAMP" if dialect == "mysql" else "    `_ingested_at` TEXT DEFAULT CURRENT_TIMESTAMP")
        column_defs.append("    `_batch_id` VARCHAR(64)" if dialect == "mysql" else "    `_batch_id` TEXT")

        columns_str = ",\n".join(column_defs)
        return f"CREATE TABLE IF NOT EXISTS `{safe_table}` (\n{columns_str}\n);\n"

    @classmethod
    def generate_insert_statement(cls, table_name: str, df: pd.DataFrame, dialect: str = "mysql") -> str:
        """Generates parameterized INSERT template."""
        safe_table = re.sub(r"[^\w]", "_", table_name).lower()
        safe_cols = [re.sub(r"[^\w]", "_", str(c)).lower() for c in df.columns]
        
        cols_clause = ", ".join([f"`{c}`" for c in safe_cols])
        placeholders = ", ".join([f":{c}" for c in safe_cols])
        
        return f"INSERT INTO `{safe_table}` ({cols_clause}) VALUES ({placeholders});"
