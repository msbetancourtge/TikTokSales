from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional

app = FastAPI()

# Add CORS middleware with restricted origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class TextPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    
    @validator('text')
    def text_must_not_be_empty(cls, v):
        if not v or v.isspace():
            raise ValueError('text cannot be empty or whitespace only')
        return v.strip()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/predict_intent")
def predict(payload: TextPayload):
    try:
        text = payload.text.lower()
        keywords = ["lo quiero","comprar","me interesa","cómo lo pago","quiero comprar","quiero"]
        score = 0.0
        for k in keywords:
            if k in text:
                score = 0.95
                break
        intent = "buy" if score > 0.5 else "none"
        return {"intent": intent, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
