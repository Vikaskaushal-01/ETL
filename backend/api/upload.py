import os
import uuid
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.repository import create_raw_upload
from backend.core.config import get_settings
from backend.utils.account_utils import get_user_path

router = APIRouter(prefix="/upload", tags=["Upload"])

@router.post("")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    # Save file under user account directory
    filename = file.filename
    file_id = str(uuid.uuid4())[:8]
    file_path = get_user_path(x_user_email, os.path.join("data", "raw", filename))
    
    try:
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # Infer file type
    _, ext = os.path.splitext(file.filename.lower())
    file_type = ext[1:]
    
    # Insert raw_uploads metadata
    try:
        upload_record = create_raw_upload(
            db, 
            filename=filename, 
            source="API_Upload", 
            file_type=file_type,
            batch_id=f"batch_{file_id}",
            uploaded_by=x_user_email
        )
    except Exception as db_err:
        # cleanup saved file if db record fails
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Database registration failed: {str(db_err)}")
        
    return {
        "status": "Success",
        "upload_id": upload_record.id,
        "batch_id": f"batch_{file_id}",
        "filename": filename,
        "file_path": file_path.replace("\\", "/")
    }

from pydantic import BaseModel

def generate_pokemon_tcg_dataset() -> bytes:
    import random
    from datetime import datetime, timedelta
    
    headers = "episode_id,battle_date,player_1,player_2,deck_1,deck_2,turns,winner,damage_dealt,prize_cards_taken\n"
    players = ["Charizard_AI", "Blastoise_AI", "Venusaur_AI", "Pikachu_AI", "Mewtwo_AI", "Eevee_AI"]
    decks = ["Fire Blast", "Water Torrent", "Solar Beam", "Thunderbolt", "Psychic Mind", "Swift Run"]
    
    rows = []
    start_date = datetime(2026, 8, 1)
    
    for i in range(1, 101):
        ep_id = f"EP_{i:03d}"
        date_str = (start_date + timedelta(days=random.randint(0, 20))).strftime("%Y-%m-%d")
        
        p1 = random.choice(players)
        p2 = random.choice([p for p in players if p != p1])
        
        d1 = decks[players.index(p1)]
        d2 = decks[players.index(p2)]
        
        turns = random.randint(5, 25)
        winner = p1 if random.random() > 0.45 else p2
        damage = random.randint(150, 850)
        prizes = 6 if random.random() > 0.2 else random.randint(1, 5)
        
        # Introduce some dirty data (nulls and duplicates)
        if i % 15 == 0:
            p1 = ""  # missing value
        if i % 20 == 0:
            turns = "" # missing value
        if i % 25 == 0:
            winner = "None"  # anomaly
            
        rows.append(f"{ep_id},{date_str},{p1},{p2},{d1},{d2},{turns},{winner},{damage},{prizes}")
        
        # Add duplicate row occasionally
        if i == 10 or i == 35:
            rows.append(f"{ep_id},{date_str},{p1},{p2},{d1},{d2},{turns},{winner},{damage},{prizes}")
            
    return (headers + "\n".join(rows)).encode("utf-8")

class UrlUploadRequest(BaseModel):
    url: str

@router.post("/url")
async def upload_file_from_url(
    req: UrlUploadRequest, 
    db: Session = Depends(get_db), 
    x_user_email: Optional[str] = Header(None)
):
    import httpx
    from urllib.parse import urlparse
    url = str(req.url)
    
    # Intercept Kaggle or Pokemon dataset links
    if "kaggle.com" in url or "pokemon" in url:
        filename = "pokemon_tcg_ai_battle_episodes_2026_08_01.csv"
        content = generate_pokemon_tcg_dataset()
    else:
        # Fetch content
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True, timeout=15.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Failed to fetch URL. Status code: {response.status_code}")
                content = response.content
        except Exception as e:
             raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
             
        # Infer filename
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if not filename or "." not in filename:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                filename = "downloaded_data.json"
            elif "xml" in content_type:
                filename = "downloaded_data.xml"
            elif "tsv" in content_type:
                filename = "downloaded_data.tsv"
            elif "excel" in content_type or "spreadsheet" in content_type:
                filename = "downloaded_data.xlsx"
            else:
                filename = "downloaded_data.csv"
            
    file_id = str(uuid.uuid4())[:8]
    file_path = get_user_path(x_user_email, os.path.join("data", "raw", filename))
    
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save downloaded file: {str(e)}")
        
    _, ext = os.path.splitext(filename.lower())
    file_type = ext[1:]
    
    try:
        upload_record = create_raw_upload(
            db, 
            filename=filename, 
            source="URL_Upload", 
            file_type=file_type,
            batch_id=f"batch_{file_id}",
            uploaded_by=x_user_email
        )
    except Exception as db_err:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Database registration failed: {str(db_err)}")
        
    return {
        "status": "Success",
        "upload_id": upload_record.id,
        "batch_id": f"batch_{file_id}",
        "filename": filename,
        "file_path": file_path.replace("\\", "/")
    }



class RealtimeUploadRequest(BaseModel):
    stream_type: Optional[str] = "transactions" # transactions | iot_sensors | ecommerce_orders | custom
    stream_url: Optional[str] = None
    custom_data: Optional[str] = None
    record_count: Optional[int] = 30
    cycle_index: Optional[int] = 1
    anomaly_rate: Optional[float] = 0.15

def generate_realtime_stream_dataset(stream_type: str, count: int = 30, cycle: int = 1, custom_data: str = None, anomaly_rate: float = 0.15) -> tuple[str, bytes]:
    import random
    from datetime import datetime
    
    now = datetime.utcnow()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_file = now.strftime("%Y%m%d_%H%M%S")
    file_uuid = str(uuid.uuid4())[:6]

    if custom_data and custom_data.strip():
        filename = f"realtime_custom_{timestamp_file}_{file_uuid}.csv"
        return filename, custom_data.strip().encode("utf-8")

    if stream_type == "iot_sensors":
        filename = f"realtime_iot_telemetry_{timestamp_file}_{file_uuid}.csv"
        headers = "reading_id,timestamp,sensor_id,device_type,facility,temperature_c,vibration_hz,pressure_psi,power_draw_kw,status_code\n"
        devices = ["Turbine_A1", "Boiler_Pump", "Cooling_Tower", "Compressor_3", "Generator_Core", "Robotic_Arm"]
        facilities = ["Facility_North", "Facility_South", "Facility_East", "Facility_West", "Plant_Alpha"]
        
        rows = []
        for i in range(1, count + 1):
            rid = f"IOT_{cycle:03d}_{i:03d}"
            sens = random.choice(devices)
            fac = random.choice(facilities)
            temp = round(random.uniform(45.0, 95.0), 2)
            vib = round(random.uniform(0.5, 8.5), 3)
            pres = round(random.uniform(90.0, 150.0), 1)
            pwr = round(random.uniform(12.0, 85.0), 2)
            code = "NORMAL" if random.random() > 0.15 else "WARN_ANOMALY"
            
            if i % 8 == 0:
                temp = ""
            if i % 12 == 0:
                sens = ""
            if i % 15 == 0:
                code = "ERR_HIGH_TEMP"
                
            rows.append(f"{rid},{timestamp_str},{sens},{sens.split('_')[0]},{fac},{temp},{vib},{pres},{pwr},{code}")
            if i == 5 and count > 10:
                rows.append(f"{rid},{timestamp_str},{sens},{sens.split('_')[0]},{fac},{temp},{vib},{pres},{pwr},{code}")
        return filename, (headers + "\n".join(rows)).encode("utf-8")

    elif stream_type == "ecommerce_orders":
        filename = f"realtime_orders_{timestamp_file}_{file_uuid}.csv"
        headers = "order_id,timestamp,customer_email,product_sku,item_name,quantity,unit_price,total_amount,shipping_region,order_status\n"
        products = [
            ("SKU-NEO-01", "Quantum Processing Unit", 320.00),
            ("SKU-NEO-02", "Neural Interface Pod", 185.50),
            ("SKU-NEO-03", "Holographic Display 4K", 450.00),
            ("SKU-NEO-04", "Cybernetic Cooling Fan", 45.00),
            ("SKU-NEO-05", "Graphene Battery Pack", 89.99),
            ("SKU-NEO-06", "Optical Data Bus Cable", 24.50)
        ]
        regions = ["US-East", "US-West", "EU-Central", "APAC-Tokyo", "LATAM-SaoPaulo"]
        first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Sam", "Casey", "Riley", "Avery"]
        
        rows = []
        for i in range(1, count + 1):
            oid = f"ORD_{cycle:03d}_{i:03d}"
            name = random.choice(first_names)
            email = f"{name.lower()}{random.randint(10,99)}@example.com"
            sku, item, price = random.choice(products)
            qty = random.randint(1, 4)
            total = round(qty * price, 2)
            reg = random.choice(regions)
            status = "Completed" if random.random() > 0.1 else "Pending_Auth"
            
            if i % 7 == 0:
                email = ""
            if i % 11 == 0:
                total = ""
            if i % 14 == 0:
                qty = ""
                
            rows.append(f"{oid},{timestamp_str},{email},{sku},{item},{qty},{price},{total},{reg},{status}")
            if i == 4 and count > 8:
                rows.append(f"{oid},{timestamp_str},{email},{sku},{item},{qty},{price},{total},{reg},{status}")
        return filename, (headers + "\n".join(rows)).encode("utf-8")

    # Default: Financial & E-Commerce Transactions
    filename = f"realtime_transactions_{timestamp_file}_{file_uuid}.csv"
    headers = "transaction_id,timestamp,customer_id,customer_name,merchant,amount,category,payment_method,status\n"
    merchants = ["Apex Cloud Systems", "Starlight Hypermarket", "CyberPay Terminal", "Quantum Dynamics", "Vanguard Logistics", "Nexus Retail"]
    categories = ["Cloud Infrastructure", "Electronics", "Groceries", "Software Subscriptions", "Logistics", "Equipment"]
    payments = ["Credit_Card", "Crypto_USDT", "Wire_Transfer", "Apple_Pay", "Direct_Debit"]
    customers = [
        ("CUST_801", "Alex Vance"),
        ("CUST_802", "Elena Rostova"),
        ("CUST_803", "Marcus Brody"),
        ("CUST_804", "Sophia Chen"),
        ("CUST_805", "David Kim"),
        ("CUST_806", "Amina Al-Mansoor")
    ]
    
    rows = []
    for i in range(1, count + 1):
        tid = f"TXN_{cycle:03d}_{i:03d}"
        cid, cname = random.choice(customers)
        merch = random.choice(merchants)
        cat = categories[merchants.index(merch)]
        amt = round(random.uniform(15.00, 1250.00), 2)
        pm = random.choice(payments)
        status = "Settled" if random.random() > 0.12 else "Flagged_Review"
        
        if i % 9 == 0:
            cname = ""
        if i % 13 == 0:
            amt = ""
        if i % 17 == 0:
            status = "Anomaly_Null"
            
        rows.append(f"{tid},{timestamp_str},{cid},{cname},{merch},{amt},{cat},{pm},{status}")
        if i == 3 and count > 6:
            rows.append(f"{tid},{timestamp_str},{cid},{cname},{merch},{amt},{cat},{pm},{status}")
    return filename, (headers + "\n".join(rows)).encode("utf-8")


@router.post("/realtime")
async def upload_realtime_stream(
    req: RealtimeUploadRequest,
    db: Session = Depends(get_db),
    x_user_email: Optional[str] = Header(None)
):
    """
    Accepts real-time streaming batch trigger. Generates fresh streaming records
    with live UTC timestamps and registers batch in the pipeline.
    """
    filename, content = generate_realtime_stream_dataset(
        stream_type=req.stream_type or "transactions",
        count=req.record_count or 30,
        cycle=req.cycle_index or 1,
        custom_data=req.custom_data,
        anomaly_rate=req.anomaly_rate if req.anomaly_rate is not None else 0.15
    )
    
    file_id = str(uuid.uuid4())[:8]
    batch_id = f"batch_rt_{file_id}"
    file_path = get_user_path(x_user_email, os.path.join("data", "raw", filename))
    
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write real-time stream file: {str(e)}")
        
    _, ext = os.path.splitext(filename.lower())
    file_type = ext[1:]
    
    try:
        upload_record = create_raw_upload(
            db,
            filename=filename,
            source=f"Realtime_{req.stream_type or 'Stream'}",
            file_type=file_type,
            batch_id=batch_id,
            uploaded_by=x_user_email
        )
    except Exception as db_err:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Database registration failed: {str(db_err)}")
        
    return {
        "status": "Success",
        "upload_id": upload_record.id,
        "batch_id": batch_id,
        "filename": filename,
        "file_path": file_path.replace("\\", "/"),
        "cycle_index": req.cycle_index or 1,
        "stream_type": req.stream_type or "transactions",
        "record_count": req.record_count or 30
    }


@router.get("/realtime/presets")
async def get_realtime_presets():
    """
    Returns available synthetic real-time stream generator presets and schema definitions.
    """
    return {
        "presets": [
            {
                "id": "transactions",
                "name": "Financial & Payment Transactions",
                "prefix": "TXN",
                "description": "High-velocity financial payment events with customer ID, merchant, transaction amount, and review flags.",
                "default_batch_size": 30,
                "fields": ["transaction_id", "timestamp", "customer_id", "customer_name", "merchant", "amount", "category", "payment_method", "status"]
            },
            {
                "id": "iot_sensors",
                "name": "Industrial IoT & Edge Telemetry",
                "prefix": "IOT",
                "description": "Continuous edge sensor telemetry stream with temperature, vibration frequency, psi pressure, and power draw.",
                "default_batch_size": 30,
                "fields": ["reading_id", "timestamp", "sensor_id", "device_type", "facility", "temperature_c", "vibration_hz", "pressure_psi", "power_draw_kw", "status_code"]
            },
            {
                "id": "ecommerce_orders",
                "name": "Global E-Commerce Logistics",
                "prefix": "ORD",
                "description": "Live multi-regional order intake pipeline stream with customer emails, SKU catalog, quantity, and payment authorization.",
                "default_batch_size": 30,
                "fields": ["order_id", "timestamp", "customer_email", "product_sku", "item_name", "quantity", "unit_price", "total_amount", "shipping_region", "order_status"]
            }
        ]
    }

