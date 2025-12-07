#!/usr/bin/env python3
"""
Quick script to set public read policy on MinIO bucket.
Run this once to make the bucket publicly readable.

Usage:
    python set_minio_public.py
"""

from minio import Minio

# Update these with your MinIO credentials
MINIO_ENDPOINT = "72.61.76.44:9000"
MINIO_ACCESS_KEY = "minio"
MINIO_SECRET_KEY = "minio123"
MINIO_BUCKET = "tiktoksales-products"

PUBLIC_READ_POLICY = '''{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::%s/*"]
        }
    ]
}'''

def main():
    print(f"Connecting to MinIO at {MINIO_ENDPOINT}...")
    
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )
    
    # Check if bucket exists
    if not client.bucket_exists(MINIO_BUCKET):
        print(f"Creating bucket: {MINIO_BUCKET}")
        client.make_bucket(MINIO_BUCKET)
    else:
        print(f"Bucket exists: {MINIO_BUCKET}")
    
    # Set public read policy
    policy = PUBLIC_READ_POLICY % MINIO_BUCKET
    print(f"Setting public read policy on {MINIO_BUCKET}...")
    client.set_bucket_policy(MINIO_BUCKET, policy)
    
    print("✅ Done! Bucket is now publicly readable.")
    print(f"   Test URL: http://{MINIO_ENDPOINT}/{MINIO_BUCKET}/")

if __name__ == "__main__":
    main()
