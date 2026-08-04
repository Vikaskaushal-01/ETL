import os
import pandas as pd

def generate_data():
    raw_dir = "data/raw"
    os.makedirs(raw_dir, exist_ok=True)
    
    # 1. Customers Dataset (contains duplicates and missing emails)
    customers_data = {
        "Customer ID": ["C001", "C002", "C003", "C001", "C004"],
        "Customer Name": ["Alice Smith", "Bob Jones", "Charlie Brown", "Alice Smith", "Diana Prince"],
        "Email": ["alice@example.com", "bob@example.com", None, "alice@example.com", "diana@example.com"],
        "Phone": ["555-0100", "555-0200", "555-0300", "555-0100", "555-0400"],
        "Region": ["North", "South", "East", "North", "West"]
    }
    df_customers = pd.DataFrame(customers_data)
    
    # Write customers in CSV, JSON, and XML formats
    df_customers.to_csv(os.path.join(raw_dir, "customers_dirty.csv"), index=False)
    df_customers.to_json(os.path.join(raw_dir, "customers_dirty.json"), orient="records", indent=2)
    
    # XML tags cannot contain spaces, so rename spaces to underscores
    df_customers_xml = df_customers.rename(columns=lambda x: x.replace(" ", "_"))
    df_customers_xml.to_xml(os.path.join(raw_dir, "customers_dirty.xml"), index=False, parser="etree")
    print("Generated dirty customers datasets (CSV, JSON, XML).")

    # 2. Orders Dataset (with valid FK references and date formatting checks)
    orders_data = {
        "Order ID": ["O101", "O102", "O103", "O104", "O105"],
        "Customer ID": ["C001", "C002", "C003", "C004", "C002"],
        "Order Date": ["2026/07/20", "2026-07-21 10:00:00", "July 22, 2026", "2026-07-23", "2026-07-24"],
        "Status": ["Shipped", "Pending", "Cancelled", "Shipped", "Shipped"],
        "Total Amount": [150.50, 200.00, 45.00, 320.10, 85.00]
    }
    df_orders = pd.DataFrame(orders_data)
    
    # Write orders in CSV, JSON, and Excel formats
    df_orders.to_csv(os.path.join(raw_dir, "orders_dirty.csv"), index=False)
    df_orders.to_json(os.path.join(raw_dir, "orders_dirty.json"), orient="records", indent=2)
    df_orders.to_excel(os.path.join(raw_dir, "orders_dirty.xlsx"), index=False)
    print("Generated dirty orders datasets (CSV, JSON, XLSX).")
 
    # 3. Sales Dataset (with valid FK references and unique primary keys)
    sales_data = {
        "Sale ID": ["S201", "S202", "S203", "S204", "S205"],
        "Order ID": ["O101", "O102", "O103", "O104", "O101"],
        "Product ID": ["P001", "P002", "P003", "P001", "P002"],
        "Quantity": [2, None, 1, 2, 5],
        "Unit Price": [50.00, 25.00, None, 50.00, 25.00],
        "Total Price": [100.00, None, 15.00, 100.00, None],
        "Sale Date": ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-20", "2026-07-25"]
    }
    df_sales = pd.DataFrame(sales_data)
    
    # Write sales in CSV, TSV, and JSON formats
    df_sales.to_csv(os.path.join(raw_dir, "sales_dirty.csv"), index=False)
    df_sales.to_csv(os.path.join(raw_dir, "sales_dirty.tsv"), sep="\t", index=False)
    df_sales.to_json(os.path.join(raw_dir, "sales_dirty.json"), orient="records", indent=2)
    print("Generated dirty sales datasets (CSV, TSV, JSON).")

if __name__ == "__main__":
    generate_data()
