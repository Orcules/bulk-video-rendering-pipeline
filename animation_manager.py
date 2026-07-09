#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Animation management - KLING and MINIMAX providers
"""

import logging
import requests
import time
import tempfile
import os
from typing import Dict, List, Optional
from google.cloud import storage
import config
from sheets_manager import SheetsManager


logger = logging.getLogger(__name__)


class AnimationManager:
    """Animation manager for KLING and MINIMAX"""
    
    def __init__(self):
        self.kling_api_key = config.KLING_API_KEY
        self.minimax_api_key = config.MINIMAX_API_KEY
        self.sheets = None
        
        # Wait timings
        self.create_timeout = 30
        self.check_timeout = 10
        self.max_wait_minutes = 120  # two hours per animation
        
        logger.info("Animation Manager ready")
    
    def set_sheets_manager(self, sheets: SheetsManager):
        """Attach the sheets manager"""
        self.sheets = sheets
    
    def animate_row(self, row_data: Dict) -> bool:
        """Animate the images for a row"""
        try:
            animate_value = str(row_data.get('animate_images', '')).upper()
            
            if 'KLING' in animate_value:
                return self._animate_with_kling(row_data)
            elif 'MINIMAX' in animate_value:
                return self._animate_with_minimax(row_data)
            else:
                logger.error("No suitable animation type found")
                return False
                
        except Exception as e:
            logger.error(f"Row animation error: {e}")
            return False
    
    def _animate_with_kling(self, row_data: Dict) -> bool:
        """Animate with KLING"""
        try:
            logger.info("Animating with KLING...")
            
            # Build the request payload
            request_data = self._prepare_kling_request(row_data)
            
            if not request_data:
                return False
            
            # Send the request
            headers = {
                'Authorization': f'Bearer {self.kling_api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                "https://api.kling.ai/v1/videos/text2video",
                json=request_data,
                headers=headers,
                timeout=self.create_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                task_id = data.get('data', {}).get('task_id')
                
                if task_id:
                    logger.info(f"KLING task created: {task_id}")
                    # Task tracking hook goes here
                    return True
                    
            logger.error(f"KLING error: {response.status_code} - {response.text}")
            return False
            
        except Exception as e:
            logger.error(f"KLING error: {e}")
            return False
    
    def _animate_with_minimax(self, row_data: Dict) -> bool:
        """Animate with MINIMAX"""
        try:
            logger.info("Animating with MINIMAX...")
            
            # Build the request payload
            request_data = self._prepare_minimax_request(row_data)
            
            if not request_data:
                return False
            
            # Send the request
            headers = {
                'Authorization': f'Bearer {self.minimax_api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                "https://api.minimax.chat/v1/video_generation",
                json=request_data,
                headers=headers,
                timeout=self.create_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                task_id = data.get('task_id')
                
                if task_id:
                    logger.info(f"MINIMAX task created: {task_id}")
                    return True
                    
            logger.error(f"MINIMAX error: {response.status_code} - {response.text}")
            return False
            
        except Exception as e:
            logger.error(f"MINIMAX error: {e}")
            return False
    
    def _prepare_kling_request(self, row_data: Dict) -> Optional[Dict]:
        """Build a KLING request"""
        try:
            # Validate required data
            image_urls = self._extract_image_urls(row_data)
            
            if not image_urls:
                logger.error("No images found to animate")
                return None
            
            # Build the request
            request_data = {
                "model": "kling-v1",
                "prompt": row_data.get('script', ''),
                "image": image_urls[0],  # first image
                "duration": 5,  # seconds
                "aspect_ratio": "16:9"
            }
            
            return request_data
            
        except Exception as e:
            logger.error(f"KLING request build error: {e}")
            return None
    
    def _prepare_minimax_request(self, row_data: Dict) -> Optional[Dict]:
        """Build a MINIMAX request"""
        try:
            # Validate required data
            image_urls = self._extract_image_urls(row_data)
            
            if not image_urls:
                logger.error("No images found to animate")
                return None
            
            # Build the request
            request_data = {
                "model": "video-01",
                "prompt": row_data.get('script', ''),
                "first_frame_image": image_urls[0],
                "duration": 5000  # milliseconds
            }
            
            return request_data
            
        except Exception as e:
            logger.error(f"MINIMAX request build error: {e}")
            return None
    
    def _extract_image_urls(self, row_data: Dict) -> List[str]:
        """Extract image URLs from the row"""
        try:
            image_urls = []
            
            # Find image columns
            for key, value in row_data.items():
                if 'image' in key.lower() and value and value.strip():
                    # only keep valid links
                    if value.startswith('http'):
                        image_urls.append(value.strip())
            
            return image_urls
            
        except Exception as e:
            logger.error(f"Image extraction error: {e}")
            return []
    
    def check_all_pending_animations(self):
        """Check all pending animations"""
        logger.info("Checking pending animations...")
        
        # Pending-animation polling logic goes here
        # if a tracking system like ZapCap's exists
        
        logger.info("Animation polling - planned for a future version")
    
    def check_animation_status(self, service: str, task_id: str) -> Dict:
        """Check an animation task status"""
        try:
            if service.upper() == 'KLING':
                return self._check_kling_status(task_id)
            elif service.upper() == 'MINIMAX':
                return self._check_minimax_status(task_id)
            else:
                return {'status': 'unknown_service'}
                
        except Exception as e:
            logger.error(f"Animation status check error: {e}")
            return {'status': 'error'}
    
    def _check_kling_status(self, task_id: str) -> Dict:
        """Check a KLING task status"""
        try:
            headers = {
                'Authorization': f'Bearer {self.kling_api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"https://api.kling.ai/v1/videos/{task_id}",
                headers=headers,
                timeout=self.check_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('data', {}).get('task_status', '').lower()
                
                if status == 'succeed':
                    video_url = data.get('data', {}).get('task_result', {}).get('videos', [])
                    if video_url:
                        return {'status': 'completed', 'video_url': video_url[0]}
                        
                elif status == 'failed':
                    return {'status': 'failed'}
                    
                elif status in ['processing', 'submitted']:
                    return {'status': 'processing'}
            
            return {'status': 'unknown'}
            
        except Exception as e:
            logger.error(f"KLING status check error: {e}")
            return {'status': 'error'}
    
    def _check_minimax_status(self, task_id: str) -> Dict:
        """Check a MINIMAX task status"""
        try:
            headers = {
                'Authorization': f'Bearer {self.minimax_api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"https://api.minimax.chat/v1/query/video_generation?task_id={task_id}",
                headers=headers,
                timeout=self.check_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', '').lower()
                
                if status == 'success':
                    video_url = data.get('file_id')  # or the relevant field
                    return {'status': 'completed', 'video_url': video_url}
                    
                elif status == 'failed':
                    return {'status': 'failed'}
                    
                elif status in ['processing', 'queued']:
                    return {'status': 'processing'}
            
            return {'status': 'unknown'}
            
        except Exception as e:
            logger.error(f"MINIMAX status check error: {e}")
            return {'status': 'error'}
    
    def _download_and_upload_animation(self, video_url: str, file_name: str) -> bool:
        """Download the animation and upload it to the bucket"""
        temp_file_path = None
        
        try:
            logger.info(f"Downloading animation...")
            response = requests.get(video_url, timeout=300)
            
            if response.status_code != 200:
                logger.error(f"Download error: {response.status_code}")
                return False
            
            # Save temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name
            
            logger.info(f"Uploading to bucket...")
            
            # Upload to the bucket
            client = storage.Client.from_service_account_json('service_account.json')
            bucket = client.bucket(config.GCS_BUCKET_NAME)
            blob = bucket.blob(f"animations/{file_name}.mp4")
            
            blob.upload_from_filename(temp_file_path)
            blob.make_public()
            
            logger.info(f"Animation uploaded: {file_name}.mp4")
            return True
            
        except Exception as e:
            logger.error(f"Download/upload error: {e}")
            return False
            
        finally:
            # Clean up the temp file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass 