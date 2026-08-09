from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Boolean
from sqlalchemy.sql import func
from backend.database.mysql import Base

class RawUpload(Base):
    __tablename__ = 'raw_uploads'

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    batch_id = Column(String(100), nullable=True)
    source = Column(String(100))
    file_type = Column(String(50))
    upload_time = Column(DateTime, server_default=func.now())
    uploaded_by = Column(String(100))
    status = Column(String(50), default='Pending')

class StagingDataset(Base):
    __tablename__ = 'staging_dataset'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    row_number = Column(Integer)
    data_json = Column(Text)
    validation_status = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

class ProductionDataset(Base):
    __tablename__ = 'production_dataset'

    id = Column(Integer, primary_key=True, autoincrement=True)
    business_columns = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# Tabular Business Models: Customers
class Customer(Base):
    __tablename__ = 'customers'

    customer_id = Column(String(100), primary_key=True)
    customer_name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(50))
    region = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class StagingCustomer(Base):
    __tablename__ = 'staging_customers'

    # Using auto-increment or composite for staging
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(100))
    customer_name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    region = Column(String(100))
    batch_id = Column(String(100))
    row_number = Column(Integer)
    validation_status = Column(String(50))

# Tabular Business Models: Orders
class Order(Base):
    __tablename__ = 'orders'

    order_id = Column(String(100), primary_key=True)
    customer_id = Column(String(100), ForeignKey('customers.customer_id'))
    order_date = Column(DateTime)
    status = Column(String(50))
    total_amount = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class StagingOrder(Base):
    __tablename__ = 'staging_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100))
    customer_id = Column(String(100))
    order_date = Column(String(100))
    status = Column(String(50))
    total_amount = Column(String(100))
    batch_id = Column(String(100))
    row_number = Column(Integer)
    validation_status = Column(String(50))

# Tabular Business Models: Sales
class Sale(Base):
    __tablename__ = 'sales'

    sale_id = Column(String(100), primary_key=True)
    order_id = Column(String(100), ForeignKey('orders.order_id'))
    product_id = Column(String(100))
    quantity = Column(Integer)
    unit_price = Column(Float)
    total_price = Column(Float)
    sale_date = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class StagingSale(Base):
    __tablename__ = 'staging_sales'

    id = Column(Integer, primary_key=True, autoincrement=True)
    sale_id = Column(String(100))
    order_id = Column(String(100))
    product_id = Column(String(100))
    quantity = Column(String(100))
    unit_price = Column(String(100))
    total_price = Column(String(100))
    sale_date = Column(String(100))
    batch_id = Column(String(100))
    row_number = Column(Integer)
    validation_status = Column(String(50))

# Logs & Meta Info
class TransformationLog(Base):
    __tablename__ = 'transformation_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    agent_name = Column(String(100))
    column_name = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)
    reason = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())

class ValidationLog(Base):
    __tablename__ = 'validation_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    validation_type = Column(String(100))
    status = Column(String(50))
    message = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())

class PipelineLog(Base):
    __tablename__ = 'pipeline_logs'

    pipeline_id = Column(String(100), primary_key=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    execution_time = Column(Float)
    status = Column(String(50))

class AgentLog(Base):
    __tablename__ = 'agent_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100))
    agent_name = Column(String(100))
    task = Column(Text)
    reasoning = Column(Text)
    confidence = Column(Float)
    execution_time = Column(Float)
    timestamp = Column(DateTime, server_default=func.now())

class QualityReport(Base):
    __tablename__ = 'quality_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    missing_values = Column(Integer)
    duplicate_count = Column(Integer)
    quality_score = Column(Float)
    schema_match = Column(Boolean)

class RootCauseReport(Base):
    __tablename__ = 'root_cause_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    issue = Column(Text)
    root_cause = Column(Text)
    business_impact = Column(Text)
    technical_impact = Column(Text)
    recommendation = Column(Text)
    confidence = Column(Float)

class GeneratedReport(Base):
    __tablename__ = 'generated_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    pdf_path = Column(String(500))
    docx_path = Column(String(500), nullable=True)
    txt_path = Column(String(500), nullable=True)
    json_path = Column(String(500))
    markdown_path = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    reset_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

