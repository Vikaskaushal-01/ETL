import os
import json
import logging
import time
from backend.utils.file_utils import read_dataset, detect_file_info
from backend.core.llm import query_llm

logger = logging.getLogger("etl_intake_agent")

class IntakeAgent:
    def __init__(self):
        self.role = "Senior Data Engineer"
        self.name = "Data Intake Agent"

    def run(self, file_path: str) -> dict:
        start_time = time.time()
        logger.info(f"Running Data Intake Agent on {file_path}")
        
        file_info = detect_file_info(file_path)
        
        # Optimize profiling for large files (> 10 MB)
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        if file_size > 10 * 1024 * 1024:
            logger.info("Large dataset detected (>10MB). Ingesting first 20,000 rows for schema profiling.")
            df = read_dataset(file_path, nrows=20000)
        else:
            df = read_dataset(file_path)
        
        row_count, col_count = df.shape
        column_names = list(df.columns)
        
        # Calculate missing values
        missing_values = df.isnull().sum().to_dict()
        missing_values = {k: int(v) for k, v in missing_values.items()}
        
        # Calculate duplicates
        duplicate_count = int(df.duplicated().sum())
        
        # Datatypes summary
        col_types = {col: str(dtype) for col, dtype in df.dtypes.items()}
        
        # Take a small preview (first 5 rows)
        preview_data = df.head(5).to_dict(orient='records')
        
        # Construct prompt for the LLM
        prompt = f"""
        You are a Senior Data Engineer analyzing a newly uploaded dataset.
        File Path: {file_path}
        File Type: {file_info['file_type']}
        Delimiter: {file_info['delimiter']}
        Encoding: {file_info['encoding']}
        
        Dataset Profile:
        - Total Rows: {row_count}
        - Total Columns: {col_count}
        - Columns: {column_names}
        - Column Data Types (Inferred by Pandas): {col_types}
        - Missing Values: {missing_values}
        - Duplicate Rows: {duplicate_count}
        
        First 5 rows preview:
        {json.dumps(preview_data, default=str, indent=2)}
        
        Generate a data profile report in JSON format. Ensure it includes:
        1. dataset_name (basename of file)
        2. rows (int)
        3. columns (int)
        4. column_names (array of strings)
        5. column_types (object mapping col -> datatype)
        6. missing_values (object mapping col -> count)
        7. duplicate_rows (int)
        8. estimated_quality (float between 0 and 100 based on completeness and uniqueness)
        9. recommended_transformations (array of strings outlining what cleaning steps are needed)
        
        Return ONLY valid JSON.
        """
        
        system_instruction = "You are the Data Intake Agent. Analyze dataset parameters and return structured JSON metadata. Never edit the raw file."
        
        try:
            llm_response = query_llm(prompt, system_instruction, json_mode=True)
            # Clean response text from markdown block quotes if present
            if "```json" in llm_response:
                llm_response = llm_response.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_response:
                llm_response = llm_response.split("```")[1].split("```")[0].strip()
            
            analysis = json.loads(llm_response.strip())
        except Exception as e:
            logger.error(f"Error parsing LLM response in IntakeAgent: {e}")
            # Fallback local calculation
            total_elements = row_count * col_count
            total_nulls = sum(missing_values.values())
            quality_score = 100.0
            if total_elements > 0:
                quality_score = round(((total_elements - total_nulls - duplicate_count) / total_elements) * 100, 2)
                quality_score = max(0.0, quality_score)
                
            analysis = {
                "dataset_name": os.path.basename(file_path),
                "rows": row_count,
                "columns": col_count,
                "column_names": column_names,
                "column_types": col_types,
                "missing_values": missing_values,
                "duplicate_rows": duplicate_count,
                "estimated_quality": quality_score,
                "recommended_transformations": [
                    "Trim spaces in column headers",
                    "Handle missing values in incomplete fields",
                    "Deduplicate records"
                ]
            }

        execution_time = time.time() - start_time
        analysis["execution_time"] = execution_time
        analysis["file_info"] = file_info
        
        logger.info(f"Intake completed in {execution_time:.2f}s with quality score {analysis.get('estimated_quality')}%")
        return analysis
