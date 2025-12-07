from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List

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
