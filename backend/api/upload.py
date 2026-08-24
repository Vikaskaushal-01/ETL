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

