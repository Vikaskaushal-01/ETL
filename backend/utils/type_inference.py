import re
import math
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np


class SemanticTypeInferenceEngine:
    """
    Advanced semantic type inference and anomaly detection engine for autonomous ETL.
    Analyzes series values and infers business data types beyond basic Python types.
    """

    EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    PHONE_REGEX = re.compile(r"^(\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}$")
    IP_REGEX = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    UUID_REGEX = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    CURRENCY_REGEX = re.compile(r"^[\$\€\£\¥\₹]?\s*-?\d{1,3}(?:,\d{3})*(?:\.\d{1,4})?\s*[\$\€\£\¥\₹]?$")

    @classmethod
    def infer_column_type(cls, series: pd.Series) -> str:
        """Infers granular semantic type of a pandas Series."""
        cleaned = series.dropna().astype(str).str.strip()
        if len(cleaned) == 0:
            return "empty"

        sample_size = min(len(cleaned), 500)
        sample = cleaned.sample(n=sample_size, random_state=42) if len(cleaned) > sample_size else cleaned

        # 1. Boolean check
        bool_matches = sample.str.lower().isin(["true", "false", "1", "0", "yes", "no", "y", "n", "t", "f"])
        if bool_matches.mean() > 0.90:
            return "boolean"

        # 2. UUID check
        if sample.apply(lambda x: bool(cls.UUID_REGEX.match(x))).mean() > 0.85:
            return "uuid"

        # 3. Email check
        if sample.apply(lambda x: bool(cls.EMAIL_REGEX.match(x))).mean() > 0.80:
            return "email"

        # 4. IP Address check
        if sample.apply(lambda x: bool(cls.IP_REGEX.match(x))).mean() > 0.80:
            return "ip_address"

        # 5. Currency / Numeric format check
        if sample.apply(lambda x: bool(cls.CURRENCY_REGEX.match(x))).mean() > 0.85:
            # Check if pure float or currency symbol
            has_symbol = sample.str.contains(r"[\$\€\£\¥\₹]", regex=True).mean() > 0.1
            return "currency" if has_symbol else ("integer" if sample.str.isdigit().mean() > 0.9 else "float")

        # 6. Datetime check
        try:
            parsed = pd.to_datetime(sample, errors="coerce")
            if (parsed.notna().mean()) > 0.85:
                return "datetime"
        except Exception:
            pass

        # 7. Categorical vs Free Text check
        unique_ratio = series.nunique() / max(len(series), 1)
        if unique_ratio < 0.10 and series.nunique() <= 50:
            return "categorical"

        return "string"

    @classmethod
    def detect_outliers_zscore(cls, series: pd.Series, threshold: float = 3.0) -> List[int]:
        """Returns indices of numeric outliers using Z-score method."""
        numeric_series = pd.to_numeric(series, errors="coerce").dropna()
        if len(numeric_series) < 5 or numeric_series.std() == 0:
            return []
        
        mean = numeric_series.mean()
        std = numeric_series.std()
        z_scores = (numeric_series - mean) / std
        return numeric_series[z_scores.abs() > threshold].index.tolist()

    @classmethod
    def profile_dataframe(cls, df: pd.DataFrame) -> Dict[str, Any]:
        """Comprehensive dataframe schema profiling."""
        total_rows = len(df)
        columns_profile = {}
        total_missing = int(df.isna().sum().sum())
        total_duplicates = int(df.duplicated().sum())

        for col in df.columns:
            series = df[col]
            inferred_type = cls.infer_column_type(series)
            null_count = int(series.isna().sum())
            null_pct = round((null_count / max(total_rows, 1)) * 100, 2)
            unique_count = int(series.nunique(dropna=True))

            outlier_indices = []
            if pd.api.types.is_numeric_dtype(series):
                outlier_indices = cls.detect_outliers_zscore(series)

            columns_profile[col] = {
                "inferred_type": inferred_type,
                "null_count": null_count,
                "null_percentage": null_pct,
                "unique_count": unique_count,
                "outlier_count": len(outlier_indices),
                "is_primary_key_candidate": unique_count == total_rows and null_count == 0
            }

        # Overall estimated data quality score (0 - 100)
        penalty = (total_missing / max(total_rows * max(len(df.columns), 1), 1)) * 40
        dup_penalty = (total_duplicates / max(total_rows, 1)) * 30
        quality_score = max(0.0, min(100.0, round(100.0 - penalty - dup_penalty, 2)))

        return {
            "total_rows": total_rows,
            "total_columns": len(df.columns),
            "total_missing_values": total_missing,
            "total_duplicates": total_duplicates,
            "overall_quality_score": quality_score,
            "columns": columns_profile
        }
