"""
S3 Upload Service
Handles uploading frontend artifacts to S3 and syncing to CloudFront
"""
import boto3
import zipfile
import tempfile
import os
from pathlib import Path
from typing import Dict, Optional, Any, Callable
from botocore.exceptions import ClientError


class S3UploadService:
    """Service for uploading frontend artifacts to S3"""
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize S3 upload service
        
        Args:
            credentials: Optional AWS credentials dict
        """
        self.credentials = credentials or {}
    
    def _get_client(self, service: str, region: str) -> Any:
        """Get boto3 client with credentials"""
        return boto3.client(service, region_name=region, **self.credentials)
    
    def download_from_s3(self, s3_uri: str, local_path: str, 
                        callback: Optional[Callable] = None) -> bool:
        """
        Download file from S3
        
        Args:
            s3_uri: S3 URI (s3://bucket/key)
            local_path: Local file path to save to
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        try:
            # Parse S3 URI
            s3_uri_clean = s3_uri.replace("s3://", "")
            parts = s3_uri_clean.split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            
            # Determine region from bucket
            s3_client = self._get_client('s3', 'us-east-1')
            
            try:
                bucket_location = s3_client.get_bucket_location(Bucket=bucket)
                region = bucket_location['LocationConstraint'] or 'us-east-1'
            except:
                region = 'us-east-1'
            
            # Get client for correct region
            s3_client = self._get_client('s3', region)
            
            # Download file
            if callback:
                callback(f"Downloading from {s3_uri}...")
            
            s3_client.download_file(bucket, key, local_path)
            
            if callback:
                callback(f"Downloaded to {local_path}")
            
            return True
            
        except ClientError as e:
            if callback:
                callback(f"Error downloading from S3: {str(e)}")
            return False
        except Exception as e:
            if callback:
                callback(f"Error: {str(e)}")
            return False
    
    def extract_zip(self, zip_path: str, extract_to: str,
                   callback: Optional[Callable] = None) -> bool:
        """
        Extract ZIP file
        
        Args:
            zip_path: Path to ZIP file
            extract_to: Directory to extract to
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        try:
            if callback:
                callback(f"Extracting {zip_path}...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            
            if callback:
                callback(f"Extracted to {extract_to}")
            
            return True
            
        except Exception as e:
            if callback:
                callback(f"Error extracting ZIP: {str(e)}")
            return False
    
    def upload_directory_to_s3(self, local_dir: str, bucket: str, prefix: str = "",
                               region: str = 'us-east-1',
                               callback: Optional[Callable] = None) -> bool:
        """
        Upload directory contents to S3
        
        Args:
            local_dir: Local directory path
            bucket: S3 bucket name
            prefix: S3 key prefix
            region: AWS region
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        try:
            s3_client = self._get_client('s3', region)
            
            local_path = Path(local_dir)
            files_uploaded = 0
            
            # Walk through directory
            for file_path in local_path.rglob('*'):
                if file_path.is_file():
                    # Calculate relative path
                    relative_path = file_path.relative_to(local_path)
                    s3_key = str(Path(prefix) / relative_path).replace('\\', '/')
                    
                    # Determine content type
                    content_type = self._get_content_type(str(file_path))
                    
                    # Upload file
                    extra_args = {'ContentType': content_type}
                    
                    if callback:
                        callback(f"Uploading {relative_path}...")
                    
                    s3_client.upload_file(
                        str(file_path),
                        bucket,
                        s3_key,
                        ExtraArgs=extra_args
                    )
                    
                    files_uploaded += 1
            
            if callback:
                callback(f"Uploaded {files_uploaded} files to s3://{bucket}/{prefix}")
            
            return True
            
        except ClientError as e:
            if callback:
                callback(f"Error uploading to S3: {str(e)}")
            return False
        except Exception as e:
            if callback:
                callback(f"Error: {str(e)}")
            return False
    
    def _get_content_type(self, file_path: str) -> str:
        """Get content type for file"""
        extension_map = {
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
            '.ttf': 'font/ttf',
            '.eot': 'application/vnd.ms-fontobject',
        }
        
        ext = Path(file_path).suffix.lower()
        return extension_map.get(ext, 'application/octet-stream')
    
    def invalidate_cloudfront(self, distribution_id: str, paths: list = ['/*'],
                             region: str = 'us-east-1',
                             callback: Optional[Callable] = None) -> bool:
        """
        Create CloudFront invalidation
        
        Args:
            distribution_id: CloudFront distribution ID
            paths: List of paths to invalidate
            region: AWS region
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        try:
            cf_client = self._get_client('cloudfront', region)
            
            if callback:
                callback(f"Creating CloudFront invalidation for {distribution_id}...")
            
            import time
            caller_reference = f"deployment-{int(time.time())}"
            
            response = cf_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    'Paths': {
                        'Quantity': len(paths),
                        'Items': paths
                    },
                    'CallerReference': caller_reference
                }
            )
            
            invalidation_id = response['Invalidation']['Id']
            
            if callback:
                callback(f"Invalidation created: {invalidation_id}")
            
            return True
            
        except ClientError as e:
            if callback:
                callback(f"Error creating invalidation: {str(e)}")
            return False
        except Exception as e:
            if callback:
                callback(f"Error: {str(e)}")
            return False
    
    def deploy_frontend_artifact(self, s3_source_uri: str, target_bucket: str,
                                 distribution_id: Optional[str] = None,
                                 region: str = 'us-east-1',
                                 callback: Optional[Callable] = None) -> bool:
        """
        Complete frontend deployment workflow
        
        Args:
            s3_source_uri: Source S3 URI for ZIP file
            target_bucket: Target S3 bucket for deployment
            distribution_id: Optional CloudFront distribution ID
            region: AWS region
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        temp_dir = None
        temp_zip = None
        
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            temp_zip = os.path.join(temp_dir, 'frontend.zip')
            extract_dir = os.path.join(temp_dir, 'extracted')
            os.makedirs(extract_dir)
            
            # Download ZIP from source S3
            if not self.download_from_s3(s3_source_uri, temp_zip, callback):
                return False
            
            # Extract ZIP
            if not self.extract_zip(temp_zip, extract_dir, callback):
                return False
            
            # Upload to target S3 bucket
            if not self.upload_directory_to_s3(extract_dir, target_bucket, '', region, callback):
                return False
            
            # Invalidate CloudFront if distribution ID provided
            if distribution_id:
                if not self.invalidate_cloudfront(distribution_id, ['/*'], region, callback):
                    if callback:
                        callback("Warning: CloudFront invalidation failed, but deployment succeeded")
            
            return True
            
        except Exception as e:
            if callback:
                callback(f"Frontend deployment failed: {str(e)}")
            return False
        finally:
            # Cleanup temp files
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
