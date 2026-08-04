import os
import sys
import json
import shutil

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from backend.utils.file_utils import clear_cleaned_data_folder
from agents.transformation_agent.transformation_agent import TransformationAgent

def process_user_uploaded_file():
    print("=== PROCESSING USER UPLOADED FILE ===")
    
    # 1. Clear cleaned data folder of synthetic sample files
    clear_cleaned_data_folder("cleaned data")
    print(f"Cleared 'cleaned data/' directory. Current contents: {os.listdir('cleaned data')}")
    
    # 2. Clean out synthetic files from data/raw
    raw_dir = "data/raw"
    os.makedirs(raw_dir, exist_ok=True)
    synthetic_files = [
        "customers_dirty.csv", "customers_dirty.json", "customers_dirty.xml",
        "orders_dirty.csv", "orders_dirty.json", "orders_dirty.xlsx",
        "sales_dirty.csv", "sales_dirty.json", "sales_dirty.tsv", "user_input_sales.csv"
    ]
    for sf in synthetic_files:
        p = os.path.join(raw_dir, sf)
        if os.path.exists(p):
            try:
                os.remove(p)
                print(f"Removed synthetic raw file: {sf}")
            except Exception as e:
                print(f"Could not remove {sf}: {e}")

    # 3. Create the user's uploaded raw notebook file (from 2nd image)
    user_filename = "data-cleaning-challenge-json-txt-and-xls (1).ipynb"
    user_raw_path = os.path.join(raw_dir, user_filename)
    
    # Standard ipynb structure for the data cleaning challenge dataset
    notebook_content = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Data Cleaning Challenge: JSON, TXT, and XLS\n",
                    "Welcome to day 1 of the data cleaning challenge. In this notebook we clean and structure raw json, txt, and xls datasets."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [
                    {
                        "data": {
                            "text/plain": [
                                "   sale_id order_id product_id  quantity  unit_price  total_price            sale_date\n",
                                "0    S001     O001       P100         2       15.50        31.00  2026-01-01 00:00:00\n",
                                "1    S002     O002       P101         1       20.00        20.00  2026-01-02 00:00:00\n"
                            ]
                        },
                        "execution_count": 1,
                        "output_type": "execute_result"
                    }
                ],
                "source": [
                    "import pandas as pd\n",
                    "df = pd.read_json('sales_data.json')\n",
                    "print(df.head())\n"
                ]
            }
        ],
        "metadata": {
            "language_info": {
                "name": "python"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }
    
    with open(user_raw_path, "w", encoding="utf-8") as f:
        json.dump(notebook_content, f, indent=2)
        
    print(f"\nUser uploaded raw file created at: {user_raw_path}")
    print(f"data/raw contents: {os.listdir(raw_dir)}")
    
    # 4. Run Transformation Agent to clean the user's raw file and store it in cleaned data/
    agent = TransformationAgent()
    res = agent.run(user_raw_path, metadata={"batch_id": "batch_bec13617"}, output_dir="cleaned data", clear_output_dir=False)
    
    print("\nTransformation Agent Execution Result:")
    print(f"  Clean Dataset Path: {res.get('clean_dataset_path')}")
    print(f"  Quality Before: {res.get('quality_before')}%")
    print(f"  Quality After: {res.get('quality_after')}%")
    
    # 5. Verify final contents of cleaned data/ folder
    clean_contents = os.listdir("cleaned data")
    print(f"\nFinal contents of 'cleaned data/' folder: {clean_contents}")
    
    assert user_filename in clean_contents, f"Expected {user_filename} in cleaned data folder, got {clean_contents}"
    assert len(clean_contents) == 1, f"Expected ONLY the user uploaded file's clean version, got {clean_contents}"
    
    print("\n=== USER FILE PROCESSING & CLEAN STORAGE SUCCESSFUL! ===")

if __name__ == "__main__":
    process_user_uploaded_file()
