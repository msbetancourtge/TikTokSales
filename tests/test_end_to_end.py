import os
import asyncio
import json
import httpx
import uuid
import pytest
from pathlib import Path

# Run these tests against locally running services started by docker compose
ECOM_URL = os.getenv("E_COMMERCE_TEST_URL", "http://localhost:8082")
VISION_URL = os.getenv("VISION_TEST_URL", "http://localhost:8002")

pytestmark = pytest.mark.asyncio

async def fetch_placeholder_frame(streamer: str = "test_streamer") -> bytes:
    url = f"{VISION_URL}/capture_frame?streamer={streamer}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

async def analyze_product(name: str, streamer: str = "test_streamer") -> dict:
    url = f"{VISION_URL}/analyze_product"
    payload = {"streamer": streamer, "product_name": name, "frame_urls": ["minio://dummy/1.png"]}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

async def upload_product(image_bytes: bytes, filename: str = "frame.png", sku: str = None) -> httpx.Response:
    url = f"{ECOM_URL}/products/upload"
    # Build multipart form data
    files = {"files": (filename, image_bytes, "image/png")}
    data = {
        "streamer": "test_streamer",
        "sku": sku or f"e2e-{uuid.uuid4().hex[:8]}",
        "name": "E2E Test Product",
        "user_description": "Uploaded by integration test",
        "price": "9.99",
        "stock": "10",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, data=data, files=files)
        return r

async def query_supabase_products(sku: str, streamer: str) -> dict:
    # Use SUPABASE env variables if present; otherwise skip
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {}

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/products?select=*&sku=eq.{sku}&streamer=eq.{streamer}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data[0] if data else {}

async def test_capture_and_analyze():
    frame = await fetch_placeholder_frame("e2e_streamer")
    assert frame and len(frame) > 0

    analysis = await analyze_product("Fancy Shoes", streamer="e2e_streamer")
    assert "description" in analysis
    assert "category" in analysis

async def test_upload_product_and_db_store():
    # Fetch an example frame from vision capture endpoint
    frame = await fetch_placeholder_frame("e2e_streamer")
    assert frame and len(frame) > 0

    # Upload product to ecommerce with a unique SKU
    unique_sku = f"e2e-{uuid.uuid4().hex[:8]}"
    resp = await upload_product(frame, filename="e2e_frame.png", sku=unique_sku)
    assert resp.status_code in (200, 201), f"Upload failed: {resp.status_code} {resp.text}"

    # If Supabase is configured, check product stored with category
    product = await query_supabase_products(unique_sku, "test_streamer")
    # If supabase not configured, product will be empty; assert when present
    if product:
        assert product.get("sku") == "e2e-sku-123"
        # category may be null if vision didn't produce it, but ensure field exists
        assert "category" in product

if __name__ == "__main__":
    asyncio.run(test_capture_and_analyze())
import asyncio
import json
import httpx
import uuid
import pytest
from pathlib import Path

# Run these tests against locally running services started by docker compose
ECOM_URL = os.getenv("E_COMMERCE_TEST_URL", "http://localhost:8082")
VISION_URL = os.getenv("VISION_TEST_URL", "http://localhost:8002")

pytestmark = pytest.mark.asyncio


async def fetch_placeholder_frame(streamer: str = "test_streamer") -> bytes:
    url = f"{VISION_URL}/capture_frame?streamer={streamer}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def analyze_product(name: str, streamer: str = "test_streamer") -> dict:
    url = f"{VISION_URL}/analyze_product"
    payload = {"streamer": streamer, "product_name": name, "frame_urls": ["minio://dummy/1.png"]}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


async def upload_product(image_bytes: bytes, filename: str = "frame.png", sku: str = None) -> httpx.Response:
    url = f"{ECOM_URL}/products/upload"
    # Build multipart form data
    files = {"files": (filename, image_bytes, "image/png")}
    data = {
        "streamer": "test_streamer",
        "sku": sku or f"e2e-{uuid.uuid4().hex[:8]}",
        "name": "E2E Test Product",
        "user_description": "Uploaded by integration test",
        "price": "9.99",
        "stock": "10",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, data=data, files=files)
        return r


async def query_supabase_products(sku: str, streamer: str) -> dict:
    # Use SUPABASE env variables if present; otherwise skip
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {}

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/products?select=*&sku=eq.{sku}&streamer=eq.{streamer}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data[0] if data else {}


async def test_capture_and_analyze():
    frame = await fetch_placeholder_frame("e2e_streamer")
    assert frame and len(frame) > 0

    analysis = await analyze_product("Fancy Shoes", streamer="e2e_streamer")
    assert "description" in analysis
    assert "category" in analysis


async def test_upload_product_and_db_store():
    # Fetch an example frame from vision capture endpoint
    frame = await fetch_placeholder_frame("e2e_streamer")
    assert frame and len(frame) > 0

    # Upload product to ecommerce with a unique SKU
    unique_sku = f"e2e-{uuid.uuid4().hex[:8]}"
    resp = await upload_product(frame, filename="e2e_frame.png", sku=unique_sku)
    assert resp.status_code in (200, 201), f"Upload failed: {resp.status_code} {resp.text}"

    # If Supabase is configured, check product stored with category
    product = await query_supabase_products(unique_sku, "test_streamer")
    # If supabase not configured, product will be empty; assert when present
    if product:
        assert product.get("sku") == "e2e-sku-123"
        # category may be null if vision didn't produce it, but ensure field exists
        assert "category" in product


if __name__ == "__main__":
    asyncio.run(test_capture_and_analyze())
