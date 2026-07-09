#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local video creation - MoviePy plus supporting utilities
"""

import logging
import os
import tempfile
import requests
from typing import Dict, List, Optional, Tuple
from google.cloud import storage
import config


logger = logging.getLogger(__name__)


class VideoCreator:
    """Manages local video creation"""
    
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
        logger.info("Video Creator ready")
    
    def create_local_video(self, row_data: Dict) -> Optional[str]:
        """Create a local video (when needed)"""
        try:
            logger.info(f"Creating local video for row {row_data['row_number']}")
            
            # Check whether a local video is needed
            if not self._needs_local_creation(row_data):
                logger.info("No local video needed - using ZapCap")
                return None
            
            # Local video creation logic goes here
            # using MoviePy or other tools
            
            logger.info("Local video creation - planned for a future version")
            return None
            
        except Exception as e:
            logger.error(f"Local video creation error: {e}")
            return None
    
    def _needs_local_creation(self, row_data: Dict) -> bool:
        """Check whether a local video is required"""
        # Currently everything goes through ZapCap
        return False
    
    def download_file(self, url: str, local_path: str) -> bool:
        """Download a file from the web"""
        try:
            response = requests.get(url, timeout=60)
            
            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                logger.error(f"File download error: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"File download error: {e}")
            return False
    
    def upload_to_bucket(self, local_path: str, bucket_path: str) -> bool:
        """Upload a file to the bucket"""
        try:
            client = storage.Client.from_service_account_json('service_account.json')
            bucket = client.bucket(config.GCS_BUCKET_NAME)
            blob = bucket.blob(bucket_path)
            
            blob.upload_from_filename(local_path)
            blob.make_public()
            
            logger.info(f"File uploaded to bucket: {bucket_path}")
            return True
            
        except Exception as e:
            logger.error(f"Bucket upload error: {e}")
            return False
    
    def get_file_info(self, file_path: str) -> Dict:
        """Get file metadata"""
        try:
            if not os.path.exists(file_path):
                return {'exists': False}
            
            stat = os.stat(file_path)
            
            return {
                'exists': True,
                'size': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'extension': os.path.splitext(file_path)[1].lower()
            }
            
        except Exception as e:
            logger.error(f"Error reading file metadata: {e}")
            return {'exists': False, 'error': str(e)}
    
    def is_video_file(self, file_path: str) -> bool:
        """Check whether a file is a video"""
        try:
            video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']
            extension = os.path.splitext(file_path)[1].lower()
            return extension in video_extensions
            
        except Exception as e:
            return False
    
    def is_image_file(self, file_path: str) -> bool:
        """Check whether a file is an image"""
        try:
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
            extension = os.path.splitext(file_path)[1].lower()
            
            # Extra validation via magic bytes (when the file exists)
            if os.path.exists(file_path):
                return self._check_image_magic_bytes(file_path)
            
            return extension in image_extensions
            
        except Exception as e:
            return False
    
    def _check_image_magic_bytes(self, file_path: str) -> bool:
        """Validate image magic bytes"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(12)
            
            # Magic bytes for common formats
            image_signatures = [
                b'\xFF\xD8\xFF',  # JPEG
                b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A',  # PNG
                b'\x47\x49\x46\x38',  # GIF
                b'\x42\x4D',  # BMP
                b'\x52\x49\x46\x46',  # WEBP (RIFF)
            ]
            
            for signature in image_signatures:
                if header.startswith(signature):
                    return True
            
            return False
            
        except Exception as e:
            return False
    
    def cleanup_temp_files(self, file_paths: List[str]):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Removed temp file: {file_path}")
            except Exception as e:
                logger.warning(f"Could not remove temp file {file_path}: {e}")
    
    def get_temp_file_path(self, suffix: str = ".tmp") -> str:
        """Build a temp file path"""
        return tempfile.mktemp(suffix=suffix, dir=self.temp_dir)
    
    def validate_video_urls(self, urls: List[str]) -> List[str]:
        """Validate a list of video URLs"""
        valid_urls = []
        
        for url in urls:
            if self._is_valid_video_url(url):
                valid_urls.append(url)
            else:
                logger.warning(f"Invalid video URL: {url}")
        
        return valid_urls
    
    def _is_valid_video_url(self, url: str) -> bool:
        """Validate a single video URL"""
        try:
            if not url or not url.strip():
                return False
            
            url = url.strip()
            
            # Basic URL sanity check
            if not url.startswith(('http://', 'https://')):
                return False
            
            # HEAD request check
            response = requests.head(url, timeout=10)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                return any(video_type in content_type for video_type in 
                          ['video/', 'application/octet-stream'])
            
            return False
            
        except Exception as e:
            return False 