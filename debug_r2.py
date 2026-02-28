import os
import django
from pathlib import Path

# Set up django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

import boto3
from django.conf import settings

from botocore.config import Config

print("Endpoint URL:", settings.AWS_S3_ENDPOINT_URL)
print("Bucket:", settings.AWS_STORAGE_BUCKET_NAME)
print("Keys configured?", bool(settings.AWS_ACCESS_KEY_ID), bool(settings.AWS_SECRET_ACCESS_KEY))

try:
    s3 = boto3.client(
        's3',
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME or 'auto',
        config=Config(s3={'addressing_style': 'path'})
    )
    
    print("Listing buckets...")
    response = s3.list_buckets()
    print("Buckets found:", [b['Name'] for b in response.get('Buckets', [])])
    
    # Try a dummy upload
    print("Uploading dummy file...")
    s3.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key='test_connection.txt',
        Body=b'Connected successfully',
        ContentType='text/plain'
    )
    print("Upload successful!")
except Exception as e:
    print("ERROR DURING BOTO3 TEST:", getattr(e, 'message', str(e)))
