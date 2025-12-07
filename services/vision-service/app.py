from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List
import io
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

app = FastAPI()

# Add CORS middleware with restricted origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class FramePayload(BaseModel):
    frame_urls: List[str] = Field(..., min_items=1, max_items=100)
    
    @validator('frame_urls', each_item=True)
    def validate_url(cls, v):
        if not v or not isinstance(v, str) or len(v) > 2000:
            raise ValueError('Invalid URL format')
        return v

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/match_product")
def match(payload: FramePayload):
    try:
        # placeholder matching: always returns None / demo product
        # later: compute embeddings and nearest neighbour to products
        return {"productId": None, "score": 0.0}
    except Exception as e:
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
