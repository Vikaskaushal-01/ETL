import re

prompt = """
    You are the Senior Data Engineering Chat Assistant for the Agentic AI ETL Platform.
    Using the database context below (if any), answer the user's questions regarding their ETL runs, data quality issues, or database structure.
    
    Database Context:
    Context for requested files:

Directly matched files in the workspace filesystem:
- File clean_dataset.csv (cleaned data): [Download clean_dataset.csv](/api/v1/reports/download-file?path=cleaned%20data/clean_dataset.csv)
    
    User Query: Here is my cleaning log: {"transformation_steps": [], "clean_dataset_path": "cleaned data/clean_dataset.csv"}. Please send me the file.
"""

prompt_lower = prompt.lower()
print("database context: in prompt_lower:", "database context:" in prompt_lower)

context_section = ""
if "database context:" in prompt_lower:
    # Use case-insensitive regex split to be safe, or just find it
    parts = re.split(r'Database Context:', prompt, flags=re.IGNORECASE)
    print("parts length:", len(parts))
    if len(parts) > 1:
        context_section = re.split(r'User Query:', parts[1], flags=re.IGNORECASE)[0].strip()

print("context_section:")
print(repr(context_section))

links = re.findall(r'\[Download [^\]]+\]\([^\)]+\)', context_section)
print("links found:", links)
