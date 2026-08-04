CREATE DATABASE IF NOT EXISTS agentic_ai_etl;
USE agentic_ai_etl;

-- 1. raw_uploads
CREATE TABLE IF NOT EXISTS raw_uploads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    source VARCHAR(100),
    file_type VARCHAR(50),
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by VARCHAR(100),
    status VARCHAR(50) DEFAULT 'Pending'
);

-- 2. staging_dataset
CREATE TABLE IF NOT EXISTS staging_dataset (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100) NOT NULL,
    row_number INT,
    data_json TEXT,
    validation_status VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. production_dataset
CREATE TABLE IF NOT EXISTS production_dataset (
    id INT AUTO_INCREMENT PRIMARY KEY,
    business_columns TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 4. customers (Production)
CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR(100) PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    region VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Staging Customers
CREATE TABLE IF NOT EXISTS staging_customers (
    customer_id VARCHAR(100),
    customer_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    region VARCHAR(100),
    batch_id VARCHAR(100),
    row_number INT,
    validation_status VARCHAR(50)
);

-- 5. orders (Production)
CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(100) PRIMARY KEY,
    customer_id VARCHAR(100),
    order_date DATETIME,
    status VARCHAR(50),
    total_amount DECIMAL(15, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

-- Staging Orders
CREATE TABLE IF NOT EXISTS staging_orders (
    order_id VARCHAR(100),
    customer_id VARCHAR(100),
    order_date VARCHAR(100),
    status VARCHAR(50),
    total_amount VARCHAR(100),
    batch_id VARCHAR(100),
    row_number INT,
    validation_status VARCHAR(50)
);

-- 6. sales (Production)
CREATE TABLE IF NOT EXISTS sales (
    sale_id VARCHAR(100) PRIMARY KEY,
    order_id VARCHAR(100),
    product_id VARCHAR(100),
    quantity INT,
    unit_price DECIMAL(15, 2),
    total_price DECIMAL(15, 2),
    sale_date DATETIME,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

-- Staging Sales
CREATE TABLE IF NOT EXISTS staging_sales (
    sale_id VARCHAR(100),
    order_id VARCHAR(100),
    product_id VARCHAR(100),
    quantity VARCHAR(100),
    unit_price VARCHAR(100),
    total_price VARCHAR(100),
    sale_date VARCHAR(100),
    batch_id VARCHAR(100),
    row_number INT,
    validation_status VARCHAR(50)
);

-- 7. transformation_logs
CREATE TABLE IF NOT EXISTS transformation_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100) NOT NULL,
    agent_name VARCHAR(100),
    column_name VARCHAR(100),
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. validation_logs
CREATE TABLE IF NOT EXISTS validation_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100) NOT NULL,
    validation_type VARCHAR(100),
    status VARCHAR(50),
    message TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. pipeline_logs
CREATE TABLE IF NOT EXISTS pipeline_logs (
    pipeline_id VARCHAR(100) PRIMARY KEY,
    start_time TIMESTAMP NULL DEFAULT NULL,
    end_time TIMESTAMP NULL DEFAULT NULL,
    execution_time DOUBLE,
    status VARCHAR(50)
);

-- 10. agent_logs
CREATE TABLE IF NOT EXISTS agent_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100),
    agent_name VARCHAR(100),
    task TEXT,
    reasoning TEXT,
    confidence DOUBLE,
    execution_time DOUBLE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. quality_reports
CREATE TABLE IF NOT EXISTS quality_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100) NOT NULL,
    missing_values INT,
    duplicate_count INT,
    quality_score DOUBLE,
    schema_match TINYINT(1)
);

-- 12. root_cause_reports
CREATE TABLE IF NOT EXISTS root_cause_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100) NOT NULL,
    issue TEXT,
    root_cause TEXT,
    business_impact TEXT,
    technical_impact TEXT,
    recommendation TEXT,
    confidence DOUBLE
);

-- 13. generated_reports
CREATE TABLE IF NOT EXISTS generated_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(100) NOT NULL,
    pdf_path VARCHAR(500),
    docx_path VARCHAR(500),
    json_path VARCHAR(500),
    markdown_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
