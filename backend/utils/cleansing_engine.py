import re
from typing import Dict, Any, List, Tuple
import pandas as pd
import numpy as np


class AutonomousCleansingEngine:
    """
    Production-grade data cleansing and standardization engine.
    Applies deterministic heuristics and statistical transformations.
    """

    @classmethod
    def clean_dataframe(
        cls, 
        df: pd.DataFrame, 
        impute_strategy: str = "auto",
        cap_outliers: bool = True
    ) -> Tuple[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]]:
        """
        Cleanses input dataframe and generates comprehensive audit trail.
        Returns: (cleaned_df, transformation_audit_log, summary_stats)
        """
        cleaned = df.copy()
        audit_log: List[Dict[str, Any]] = []
        initial_rows = len(cleaned)

        # 1. Standardize column names (snake_case, strip special characters)
        old_cols = list(cleaned.columns)
        new_cols = [
            re.sub(r"[^\w\s]", "", str(c)).strip().lower().replace(" ", "_").replace("-", "_")
            for c in old_cols
        ]
        cleaned.columns = new_cols
        for o, n in zip(old_cols, new_cols):
            if o != n:
                audit_log.append({
                    "column_name": n,
                    "operation": "COLUMN_RENAME",
                    "old_value": o,
                    "new_value": n,
                    "reason": "Standardized to clean snake_case identifier"
                })

        # 2. Deduplication
        duplicates_count = int(cleaned.duplicated().sum())
        if duplicates_count > 0:
            cleaned = cleaned.drop_duplicates().reset_index(drop=True)
            audit_log.append({
                "column_name": "GLOBAL",
                "operation": "DEDUPLICATION",
                "old_value": f"{initial_rows} rows",
                "new_value": f"{len(cleaned)} rows",
                "reason": f"Removed {duplicates_count} duplicate record rows"
            })

        # 3. Column-by-column transformation and imputation
        for col in cleaned.columns:
            series = cleaned[col]
            nulls_before = int(series.isna().sum())

            # A. Clean String Columns
            if series.dtype == object or pd.api.types.is_string_dtype(series):
                # Strip leading/trailing whitespaces and empty strings to NaN
                cleaned_str = series.astype(str).str.strip()
                cleaned_str = cleaned_str.replace({"nan": np.nan, "None": np.nan, "null": np.nan, "": np.nan})
                cleaned[col] = cleaned_str

                # Impute missing categoricals with Mode if nulls exist
                if nulls_before > 0:
                    mode_val = cleaned[col].mode()
                    replacement = mode_val[0] if len(mode_val) > 0 else "UNKNOWN"
                    cleaned[col] = cleaned[col].fillna(replacement)
                    audit_log.append({
                        "column_name": col,
                        "operation": "CATEGORICAL_IMPUTATION",
                        "old_value": f"{nulls_before} null values",
                        "new_value": str(replacement),
                        "reason": f"Replaced missing string values with mode value '{replacement}'"
                    })

            # B. Clean Numeric Columns (IQR Outlier Capping & Median Imputation)
            elif pd.api.types.is_numeric_dtype(series):
                # Impute missing numeric with median
                if nulls_before > 0:
                    med_val = series.median()
                    if pd.notna(med_val):
                        cleaned[col] = series.fillna(med_val)
                        audit_log.append({
                            "column_name": col,
                            "operation": "NUMERIC_IMPUTATION",
                            "old_value": f"{nulls_before} null values",
                            "new_value": round(float(med_val), 4),
                            "reason": f"Imputed missing numeric values with column median ({med_val})"
                        })

                # IQR Outlier Winsorization
                if cap_outliers and len(cleaned[col].dropna()) >= 10:
                    q25 = cleaned[col].quantile(0.25)
                    q75 = cleaned[col].quantile(0.75)
                    iqr = q75 - q25
                    lower_bound = q25 - 1.5 * iqr
                    upper_bound = q75 + 1.5 * iqr

                    outliers_low = (cleaned[col] < lower_bound).sum()
                    outliers_high = (cleaned[col] > upper_bound).sum()

                    if outliers_low > 0 or outliers_high > 0:
                        cleaned[col] = cleaned[col].clip(lower=lower_bound, upper=upper_bound)
                        audit_log.append({
                            "column_name": col,
                            "operation": "OUTLIER_CAPPING",
                            "old_value": f"{outliers_low + outliers_high} outliers",
                            "new_value": f"[{round(lower_bound, 2)}, {round(upper_bound, 2)}]",
                            "reason": f"Winsorized statistical outliers to 1.5x IQR boundaries"
                        })

        summary_stats = {
            "initial_rows": initial_rows,
            "final_rows": len(cleaned),
            "duplicates_removed": duplicates_count,
            "transformations_applied": len(audit_log),
            "remaining_nulls": int(cleaned.isna().sum().sum())
        }

        return cleaned, audit_log, summary_stats
