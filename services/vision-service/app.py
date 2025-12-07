from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Optional
import os
import io
import logging
from datetime import datetime
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

app = FastAPI(title="Vision Service", description="CV-based product matching from live stream frames")

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
supabase_client: Optional[Client] = None

def get_supabase_client() -> Optional[Client]:
    global supabase_client
    if supabase_client is None and SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        except Exception as e:
            logger.error(f"Failed to create Supabase client: {e}")
    return supabase_client

# Add CORS middleware - open for MVP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FramePayload(BaseModel):
    frame_urls: List[str] = Field(..., min_length=1, max_length=100)
    streamer_id: Optional[str] = None  # Optional: filter products by streamer
    
    @validator('frame_urls', each_item=True)
    def validate_url(cls, v):
        if not v or not isinstance(v, str) or len(v) > 2000:
            raise ValueError('Invalid URL format')
        return v

@app.get("/health")
def health():
    return {"ok": True, "service": "vision-service"}

@app.post("/match_product")
def match(payload: FramePayload):
    """
    Match product from frame(s) using CV model.
    
    In production: This would run a CNN to extract features from frames
    and match against product catalog embeddings.
    
    For demo: Returns the most recent product for the streamer.
    """
    try:
        logger.info(f"Matching product from {len(payload.frame_urls)} frame(s)")
        
        # Get Supabase client
        supabase = get_supabase_client()
        if not supabase:
            logger.warning("Supabase not available, returning demo product")
            return {"productId": "demo-001", "score": 0.75, "name": "Demo Product", "price": 29.99}
        
        # TODO: In production, implement actual CV matching:
        # 1. Download frame from MinIO URL
        # 2. Run CNN to extract features
        # 3. Compare with product catalog embeddings
        # 4. Return best match
        
        # For demo: Get the first available product (or filter by streamer if provided)
        try:
            query = supabase.table("products").select("id,name,price,description,image_url,streamer_id").limit(1)
            
            # If streamer_id provided, filter by it
            if payload.streamer_id:
                query = query.eq("streamer_id", payload.streamer_id)
            
            result = query.execute()
            
            if result.data and len(result.data) > 0:
                product = result.data[0]
                logger.info(f"Matched product: {product.get('id')} - {product.get('name')}")
                return {
                    "productId": str(product.get("id")),
                    "score": 0.85,  # Demo confidence score
                    "name": product.get("name"),
                    "price": product.get("price"),
                    "description": product.get("description"),
                    "image_url": product.get("image_url")
                }
            else:
                logger.info("No products found in database")
                return {"productId": None, "score": 0.0}
                
        except Exception as db_err:
            logger.error(f"Database error: {db_err}")
            return {"productId": None, "score": 0.0}
            
    except Exception as e:
        logger.error(f"Error in match_product: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/capture_frame")
def capture_frame(streamer: str = Query(..., min_length=1, max_length=255)):
    """Return a placeholder image representing a captured frame for `streamer`.

    This is a test endpoint for the worker's frame-collector. It returns a small PNG
    with the streamer name and timestamp drawn on it. In production, replace with
    real frame capture service.
    """
    try:
        # If Pillow is available, generate a simple image; otherwise return 1x1 PNG bytes
        if PIL_AVAILABLE:
            img = Image.new("RGB", (320, 180), color=(73, 109, 137))
            draw = ImageDraw.Draw(img)
            text = f"{streamer} {datetime.utcnow().strftime('%H:%M:%S')}"
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
            draw.text((10, 10), text, fill=(255, 255, 255), font=font)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(content=buf.read(), media_type="image/png")
        else:
            # Minimal 1x1 PNG binary
            one_pixel_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\nIDATx\x9cc``\x00\x00\x00\x02\x00\x01\xe2!\xbc\x33\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            return Response(content=one_pixel_png, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AnalyzePayload(BaseModel):
    streamer: str = Field(..., min_length=1)
    product_name: str = Field(..., min_length=1)
    frame_urls: List[str] = Field(default_factory=list)


@app.post("/analyze_product")
def analyze_product(payload: AnalyzePayload):
    """Simple placeholder analyzer that returns a description and category.

    In production this should run the CV model to produce a description and category.
    """
    try:
        # Placeholder heuristics: description mentions number of frames, category guesses by keywords
        desc = f"Auto description for '{payload.product_name}' using {len(payload.frame_urls)} frames."
        name_lower = payload.product_name.lower()
        if any(k in name_lower for k in ("shoe", "sneaker", "boot")):
            category = "footwear"
        elif any(k in name_lower for k in ("shirt", "tee", "jacket", "hoodie")):
            category = "apparel"
        elif any(k in name_lower for k in ("phone", "case", "charger")):
            category = "electronics"
        else:
            category = "general"

        return {"description": desc, "category": category}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
