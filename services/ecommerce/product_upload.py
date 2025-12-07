"""
Product Upload Service - Handles streamer/seller product uploads with images.

Flow:
1. Receive product data (SKU, name, description, price, stock) + image files
2. Upload images to MinIO
3. Send images to Vision service for model description generation
4. Store product metadata + image URLs + model description in Supabase
"""

import os
import json
import logging
import httpx
import asyncio
from typing import List, Optional
from datetime import datetime
from io import BytesIO

import aiofiles
from fastapi import UploadFile, HTTPException
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

# MinIO Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "tiktoksales-products")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "False").lower() == "true"

# Vision Service Configuration
VISION_SERVICE_URL = os.getenv("VISION_SERVICE_URL", "http://vision-service:8002")

# Initialize MinIO client
try:
    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL
    )
    logger.info(f"MinIO client initialized: {MINIO_ENDPOINT}")
except Exception as e:
    logger.warning(f"Failed to initialize MinIO: {e}")
    minio_client = None


async def ensure_bucket_exists():
    """Ensure MinIO bucket exists."""
    if not minio_client:
        logger.warning("MinIO client not available")
        return False
    
    try:
        exists = minio_client.bucket_exists(MINIO_BUCKET)
        if not exists:
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"Created MinIO bucket: {MINIO_BUCKET}")
        else:
            logger.info(f"MinIO bucket already exists: {MINIO_BUCKET}")
        return True
    except Exception as e:
        logger.error(f"Failed to ensure bucket: {e}")
        return False


async def upload_image_to_minio(
    file: UploadFile,
    streamer: str,
    product_sku: str
) -> dict:
    """
    Upload image to MinIO and return URL info.
    
    Args:
        file: UploadFile from FastAPI
        streamer: Streamer username
        product_sku: Product SKU
    
    Returns:
        Dict with {url, filename, size, uploaded_at}
    """
    if not minio_client:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")
    
    try:
        # Ensure bucket exists
        if not await ensure_bucket_exists():
            raise HTTPException(status_code=503, detail="Failed to access MinIO bucket")
        
        # Generate object name
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        object_name = f"{streamer}/{product_sku}/{timestamp}_{file.filename}"
        
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Upload to MinIO
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=object_name,
            data=BytesIO(content),
            length=file_size,
            content_type=file.content_type or "application/octet-stream"
        )
        
        # Generate URL
        url = f"minio://{MINIO_BUCKET}/{object_name}"
        
        logger.info(f"Uploaded image to MinIO: {object_name} ({file_size} bytes)")
        
        return {
            "url": url,
            "filename": file.filename,
            "size": file_size,
            "uploaded_at": datetime.utcnow().isoformat(),
            "minio_object": object_name
        }
    
    except S3Error as e:
        logger.error(f"MinIO S3 error: {e}")
        raise HTTPException(status_code=500, detail=f"MinIO upload failed: {e}")
    except Exception as e:
        logger.error(f"Failed to upload image: {e}")
        raise HTTPException(status_code=500, detail=f"Image upload failed: {e}")


async def get_model_description_from_vision(
    image_urls: List[str],
    streamer: str,
    product_name: str
) -> dict:
    """
    Call Vision service to analyze product images.
    
    Args:
        image_urls: List of image URLs
        streamer: Streamer username
        product_name: Product name for context
    
    Returns:
        Dict with tag and model_description from CNN analysis
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "streamer": streamer,
                "product_name": product_name,
                "frame_urls": image_urls,
            }

            response = await client.post(f"{VISION_SERVICE_URL}/analyze_product", json=payload)

            if response.status_code != 200:
                logger.warning(f"Vision service returned {response.status_code}")
                return {"tag": None, "model_description": "", "category": None}

            data = response.json()
            tag = data.get("tag")
            model_description = data.get("model_description", "")
            category = data.get("category")  # backwards compatibility

            logger.info(f"Got analysis from Vision: tag={tag}, description_length={len(model_description)}")
            return {"tag": tag, "model_description": model_description, "category": category}

    except Exception as e:
        logger.warning(f"Failed to get analysis from Vision: {e}")
        return {"tag": None, "model_description": "", "category": None}


async def process_product_upload(
    streamer: str,
    sku: str,
    name: str,
    user_description: str,
    price: float,
    stock: int,
    files: List[UploadFile]
) -> dict:
    """
    Complete product upload workflow.
    
    Args:
        streamer: Streamer username
        sku: Stock Keeping Unit
        name: Product name
        user_description: Description provided by streamer
        price: Product price
        stock: Stock quantity
        files: List of product image files
    
    Returns:
        Dict with product data and processing results
    """
    
    if not files:
        raise HTTPException(status_code=400, detail="At least one image is required")
    
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 images allowed")
    
    # Validate file types
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    for file in files:
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: {file.content_type}. Allowed: {allowed_types}"
            )
    
    try:
        # Upload all images to MinIO
        image_urls = []
        for file in files:
            image_info = await upload_image_to_minio(file, streamer, sku)
            image_urls.append(image_info)
        
        logger.info(f"Uploaded {len(image_urls)} images for {streamer}/{sku}")
        
        # Get tag and model_description from Vision service CNN
        url_list = [img["url"] for img in image_urls]
        vision_result = await get_model_description_from_vision(url_list, streamer, name)
        tag = vision_result.get("tag") if isinstance(vision_result, dict) else None
        model_description = vision_result.get("model_description", "") if isinstance(vision_result, dict) else ""
        category = vision_result.get("category") if isinstance(vision_result, dict) else None
        
        # Prepare product data for database
        product_data = {
            "streamer": streamer,
            "sku": sku,
            "name": name,
            "user_description": user_description,
            "tag": tag,
            "model_description": model_description,
            "category": category,
            "price": price,
            "stock": stock,
            "image_urls": json.dumps(image_urls),
            "minio_bucket": MINIO_BUCKET,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        return {
            "success": True,
            "product": product_data,
            "images_uploaded": len(image_urls),
            "model_description_generated": bool(model_description)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Product upload workflow failed: {e}")
        raise HTTPException(status_code=500, detail=f"Product upload failed: {e}")


async def get_product_by_sku(
    supabase,
    streamer: str,
    sku: str
) -> Optional[dict]:
    """Get product from database by streamer and SKU."""
    try:
        response = supabase.table("products").select("*").eq("streamer", streamer).eq("sku", sku).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to get product: {e}")
        return None


async def list_streamer_products(
    supabase,
    streamer: str,
    limit: int = 50,
    offset: int = 0
) -> List[dict]:
    """Get all products for a streamer."""
    try:
        response = supabase.table("products").select("*").eq("streamer", streamer).range(offset, offset + limit).execute()
        return response.data or []
    except Exception as e:
        logger.error(f"Failed to list products: {e}")
        return []
