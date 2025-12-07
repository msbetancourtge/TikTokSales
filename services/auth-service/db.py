"""
Supabase client helper for auth-service.
"""
import os
import logging
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

_client: Optional[Client] = None


def get_supabase_client() -> Client:
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials not configured for auth-service")
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    logger.info("Auth-service Supabase client initialized")
    return _client


def initialize_supabase() -> bool:
    try:
        get_supabase_client()
        return True
    except Exception as e:
        logger.error("Failed to initialize Supabase in auth-service: %s", e)
        return False
