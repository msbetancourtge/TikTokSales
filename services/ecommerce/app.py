"""
Ecommerce Service: Handles payments (Stripe), SMS (Twilio), WhatsApp, and product uploads.
"""
import os
import logging
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator, EmailStr, ConfigDict

from db import initialize_supabase, get_supabase_client
from product_upload import process_product_upload, get_product_by_sku, list_streamer_products

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Ecommerce Service",
    description="E-commerce backend with Stripe, Twilio, and WhatsApp integration",
    version="1.0.0"
)

# CORS configuration - open for MVP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables (from Stripe, Twilio, etc.)
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
WHATSAPP_PHONE_NUMBER = os.getenv("WHATSAPP_PHONE_NUMBER", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Initialize Supabase on startup
db_initialized = False


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global db_initialized
    db_initialized = initialize_supabase()
    if db_initialized:
        logger.info("Ecommerce service started with Supabase connected")
    else:
        logger.info("Ecommerce service started (Supabase offline)")



class Product(BaseModel):
    """Product model."""
    id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=500)
    price: float = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    description: Optional[str] = None


class OrderItem(BaseModel):
    """Order item model."""
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=1000)
    price: float = Field(..., gt=0)


class PaymentRequest(BaseModel):
    """Payment request model."""
    order_id: str = Field(..., min_length=1, max_length=255)
    user_id: str = Field(..., min_length=1, max_length=255)
    items: List[OrderItem]
    total_amount: float = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    customer_email: Optional[str] = None
    
    @validator('total_amount')
    def validate_total(cls, v):
        if v < 0.01:
            raise ValueError('total_amount must be at least 0.01')
        return v


class PaymentResponse(BaseModel):
    """Payment response model."""
    payment_id: str
    order_id: str
    status: str  # pending, completed, failed
    amount: float
    currency: str
    message: str


class SMSRequest(BaseModel):
    """SMS notification request."""
    phone_number: str = Field(..., min_length=10, max_length=15)
    message: str = Field(..., min_length=1, max_length=1000)
    
    @validator('message')
    def message_not_empty(cls, v):
        if not v or v.isspace():
            raise ValueError('message cannot be empty')
        return v.strip()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    service: str = "ecommerce"


class ProductUploadResponse(BaseModel):
    """Product upload response."""
    model_config = ConfigDict(protected_namespaces=())
    
    product_id: str
    sku: str
    name: str
    streamer: str
    price: float
    stock: int
    images_uploaded: int
    model_description_generated: bool
    message: str


class ProductDetailsResponse(BaseModel):
    """Product details response."""
    model_config = ConfigDict(protected_namespaces=())
    
    id: int
    sku: str
    streamer: str
    name: str
    user_description: Optional[str]
    tag: Optional[str]
    model_description: Optional[str]
    price: float
    stock: int
    image_urls: Optional[str]
    created_at: str


class ProductListResponse(BaseModel):
    """Product list response."""
    streamer: str
    total: int
    products: List[ProductDetailsResponse]


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", service="ecommerce")


@app.post("/products/upload", response_model=ProductUploadResponse)
async def upload_product(
    streamer: str = Form(..., min_length=1, max_length=255),
    sku: str = Form(..., min_length=1, max_length=50),
    name: str = Form(..., min_length=1, max_length=255),
    user_description: str = Form(..., min_length=1, max_length=2000),
    price: float = Form(..., gt=0),
    stock: int = Form(..., ge=0, le=100000),
    files: List[UploadFile] = File(...)
):
    """
    Upload a new product with images.
    
    Args:
        streamer: Streamer/seller username
        sku: Stock Keeping Unit (unique per streamer)
        name: Product name
        user_description: Product description from streamer
        price: Product price
        stock: Available stock quantity
        files: Product images (JPEG, PNG, WebP, GIF)
    
    Returns:
        ProductUploadResponse with upload status
    """
    try:
        if not db_initialized:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Process product upload (MinIO + Vision)
        result = await process_product_upload(
            streamer=streamer,
            sku=sku,
            name=name,
            user_description=user_description,
            price=price,
            stock=stock,
            files=files
        )
        
        # Insert into Supabase
        supabase = get_supabase_client()
        product_data = result["product"]
        
        response = supabase.table("products").insert({
            "streamer": product_data["streamer"],
            "sku": product_data["sku"],
            "name": product_data["name"],
            "user_description": product_data["user_description"],
            "tag": product_data.get("tag"),
            "model_description": product_data.get("model_description"),
            "category": product_data.get("category"),
            "price": product_data["price"],
            "stock": product_data["stock"],
            "image_urls": product_data["image_urls"],
            "minio_bucket": product_data["minio_bucket"]
        }).execute()
        
        if response.data and len(response.data) > 0:
            product_id = response.data[0]["id"]
            logger.info(f"Product created: {streamer}/{sku} (ID: {product_id})")
            
            return ProductUploadResponse(
                product_id=str(product_id),
                sku=sku,
                name=name,
                streamer=streamer,
                price=price,
                stock=stock,
                images_uploaded=result["images_uploaded"],
                model_description_generated=result["model_description_generated"],
                message=f"Product uploaded successfully with {result['images_uploaded']} images"
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to save product to database")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Product upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Product upload failed: {e}")


@app.get("/products/{streamer}/item/{sku}", response_model=ProductDetailsResponse)
async def get_product(streamer: str, sku: str):
    """
    Get product details by streamer and SKU.
    
    Args:
        streamer: Streamer username
        sku: Product SKU
    
    Returns:
        ProductDetailsResponse
    """
    try:
        if not db_initialized:
            raise HTTPException(status_code=503, detail="Database not available")
        
        supabase = get_supabase_client()
        product = await get_product_by_sku(supabase, streamer, sku)
        
        if not product:
            raise HTTPException(status_code=404, detail=f"Product not found: {streamer}/{sku}")
        
        return ProductDetailsResponse(**product)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get product: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Removed duplicate /products/streamer/{streamer} route - use /products/{streamer} instead

@app.post("/payment/process", response_model=PaymentResponse)
async def process_payment(payload: PaymentRequest):
    """
    Process a payment through Stripe.
    
    Args:
        payload: Payment request details
    
    Returns:
        PaymentResponse with payment status
    """
    try:
        if not STRIPE_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="Stripe API key not configured"
            )
        
        # Mock payment processing
        # In production, this would use Stripe SDK to create a payment intent
        payment_id = f"pay_{payload.order_id}_{payload.user_id}"
        
        # Store payment in Supabase if available
        if db_initialized:
            try:
                supabase = get_supabase_client()
                supabase.table("payments").insert({
                    "payment_id": payment_id,
                    "order_id": payload.order_id,
                    "user_id": payload.user_id,
                    "amount": payload.total_amount,
                    "currency": payload.currency,
                    "status": "completed"
                }).execute()
            except Exception as e:
                logger.warning(f"Failed to store payment in Supabase: {e}")
                # Continue anyway - DB failure shouldn't break the payment
        
        return PaymentResponse(
            payment_id=payment_id,
            order_id=payload.order_id,
            status="completed",
            amount=payload.total_amount,
            currency=payload.currency,
            message=f"Payment of {payload.currency} {payload.total_amount:.2f} processed successfully"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notify/sms")
async def send_sms(payload: SMSRequest):
    """
    Send SMS notification via Twilio.
    
    Args:
        payload: SMS details with phone number and message
    
    Returns:
        Confirmation of SMS sent
    """
    try:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            raise HTTPException(
                status_code=503,
                detail="Twilio credentials not configured"
            )
        
        # Mock SMS sending
        # In production, this would use Twilio SDK
        return {
            "status": "sent",
            "phone_number": payload.phone_number,
            "message": "SMS notification sent successfully",
            "timestamp": "2025-12-07T12:00:00Z"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notify/whatsapp")
async def send_whatsapp(payload: SMSRequest):
    """
    Send WhatsApp notification.
    
    Args:
        payload: WhatsApp message details
    
    Returns:
        Confirmation of WhatsApp message sent
    """
    try:
        if not WHATSAPP_PHONE_NUMBER:
            raise HTTPException(
                status_code=503,
                detail="WhatsApp configuration not available"
            )
        
        # Mock WhatsApp sending
        return {
            "status": "sent",
            "phone_number": payload.phone_number,
            "message": "WhatsApp message sent successfully",
            "timestamp": "2025-12-07T12:00:00Z"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/products/{streamer}")
async def list_all_products(streamer: str, limit: int = 50, offset: int = 0):
    """
    List all available products from Supabase for a specific streamer.
    
    Args:
        streamer: Streamer username
        limit: Maximum number of products (default 50)
        offset: Offset for pagination (default 0)
    
    Returns:
        List of products from database
    """
    try:
        if not db_initialized:
            raise HTTPException(status_code=503, detail="Database not available")
        
        supabase = get_supabase_client()
        query = supabase.table("products") \
            .select("id,sku,streamer,name,user_description,tag,model_description,price,stock,image_urls,category,created_at") \
            .eq("streamer", streamer)
        
        response = query.range(offset, offset + limit - 1).execute()
        
        products = []
        if response.data:
            for p in response.data:
                products.append({
                    "id": str(p.get("id")),
                    "sku": p.get("sku"),
                    "streamer": p.get("streamer"),
                    "name": p.get("name"),
                    "price": float(p.get("price", 0)),
                    "currency": "USD",
                    "description": p.get("user_description"),
                    "tag": p.get("tag"),
                    "model_description": p.get("model_description"),
                    "stock": p.get("stock", 0),
                    "image_urls": p.get("image_urls"),
                    "category": p.get("category"),
                    "created_at": p.get("created_at")
                })
        
        return {
            "total": len(products),
            "products": products
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to list products: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def service_status():
    """Get service status and configuration."""
    return {
        "service": "ecommerce",
        "version": "1.0.0",
        "database": "connected" if db_initialized else "offline",
        "stripe_configured": bool(STRIPE_API_KEY),
        "twilio_configured": bool(TWILIO_ACCOUNT_SID),
        "whatsapp_configured": bool(WHATSAPP_PHONE_NUMBER),
        "supabase_configured": bool(SUPABASE_URL)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8082,
        reload=False,
        log_level="info"
    )
