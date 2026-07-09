#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapCap management - a simple, reliable ZapCap API wrapper
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


class ZapCapManager:
    """ZapCap manager - straightforward video-task lifecycle handling"""
    
    def __init__(self):
        self.api_key = config.ZAPCAP_API_KEY
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        self.sheets = None  # injected from outside
        
        # Tuned timeouts
        self.create_timeout = 30  # seconds for task creation
        self.check_timeout = 10   # seconds for a status check
        self.max_wait_time = 3600  # max one hour waiting for a task
        
        logger.info("ZapCap Manager ready")
    
    def set_sheets_manager(self, sheets: SheetsManager):
        """Attach the sheets manager"""
        self.sheets = sheets
    
    def create_video(self, row_data: Dict) -> Optional[str]:
        """Create a ZapCap video task"""
        try:
            logger.info(f"Creating video for row {row_data['row_number']}")
            
            # Build the request payload
            request_data = self._prepare_video_request(row_data)
            
            if not request_data:
                logger.error("Could not build the request payload")
                return None
            
            # Send the request to ZapCap
            response = requests.post(
                "https://api.zapcap.ai/generate", 
                json=request_data,
                headers=self.headers,
                timeout=self.create_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                task_id = data.get('taskId') or data.get('id') or data.get('task_id')
                
                if task_id:
                    logger.info(f"Task created: {task_id}")
                    return task_id
                else:
                    logger.error(f"No Task ID in the response: {data}")
                    return None
                    
            else:
                logger.error(f"Video creation error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Video creation error: {e}")
            return None
    
    def _prepare_video_request(self, row_data: Dict) -> Optional[Dict]:
        """Build the ZapCap request payload"""
        try:
            # Base fields
            script = row_data.get('script', '').strip()
            voice = row_data.get('voice', '').strip()
            template = row_data.get('zapcap_template', '').strip()
            
            if not script:
                logger.error("Row has no script")
                return None
            
            # Base request
            request_data = {
                "text": script,
                "voice": voice or "default",
                "template": template or "default"
            }
            
            # Optional parameters when present
            if row_data.get('vo_gender'):
                request_data["voiceGender"] = row_data['vo_gender']
            
            if row_data.get('zoom_in'):
                zoom_value = str(row_data['zoom_in']).lower()
                request_data["zoom"] = zoom_value in ['yes', 'true', '1']
            
            if row_data.get('size'):
                request_data["size"] = row_data['size']
            
            return request_data
            
        except Exception as e:
            logger.error(f"Request build error: {e}")
            return None
    
    def check_task_status(self, task_id: str) -> Dict:
        """Check a task status"""
        try:
            # Try several endpoints
            endpoints = [
                f"https://api.zapcap.ai/task/{task_id}",
                f"https://api.zapcap.ai/tasks/{task_id}",
                f"https://api.zapcap.ai/v1/task/{task_id}"
            ]
            
            for endpoint in endpoints:
                try:
                    response = requests.get(
                        endpoint, 
                        headers=self.headers, 
                        timeout=self.check_timeout
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        status = str(data.get('status', '')).lower()
                        
                        if status == 'completed':
                            video_url = (data.get('downloadUrl') or 
                                       data.get('videoUrl') or 
                                       data.get('url') or 
                                       data.get('download_url'))
                            
                            return {
                                'status': 'completed',
                                'video_url': video_url,
                                'data': data
                            }
                            
                        elif status in ['processing', 'pending', 'transcribing', 'rendering']:
                            return {'status': 'processing', 'data': data}
                            
                        elif status == 'failed':
                            return {'status': 'failed', 'data': data}
                            
                        else:
                            return {'status': status, 'data': data}
                            
                    elif response.status_code == 404:
                        continue  # try the next endpoint
                        
                    elif response.status_code == 403:
                        return {'status': 'forbidden', 'data': None}
                        
                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout on {endpoint}")
                    continue
                    
                except Exception as e:
                    logger.warning(f"Error on {endpoint}: {e}")
                    continue
            
            return {'status': 'not_found', 'data': None}
            
        except Exception as e:
            logger.error(f"Status check error: {e}")
            return {'status': 'error', 'data': None}
    
    def monitor_all_pending_tasks(self):
        """Track all pending tasks"""
        if not self.sheets:
            logger.error("No sheets manager - cannot track tasks")
            return
        
        logger.info("Checking all pending tasks...")
        
        pending_tasks = self.sheets.get_pending_zapcap_tasks()
        
        if not pending_tasks:
            logger.info("No pending ZapCap tasks")
            return
        
        logger.info(f"Found {len(pending_tasks)} pending tasks")
        
        completed_count = 0
        failed_count = 0
        still_processing = 0
        
        for task_data in pending_tasks:
            task_id = task_data.get('zapcap_task_id', '').strip()
            row_number = task_data['row_number']
            name = task_data.get('name', f'Row_{row_number}')
            
            logger.info(f"Checking task {task_id[:12]}... (row {row_number})")
            
            status_result = self.check_task_status(task_id)
            
            if status_result['status'] == 'completed' and status_result.get('video_url'):
                logger.info("Completed! Downloading and uploading to the bucket...")
                
                success = self._download_and_upload_video(
                    status_result['video_url'], 
                    name
                )
                
                if success:
                    # Complete the row in the sheet
                    final_url = f"https://storage.googleapis.com/{config.GCS_BUCKET_NAME}/videos/{name}.mp4"
                    self.sheets.complete_row(row_number, final_url)
                    completed_count += 1
                else:
                    self.sheets.update_status(row_number, "ZapCap completed but upload failed")
                    
            elif status_result['status'] in ['failed', 'forbidden']:
                logger.error(f"Task failed: {status_result['status']}")
                self.sheets.clear_zapcap_task_id(row_number, f"Failed: {status_result['status']}")
                failed_count += 1
                
            elif status_result['status'] == 'not_found':
                logger.warning("Task not found")
                self.sheets.clear_zapcap_task_id(row_number, "Task not found")
                failed_count += 1
                
            elif status_result['status'] == 'processing':
                logger.info("Still processing...")
                self.sheets.update_status(row_number, "ZapCap processing...")
                still_processing += 1
                
            else:
                logger.info(f"Unclear status: {status_result['status']}")
                self.sheets.update_status(row_number, f"Unknown status: {status_result['status']}")
                still_processing += 1
            
            time.sleep(1)  # pause between checks
        
        # Summary
        logger.info(f"Tracking summary:")
        logger.info(f"Completed: {completed_count}")
        logger.error(f"Failed: {failed_count}")
        logger.info(f"Still processing: {still_processing}")
    
    def clean_failed_tasks(self) -> int:
        """Clear failed tasks"""
        if not self.sheets:
            logger.error("No sheets manager")
            return 0
        
        logger.info("Clearing failed tasks...")
        
        pending_tasks = self.sheets.get_pending_zapcap_tasks()
        failed_count = 0
        
        for task_data in pending_tasks:
            task_id = task_data.get('zapcap_task_id', '').strip()
            row_number = task_data['row_number']
            
            status_result = self.check_task_status(task_id)
            
            if status_result['status'] in ['failed', 'forbidden', 'not_found', 'error']:
                logger.info(f"Clearing failed task on row {row_number}: {status_result['status']}")
                self.sheets.clear_zapcap_task_id(row_number, f"Cleaned: {status_result['status']}")
                failed_count += 1
                
            time.sleep(0.5)
        
        return failed_count
    
    def _download_and_upload_video(self, video_url: str, file_name: str) -> bool:
        """Download the video from ZapCap and upload it to the bucket"""
        temp_file_path = None
        
        try:
            # Download the video
            logger.info(f"Downloading video...")
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
            blob = bucket.blob(f"videos/{file_name}.mp4")
            
            blob.upload_from_filename(temp_file_path)
            blob.make_public()
            
            logger.info(f"Uploaded successfully: {file_name}.mp4")
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
    
    def wait_for_task_completion(self, task_id: str, max_wait_minutes: int = 60) -> Dict:
        """Wait for a task to complete"""
        logger.info(f"Waiting for task {task_id[:12]}... (max {max_wait_minutes} minutes)")
        
        start_time = time.time()
        max_wait_seconds = max_wait_minutes * 60
        check_interval = 30  # check every 30 seconds
        
        while time.time() - start_time < max_wait_seconds:
            status_result = self.check_task_status(task_id)
            
            if status_result['status'] == 'completed':
                logger.info(f"Task completed!")
                return status_result
                
            elif status_result['status'] in ['failed', 'forbidden', 'not_found']:
                logger.error(f"Task failed: {status_result['status']}")
                return status_result
                
            elif status_result['status'] == 'processing':
                elapsed_minutes = (time.time() - start_time) / 60
                logger.info(f"Still processing... ({elapsed_minutes:.1f} minutes)")
                
            time.sleep(check_interval)
        
        logger.warning(f"Timed out - still processing after {max_wait_minutes} minutes")
        return {'status': 'timeout', 'data': None} 