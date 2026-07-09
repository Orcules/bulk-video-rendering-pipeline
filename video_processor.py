import os
import time
import logging
import requests
import cv2
import numpy as np
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import tempfile
import json
from PIL import Image
from google.cloud import storage
import uuid
import re
from datetime import datetime
import random
import math
import traceback
from oauth2client.service_account import ServiceAccountCredentials
import config
# Removed: from video_processor import VideoProcessor
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys # Import sys for stdout/stderr reconfiguration
import contextlib
import subprocess
import queue
from openai import OpenAI

# Timer context manager
@contextlib.contextmanager
def timer(tag):
    t0 = time.perf_counter()
    yield
    print(f"TIMER - {tag}: {time.perf_counter()-t0:.2f}s")

# Setting API keys
os.environ.setdefault("KLING_API_KEY", "")
os.environ.setdefault("MINIMAX_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")

# Printing the current path
print(f"\n[DEBUG] Current path: {os.getcwd()}")

# Loading environment variables
load_dotenv()
print("[DEBUG] Loading environment variables from .env...")

# Printing all critical keys
required_keys = [
    "ELEVEN_LABS_API_KEY",
    "ZAPCAP_API_KEY",
    "ZAPCAP_WEBHOOK_SECRET",
    "KLING_API_KEY",
    "MINIMAX_API_KEY",
    "GOOGLE_SHEET_ID",
    "SERVICE_ACCOUNT_EMAIL",
    "SERVICE_ACCOUNT_KEY"
]

for key in required_keys:
    print(f"[DEBUG] {key} = {os.getenv(key)}")

# Regular code continues...
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("video_processing.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout) # Keep console output
    ]
)
logger = logging.getLogger(__name__)

# Checking API keys
missing_keys = []
for key in required_keys:
    if not os.getenv(key):
        missing_keys.append(key)

if missing_keys:
    logger.error(f"The following keys are missing: {', '.join(missing_keys)}")
    raise ValueError("Required API keys are missing")

logger.info("All required keys are present")

class KlingAPI:
    """
    API for Kling service to generate images
    """
    def __init__(self, api_key=None, logger=None):
        self.api_key = api_key or os.getenv("KLING_API_KEY") or config.KLING_API_KEY
        self.base_url = "https://api.goapi.ai"
        self.logger = logger
        
    def log_info(self, message):
        """Log info message"""
        if self.logger and hasattr(self.logger, 'log_info'):
            self.logger.log_info(message)
        elif self.logger and hasattr(self.logger, 'print_info'):
            self.logger.print_info(message)
        else:
            logging.info(message)
    
    def log_error(self, message):
        """Log error message"""
        if self.logger and hasattr(self.logger, 'log_error'):
            self.logger.log_error(message)
        elif self.logger and hasattr(self.logger, 'print_error'):
            self.logger.print_error(message)
        else:
            logging.error(message)
    
    def animate_image(self, image_url, aspect_ratio="9:16"):
        """
        Generate image using Kling API
        
        Parameters:
        ----------
        image_url : str
            URL of the image to generate
        aspect_ratio : str, default "9:16"
            Desired aspect ratio ("9:16", "1:1", "16:9")
            
        Returns:
        -------
        str
            Task ID (task_id) or None in case of error
        """
        self.log_info(f"Starting image generation process using Kling API")
        self.log_info(f"Image URL: {image_url}")
        self.log_info(f"Aspect ratio chosen: {aspect_ratio}")
        
        # Check if API key is provided
        if not self.api_key:
            self.log_error("Missing API key for Kling service")
            return None
            
        # Adjust aspect ratio to Kling format
        if aspect_ratio == "9:16":
            kling_aspect = "9:16" 
        elif aspect_ratio == "1:1":
            kling_aspect = "1:1"
        else:
            kling_aspect = "16:9"  # Default
        
        # Prepare the request
        url = f"{self.base_url}/api/v1/task"
        
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        # Prepare the request based on the example provided by the user
        data = {
            "model": "kling",
            "task_type": "video_generation",
            "input": {
                "prompt": "Photorealistic style, detailed, natural lighting, professional quality photograph taken with Iphone 13",
                "negative_prompt": "blurry, low quality, distorted, text, font, writing, brand logos",
                "cfg_scale": 0.5,
                "duration": 5,
                "aspect_ratio": "std" if kling_aspect == "16:9" else kling_aspect,
                "image_url": image_url
            }
        }
        
        try:
            self.log_info(f"Sending request to Kling API at {url}")
            self.log_info(f"Request data: {str(data)}")
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            # Detailed response received
            self.log_info(f"Received response from Kling API. Status: {response.status_code}")
            
            # Attempt to parse the response as JSON
            try:
                result = response.json()
                self.log_info(f"Response content: {str(result)}")
            except Exception as e:
                self.log_error(f"Failed to parse response as JSON: {str(e)}")
                self.log_info(f"Response content: {response.text[:200]}")
                
            response.raise_for_status()  # Raise an error if status code is not 2xx
            
            result = response.json()
            
            if result.get("code") == 200 and "task_id" in result.get("data", {}):
                task_id = result["data"]["task_id"]
                self.log_info(f"Task created successfully. Task ID: {task_id}")
                return task_id
            else:
                error_msg = result.get("message", "Unknown error")
                self.log_error(f"Error in creating task: {error_msg}")
                self.log_error(f"Error details: {str(result)}")
                return None
                
        except Exception as e:
            self.log_error(f"Error in sending request: {str(e)}")
            return None
    
    def check_animation_status(self, task_id):
        """
        Check status of the task
        
        Parameters:
        ----------
        task_id : str
            Task ID received from animate_image
            
        Returns:
        -------
        dict
            Dictionary containing information about the task status or None in case of error
            
        The returned dictionary contains the following keys:
        - status: Task status ('completed', 'processing', 'pending', 'failed')
        - video_url: URL of the generated video (only if status is 'completed')
        """
        self.log_info(f"Checking status of task for Task ID: {task_id}")
        
        url = f"{self.base_url}/api/v1/task/{task_id}"
        
        headers = {
            "x-api-key": self.api_key
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            self.log_info(f"Received response from Kling API for status check. Status code: {response.status_code}")
            
            # Attempt to parse the response as JSON
            try:
                result = response.json()
                self.log_info(f"Response content: {str(result)}")
            except Exception as e:
                self.log_error(f"Failed to parse status response as JSON: {str(e)}")
                self.log_info(f"Response content: {response.text[:200]}")
                return None
                
            response.raise_for_status()  # Raise an error if status code is not 2xx
            
            if result.get("code") != 200:
                error_msg = result.get("message", "Unknown error")
                self.log_error(f"Error in checking task status: {error_msg}")
                self.log_error(f"Error details: {str(result)}")
                return None
            
            data = result.get("data", {})
            status = data.get("status", "").lower()
            
            response_data = {
                "status": status
            }
            
            # If task is completed, add video URL
            if status == "completed":
                output = data.get("output", {})
                if "works" in output and len(output["works"]) > 0:
                    video_url = None
                    # Try to find a video without watermark first
                    video_url = output["works"][0].get("video", {}).get("resource_without_watermark")
                    
                    # If no version without watermark, use the original
                    if not video_url:
                        video_url = output["works"][0].get("video", {}).get("resource")
                    
                    # Additional check - check in output.video if exists
                    if not video_url and "video" in output:
                        video_url = output.get("video", {}).get("resource_without_watermark") or output.get("video", {}).get("resource")
                    
                    if video_url:
                        response_data["video_url"] = video_url
                        self.log_info(f"Task completed successfully. Video available at: {video_url}")
                    else:
                        self.log_error("Video URL not found in response")
                        self.log_error(f"Response structure: {str(output)}")
            else:
                self.log_info(f"Task status: {status}. Waiting for completion.")
            
            return response_data
                
        except Exception as e:
            self.log_error(f"Error in checking task status: {str(e)}")
            self.log_error(f"Error details: {traceback.format_exc()}")
            return None

class MinimaxAPI:
    """
    API for Minimax service to generate images
    """
    def __init__(self, api_key=None, logger=None):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY") or config.MINIMAX_API_KEY
        self.base_url = "https://api.goapi.ai"
        self.logger = logger
        
    def log_info(self, message):
        """Log info message"""
        if self.logger and hasattr(self.logger, 'log_info'):
            self.logger.log_info(message)
        elif self.logger and hasattr(self.logger, 'print_info'):
            self.logger.print_info(message)
        else:
            logging.info(message)
    
    def log_error(self, message):
        """Log error message"""
        if self.logger and hasattr(self.logger, 'log_error'):
            self.logger.log_error(message)
        elif self.logger and hasattr(self.logger, 'print_error'):
            self.logger.print_error(message)
        else:
            logging.error(message)
    
    def animate_image(self, image_url, aspect_ratio="9:16"):
        """
        Generate image using Minimax (Hailuo)
        
        Parameters:
        ----------
        image_url : str
            URL of the image to generate
        aspect_ratio : str, default "9:16"
            Desired aspect ratio ("9:16", "1:1", "16:9")
            
        Returns:
        -------
        str
            Task ID (task_id) or None in case of error
        """
        self.log_info(f"Starting image generation process using Minimax API")
        self.log_info(f"Image URL: {image_url}")
        self.log_info(f"Aspect ratio chosen: {aspect_ratio}")
        
        # Check if API key is provided
        if not self.api_key:
            self.log_error("Missing API key for Minimax service")
            return None
        
        # Prepare the request
        url = f"{self.base_url}/api/v1/task"
        
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        # Prepare the request based on Hailuo/GOAPI format
        data = {
            "model": "hailuo",
            "task_type": "video_generation",
            "input": {
                "model": "i2v-01",
                "image_url": image_url,
                "prompt": "Photorealistic, detailed, natural movement, professional quality"
            },
            "config": {
                "service_mode": "public"
            }
        }
        
        try:
            self.log_info(f"Sending request to Minimax API at {url}")
            self.log_info(f"Request data: {str(data)}")
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            # Detailed response received
            self.log_info(f"Received response from Minimax API. Status: {response.status_code}")
            
            # Attempt to parse the response as JSON
            try:
                result = response.json()
                self.log_info(f"Response content: {str(result)}")
            except Exception as e:
                self.log_error(f"Failed to parse response as JSON: {str(e)}")
                self.log_info(f"Response content: {response.text[:200]}")
                
            response.raise_for_status()  # Raise an error if status code is not 2xx
            
            result = response.json()
            
            if result.get("code") == 200 and "task_id" in result.get("data", {}):
                task_id = result["data"]["task_id"]
                self.log_info(f"Task created successfully. Task ID: {task_id}")
                return task_id
            else:
                error_msg = result.get("message", "Unknown error")
                self.log_error(f"Error in creating task: {error_msg}")
                self.log_error(f"Error details: {str(result)}")
                return None
                
        except Exception as e:
            self.log_error(f"Error in sending request: {str(e)}")
            return None
    
    def check_animation_status(self, task_id):
        """
        Check status of the task
        
        Parameters:
        ----------
        task_id : str
            Task ID received from animate_image
            
        Returns:
        -------
        dict
            Dictionary containing information about the task status or None in case of error
            
        The returned dictionary contains the following keys:
        - status: Task status ('completed', 'processing', 'pending', 'failed')
        - video_url: URL of the generated video (only if status is 'completed')
        """
        self.log_info(f"Checking status of task for Task ID: {task_id}")
        
        url = f"{self.base_url}/api/v1/task/{task_id}"
        
        headers = {
            "x-api-key": self.api_key
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            self.log_info(f"Received response from Minimax API for status check. Status code: {response.status_code}")
            
            # Attempt to parse the response as JSON
            try:
                result = response.json()
                self.log_info(f"Response content: {str(result)}")
            except Exception as e:
                self.log_error(f"Failed to parse status response as JSON: {str(e)}")
                self.log_info(f"Response content: {response.text[:200]}")
                return None
                
            response.raise_for_status()  # Raise an error if status code is not 2xx
            
            if result.get("code") != 200:
                error_msg = result.get("message", "Unknown error")
                self.log_error(f"Error in checking task status: {error_msg}")
                self.log_error(f"Error details: {str(result)}")
                return None
            
            data = result.get("data", {})
            status_text = data.get("status", "").lower()
            
            # Mapping Minimax status to unified format
            if status_text == "success":
                status = "completed"
            elif status_text in ["pending", "starting", "processing"]:
                status = "processing"
            elif status_text in ["failed", "retry"]:
                status = "failed"
            else:
                status = status_text
                
            response_data = {
                "status": status
            }
            
            # If task is completed, add video URL
            if status == "completed":
                output = data.get("output", {})
                video_url = output.get("video_url") or output.get("download_url")
                
                if video_url:
                    response_data["video_url"] = video_url
                    self.log_info(f"Task completed successfully. Video available at: {video_url}")
                else:
                    self.log_error("Video URL not found in response")
                    self.log_error(f"Response structure: {str(output)}")
            else:
                self.log_info(f"Task status: {status}. Waiting for completion.")
            
            return response_data
                
        except Exception as e:
            self.log_error(f"Error in checking task status: {str(e)}")
            self.log_error(f"Error details: {traceback.format_exc()}")
            return None

class VideoProcessor:
    def __init__(self, config=None):
        """Initialize the VideoProcessor with API keys and credentials"""
        self.config = config
        
        # Attempt to reconfigure stdout/stderr for UTF-8 support for print statements
        # This is important for handling Hebrew characters in console output on Windows
        if sys.stdout.encoding != 'utf-8':
            try:
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
                print("INFO: Reconfigured stdout and stderr to UTF-8.") # Test print
            except Exception as e_reconfigure:
                print(f"WARNING: Could not reconfigure stdout/stderr to UTF-8: {e_reconfigure}")
        
        # Add thread safety for logging FIRST - before any logging calls
        self._log_lock = threading.Lock()
        
        # Initialize parallel processing settings
        self.max_parallel_workers = 6
        
        # Initialize logging functions with defaults
        # These will now use the (potentially) reconfigured stdout/stderr
        self.print_info = lambda msg: print(f"INFO: {msg}")
        self.print_success = lambda msg: print(f"SUCCESS: {msg}")
        self.print_error = lambda msg: print(f"ERROR: {msg}")
        self.print_warning = lambda msg: print(f"WARNING: {msg}")
        
        # Create temp directory using an absolute path
        self.temp_dir = os.path.abspath("temp") # MODIFIED LINE
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
        self.log_info(f"Using temporary directory: {self.temp_dir}")
        
        # Checking ffmpeg availability (currently assuming it's available)
        # self.ffmpeg_available = self.check_ffmpeg() # Source of error - check_ffmpeg is not defined
        self.ffmpeg_available = True # Assuming ffmpeg is available. Add a proper check if needed.
        self.ffmpeg_path = "ffmpeg"
        if not self.ffmpeg_available:
            self.print_warning("ffmpeg is not available on the system - using MoviePy as a fallback")
        else:
            self.print_info("ffmpeg is available on the system - using it for video processing")
        
        # Storing sheet rows
        self.rows = []
        
        # Define available voice codes
        self.voice_codes = [
            'pVnrL6sighQX7hVz89cp',
            'gOkFV1JMCt0G0n9xmBwV',
            'FmJ4FDkdrYIKzBTruTkV',
            'yl2ZDV1MzN4HbQJbMihG',
            'NNwktITHHVNmS6zfr4Am',
            'P7x743VjyZEOihNNygQ9',
            'xctasy8XvGp2cVO9HL9k',
            'vEHuGikHFHgKEHihVc4j',
            'XfNU2rGpBa01ckF309OY',
            'TNHbwIMY5QmLqZdvjhNn',
            '2zRM7PkgwBPiau2jvVXc',
            'vYENaCJHl4vFKNDYPr8y'
        ]
        
        self.pending_zapcap_tasks: list[dict] = []   # new
        
        # Load environment variables
        load_dotenv()
        
        # Set API keys
        self.elevenlabs_api_key = os.getenv('ELEVEN_LABS_API_KEY')
        if not self.elevenlabs_api_key:
            self.log_warning("ELEVEN_LABS_API_KEY not found in environment variables")
            
        self.zapcap_api_key = os.getenv('ZAPCAP_API_KEY')
        if not self.zapcap_api_key:
            self.log_warning("ZAPCAP_API_KEY not found in environment variables")

        # Initialize OpenAI client for TTS fallback
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.openai_client = None
        if self.openai_api_key:
            try:
                self.openai_client = OpenAI(api_key=self.openai_api_key)
                self.log_info("OpenAI client initialized successfully for TTS fallback")
            except Exception as e:
                self.log_warning(f"Failed to initialize OpenAI client: {str(e)}")
        else:
            self.log_warning("OPENAI_API_KEY not found - OpenAI TTS fallback will not be available")
        
        # ElevenLabs availability flag
        self.elevenlabs_available = None  # Will be checked on first use
            
        self.zapcap_base_url = os.getenv("ZAPCAP_BASE_URL") or "https://api.zapcap.ai"
        
        # Use API key for Kling service
        self.kling_api_key = os.getenv("KLING_API_KEY") or getattr(config, "KLING_API_KEY", None)
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY") or getattr(config, "MINIMAX_API_KEY", None)
        
        # Initialize Kling and Minimax services
        self.kling_api = KlingAPI(self.kling_api_key, self)
        self.minimax_api = MinimaxAPI(self.minimax_api_key, self)
        
        # Initialize Google Sheets
        self.sheet = self.initialize_sheets()
        
        # Set GCS bucket name
        self.gcs_bucket_name = os.getenv("GCS_BUCKET_NAME") or "your-gcs-bucket"
        
        # Initialize Google Cloud Storage
        try:
            if os.path.exists("service_account.json"):
                self.storage_client = storage.Client.from_service_account_json('service_account.json')
                self.bucket = self.storage_client.bucket(self.gcs_bucket_name)
                self.log_success(f"Successfully connected to Google Cloud Storage. Bucket: {self.gcs_bucket_name}")
            else:
                self.log_warning("service_account.json file not found, application will continue without cloud storage")
                self.storage_client = None
                self.bucket = None
        except Exception as e:
            self.log_warning(f"Error in initializing connection to Google Cloud Storage: {str(e)}")
            self.storage_client = None
            self.bucket = None
        
        # Background Music Configuration (ensure this is up-to-date with relative path)
        self.bg_music_dir = os.path.join(os.getcwd(), "BG MUSIC") 
        self.bg_music_files = []
        self.log_info(f"Attempting to load background music from: {self.bg_music_dir}")
        if os.path.exists(self.bg_music_dir) and os.path.isdir(self.bg_music_dir):
            try:
                self.bg_music_files = [f for f in os.listdir(self.bg_music_dir) if f.lower().endswith('.mp3')]
                if self.bg_music_files:
                    self.log_info(f"Found {len(self.bg_music_files)} MP3 files in BG MUSIC directory: {self.bg_music_dir}")
                else:
                    self.log_warning(f"No MP3 files found in BG MUSIC directory: {self.bg_music_dir}")
            except Exception as e:
                self.log_error(f"Error listing BG MUSIC directory {self.bg_music_dir}: {e}")
        else:
            self.log_warning(f"BG MUSIC directory not found at: {self.bg_music_dir}")

        # Thread Pools for concurrent operations (Step 3 & 4 from guide)
        # Make max_workers configurable via config.py or use defaults
        tts_pool_workers = getattr(config, 'TTS_POOL_WORKERS', 2) # Reduced default for TTS, can be I/O bound
        video_pool_workers = getattr(config, 'VIDEO_POOL_WORKERS', 2) # For CPU/GPU bound video rendering
        zap_pool_workers = getattr(config, 'ZAPCAP_POOL_WORKERS', 4)  # For I/O bound ZapCap submissions

        self.tts_pool = ThreadPoolExecutor(max_workers=tts_pool_workers, thread_name_prefix='TTSPool')
        self.video_processing_pool = ThreadPoolExecutor(max_workers=video_pool_workers, thread_name_prefix='VideoPool')
        self.zap_pool = ThreadPoolExecutor(max_workers=zap_pool_workers, thread_name_prefix='ZapCapPool')
        self.log_info(f"Initialized Pools: TTS ({tts_pool_workers}), Video ({video_pool_workers}), ZapCap ({zap_pool_workers}).")

        # Shared resources for pipeline (Step 4)
        # maxsize for queue to prevent producer from running too far ahead of consumers if ZapCap is slow
        video_queue_maxsize = getattr(config, 'VIDEO_QUEUE_SIZE', video_pool_workers * 2) # e.g., allow some buffer
        self.video_q = queue.Queue(maxsize=video_queue_maxsize) 
        self.video_producers_done_event = threading.Event()
        self._zap_lock = threading.Lock() 
        self.tasks_for_final_monitoring = [] # This will be populated by _zapcap_worker threads

        # Initialize language mapping
        self.language_mapping = {
            'he': 'he',  # Hebrew
            'en': 'en',  # English
            'es': 'es',  # Spanish
            'fr': 'fr',  # French
            'de': 'de',  # German
            'it': 'it',  # Italian
            'pt': 'pt',  # Portuguese
            'nl': 'nl',  # Dutch
            'pl': 'pl',  # Polish
            'ru': 'ru',  # Russian
            'ja': 'ja',  # Japanese
            'ko': 'ko',  # Korean
            'zh': 'zh',  # Chinese
            'ar': 'ar',  # Arabic
            'hi': 'hi',  # Hindi
            'tr': 'tr',  # Turkish
            'vi': 'vi',  # Vietnamese
            'th': 'th',  # Thai
            'id': 'id',  # Indonesian
            'ms': 'ms',  # Malay
            'fa': 'fa',  # Persian
            'ur': 'ur',  # Urdu
            'bn': 'bn',  # Bengali
            'ta': 'ta',  # Tamil
            'te': 'te',  # Telugu
            'mr': 'mr',  # Marathi
            'gu': 'gu',  # Gujarati
            'kn': 'kn',  # Kannada
            'ml': 'ml',  # Malayalam
            'si': 'si',  # Sinhala
            'my': 'my',  # Burmese
            'km': 'km',  # Khmer
            'lo': 'lo',  # Lao
            'sv': 'sv',  # Swedish
            'da': 'da',  # Danish
            'fi': 'fi',  # Finnish
            'el': 'el',  # Greek
            'is': 'is',  # Icelandic
            'mt': 'mt',  # Maltese
            'lv': 'lv',  # Latvian
            'lt': 'lt',  # Lithuanian
            'et': 'et',  # Estonian
            'hr': 'hr',  # Croatian
            'hu': 'hu',  # Hungarian
            'cs': 'cs',  # Czech
            'ro': 'ro',  # Romanian
            'sk': 'sk',  # Slovak
            'uk': 'uk',  # Ukrainian
            'sr': 'sr',  # Serbian
            'sl': 'sl',  # Slovenian
            'mk': 'mk',  # Macedonian
            'bg': 'bg',  # Bulgarian
            'af': 'af',  # Afrikaans
            'am': 'am',  # Amharic
            'as': 'as',  # Assamese
            'az': 'az',  # Azerbaijani
            'ba': 'ba',  # Bashkir
            'be': 'be',  # Belarusian
            'bo': 'bo',  # Tibetan
            'br': 'br',  # Breton
            'bs': 'bs',  # Bosnian
            'ca': 'ca',  # Catalan
            'cy': 'cy',  # Welsh
            'eu': 'eu',  # Basque
            'fo': 'fo',  # Faroese
            'gl': 'gl',  # Galician
            'ha': 'ha',  # Hausa
            'haw': 'haw',  # Hawaiian
            'ht': 'ht',  # Haitian Creole
            'hy': 'hy',  # Armenian
            'id': 'id',  # Indonesian
            'jw': 'jw',  # Javanese
            'ka': 'ka',  # Georgian
            'kk': 'kk',  # Kazakh
            'ln': 'ln',  # Lingala
            'mg': 'mg',  # Malagasy
            'mi': 'mi',  # Maori
            'mn': 'mn',  # Mongolian
            'ne': 'ne',  # Nepali
            'nn': 'nn',  # Norwegian Nynorsk
            'no': 'no',  # Norwegian
            'oc': 'oc',  # Occitan
            'pa': 'pa',  # Punjabi
            'ps': 'ps',  # Pashto
            'sd': 'sd',  # Sindhi
            'sn': 'sn',  # Shona
            'so': 'so',  # Somali
            'sq': 'sq',  # Albanian
            'su': 'su',  # Sundanese
            'sw': 'sw',  # Swahili
            'tg': 'tg',  # Tajik
            'tk': 'tk',  # Turkmen
            'tl': 'tl',  # Tagalog
            'tt': 'tt',  # Tatar
            'uz': 'uz',  # Uzbek
            'yi': 'yi',  # Yiddish
            'yo': 'yo',  # Yoruba
            'yue': 'yue'  # Cantonese
        }
        
        # Add full language names mapping
        self.language_names_mapping = {
            'hebrew': 'he',
            'english': 'en',
            'spanish': 'es',
            'french': 'fr',
            'german': 'de',
            'italian': 'it',
            'portuguese': 'pt',
            'dutch': 'nl',
            'polish': 'pl',
            'russian': 'ru',
            'japanese': 'ja',
            'korean': 'ko',
            'chinese': 'zh',
            'arabic': 'ar',
            'hindi': 'hi',
            'turkish': 'tr',
            'vietnamese': 'vi',
            'thai': 'th',
            'indonesian': 'id',
            'malay': 'ms',
            'persian': 'fa',
            'urdu': 'ur',
            'bengali': 'bn',
            'tamil': 'ta',
            'telugu': 'te',
            'marathi': 'mr',
            'gujarati': 'gu',
            'kannada': 'kn',
            'malayalam': 'ml',
            'sinhala': 'si',
            'burmese': 'my',
            'khmer': 'km',
            'lao': 'lo',
            'swedish': 'sv',
            'danish': 'da',
            'finnish': 'fi',
            'greek': 'el',
            'icelandic': 'is',
            'maltese': 'mt',
            'latvian': 'lv',
            'lithuanian': 'lt',
            'estonian': 'et',
            'croatian': 'hr',
            'hungarian': 'hu',
            'czech': 'cs',
            'romanian': 'ro',
            'slovak': 'sk',
            'ukrainian': 'uk',
            'serbian': 'sr',
            'slovenian': 'sl',
            'macedonian': 'mk',
            'bulgarian': 'bg',
            'afrikaans': 'af',
            'amharic': 'am',
            'assamese': 'as',
            'azerbaijani': 'az',
            'bashkir': 'ba',
            'belarusian': 'be',
            'tibetan': 'bo',
            'breton': 'br',
            'bosnian': 'bs',
            'catalan': 'ca',
            'welsh': 'cy',
            'basque': 'eu',
            'faroese': 'fo',
            'galician': 'gl',
            'hausa': 'ha',
            'hawaiian': 'haw',
            'haitian creole': 'ht',
            'armenian': 'hy',
            'javanese': 'jw',
            'georgian': 'ka',
            'kazakh': 'kk',
            'lingala': 'ln',
            'malagasy': 'mg',
            'maori': 'mi',
            'mongolian': 'mn',
            'nepali': 'ne',
            'norwegian nynorsk': 'nn',
            'norwegian': 'no',
            'occitan': 'oc',
            'punjabi': 'pa',
            'pashto': 'ps',
            'sindhi': 'sd',
            'shona': 'sn',
            'somali': 'so',
            'albanian': 'sq',
            'sundanese': 'su',
            'swahili': 'sw',
            'tajik': 'tg',
            'turkmen': 'tk',
            'tagalog': 'tl',
            'tatar': 'tt',
            'uzbek': 'uz',
            'yiddish': 'yi',
            'yoruba': 'yo',
            'cantonese': 'yue'
        }

    def _is_image_file(self, file_path):
        """
        Checks if a file is an image based on its extension and magic bytes.
        This is more robust than checking extension alone.
        """
        if not file_path or not isinstance(file_path, str):
            return False
            
        # First check by extension
        common_image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
        try:
            if os.path.splitext(file_path)[1].lower() in common_image_extensions:
                return True
        except Exception:
            pass
            
        # If extension check fails, check magic bytes
        try:
            if not os.path.exists(file_path):
                return False
                
            with open(file_path, 'rb') as f:
                header = f.read(12)  # Read first 12 bytes
                
            if len(header) < 4:
                return False
                
            # Check common image magic bytes
            # JPEG: FF D8 FF
            if header.startswith(b'\xff\xd8\xff'):
                return True
            # PNG: 89 50 4E 47 0D 0A 1A 0A
            if header.startswith(b'\x89PNG\r\n\x1a\n'):
                return True
            # GIF: GIF87a or GIF89a
            if header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
                return True
            # BMP: BM
            if header.startswith(b'BM'):
                return True
            # TIFF: 49 49 2A 00 or 4D 4D 00 2A
            if header.startswith(b'II*\x00') or header.startswith(b'MM\x00*'):
                return True
            # WebP: RIFF....WEBP
            if header.startswith(b'RIFF') and len(header) >= 12 and header[8:12] == b'WEBP':
                return True
                
        except Exception as e:
            # Log the error but don't fail completely
            self.log_warning(f"Error checking magic bytes for {file_path}: {str(e)}")
            
        return False

    def log_info(self, message):
        """Log info message"""
        with self._log_lock:
            logging.info(message)
            if hasattr(self, 'print_info') and callable(self.print_info) and self.print_info != self.log_info:
                self.print_info(message)

    def log_success(self, message):
        """Log success message"""
        with self._log_lock:
            logging.info(message)
            if hasattr(self, 'print_success') and callable(self.print_success) and self.print_success != self.log_success:
                self.print_success(message)

    def log_error(self, message):
        """Log error message"""
        with self._log_lock:
            logging.error(message)
            if hasattr(self, 'print_error') and callable(self.print_error) and self.print_error != self.log_error:
                self.print_error(message)

    def log_warning(self, message):
        """Log warning message"""
        with self._log_lock:
            logging.warning(message)
            if hasattr(self, 'print_warning') and callable(self.print_warning) and self.print_warning != self.log_warning:
                self.print_warning(message)

    def initialize_sheets(self):
        """Initialize Google Sheets connection"""
        try:
            # Define the scope
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive']
            
            # Create credentials from service account file
            creds = Credentials.from_service_account_file(
                'service_account.json',
                scopes=scope
            )
            
            # Create client
            client = gspread.authorize(creds)
            
            # Get sheet ID from environment
            sheet_id = os.getenv('GOOGLE_SHEET_ID')
            if not sheet_id:
                raise Exception("Sheet ID not found in environment variables")
            
            # Open sheet
            sheet = client.open_by_key(sheet_id).sheet1
            self.log_info("Successfully connected to Google Sheet")
            
            # Validating sheet columns
            self._validate_sheet_columns(sheet)
            
            return sheet
            
        except Exception as e:
            self.log_error(f"Failed to initialize Google Sheets: {str(e)}")
            raise
            
    def _validate_sheet_columns(self, sheet):
        """
        Validates the sheet columns against the columns defined in the configuration file.
        
        Parameters:
        ----------
        sheet : gspread.worksheet.Worksheet
            Sheet object to validate.
        """
        try:
            # Getting column headers from the sheet
            headers = sheet.row_values(1)
            self.log_info(f"Sheet column headers: {headers}")
            
            # Checking required columns
            missing_columns = []
            for col_key, col_name in config.COLUMNS.items():
                if col_name not in headers:
                    missing_columns.append(col_name)
                    self.log_warning(f"Required column '{col_name}' is missing from the sheet")
            
            # Alert if columns are missing
            if missing_columns:
                self.log_error(f"{len(missing_columns)} columns are missing from the sheet: {', '.join(missing_columns)}")
                self.log_error("There might be a mismatch in column names or unnecessary spaces")
            else:
                self.log_success("All required columns are present in the sheet")
                
            # Identifying similar column names that might cause confusion
            for col_name in config.COLUMNS.values():
                for header in headers:
                    # Checking for similar names (e.g., with unnecessary spaces)
                    if col_name != header and col_name.lower() == header.lower():
                        self.log_warning(f"Found a similar column: '{header}' instead of '{col_name}' - this might be the cause of an issue")
                    elif col_name != header and col_name.replace(" ", "") == header.replace(" ", ""):
                        self.log_warning(f"Found a column with different spacing: '{header}' instead of '{col_name}'")
                    
        except Exception as e:
            self.log_error(f"Error validating sheet columns: {str(e)}")

    def check_elevenlabs_availability(self) -> bool:
        """Check if ElevenLabs API is responding"""
        if self.elevenlabs_available is not None:
            return self.elevenlabs_available
            
        if not self.elevenlabs_api_key:
            self.elevenlabs_available = False
            return False
            
        try:
            self.log_info("Checking ElevenLabs API availability...")
            url = "https://api.elevenlabs.io/v1/voices"
            headers = {"xi-api-key": self.elevenlabs_api_key}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                self.log_success("ElevenLabs API is available")
                self.elevenlabs_available = True
                return True
            else:
                self.log_warning(f"ElevenLabs API returned status {response.status_code}")
                self.elevenlabs_available = False
                return False
                
        except Exception as e:
            self.log_warning(f"ElevenLabs API is not responding: {str(e)}")
            self.elevenlabs_available = False
            return False

    def generate_openai_tts_batch(self, texts: list, voice_ids: list, gender_preferences: list = None) -> list:
        """Generate text-to-speech using OpenAI API as fallback with gender-based voice selection"""
        if not self.openai_client:
            raise Exception("OpenAI client not initialized")
            
        try:
            self.log_info(f"Generating TTS using OpenAI for {len(texts)} texts")
            
            # OpenAI voice mapping by gender (based on typical voice characteristics)
            female_voices = ['alloy', 'coral', 'nova', 'shimmer']
            male_voices = ['ash', 'ballad', 'echo', 'fable', 'onyx', 'sage']
            all_voices = female_voices + male_voices
            
            responses = []
            for i, text in enumerate(texts):
                try:
                    # Select voice based on gender preference
                    if gender_preferences and i < len(gender_preferences):
                        gender_pref = str(gender_preferences[i]).strip().lower()
                        if gender_pref in ['female', 'f']:
                            voice = random.choice(female_voices)
                            self.log_info(f"Selected female voice '{voice}' for text {i+1}")
                        elif gender_pref in ['male', 'm']:
                            voice = random.choice(male_voices)
                            self.log_info(f"Selected male voice '{voice}' for text {i+1}")
                        else:
                            voice = random.choice(all_voices)
                            self.log_info(f"Gender preference '{gender_pref}' not recognized, selected random voice '{voice}' for text {i+1}")
                    else:
                        # Fallback to cycling through all voices
                        voice = all_voices[i % len(all_voices)]
                        self.log_info(f"No gender preference specified, selected voice '{voice}' for text {i+1}")
                    
                    self.log_info(f"Generating OpenAI TTS for text {i+1}/{len(texts)} with voice '{voice}'")
                    
                    response = self.openai_client.audio.speech.create(
                        model="gpt-4o-mini-tts",
                        voice=voice,
                        input=text,
                        response_format="mp3"
                    )
                    
                    audio_data = response.content
                    if audio_data and len(audio_data) > 1000:
                        responses.append(audio_data)
                        self.log_info(f"Successfully generated OpenAI TTS audio {i+1} ({len(audio_data)} bytes) with {voice}")
                    else:
                        self.log_error(f"Invalid OpenAI TTS audio data for text {i+1}")
                        
                except Exception as e:
                    self.log_error(f"Error generating OpenAI TTS for text {i+1}: {str(e)}")
                    continue
            
            self.log_success(f"Successfully generated {len(responses)} OpenAI TTS audio files")
            return responses
            
        except Exception as e:
            self.log_error(f"OpenAI TTS batch generation failed: {str(e)}")
            raise

    def generate_tts_batch(self, texts: list, voice_ids: list, gender_preferences: list = None) -> list:
        """Generate text-to-speech for multiple texts in parallel with fallback and gender-based voice selection"""
        try:
            # Check ElevenLabs availability first
            if self.check_elevenlabs_availability():
                self.log_info(f"Using ElevenLabs for TTS generation of {len(texts)} texts")
                
                # Create all requests
                requests_list = []
                for text, voice_id in zip(texts, voice_ids):
                    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                    headers = {
                        "xi-api-key": self.elevenlabs_api_key,
                        "Content-Type": "application/json"
                    }
                    data = {
                        "text": text,
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75
                        }
                    }
                    requests_list.append((url, headers, data))
                
                # Send all requests in parallel
                responses = []
                for url, headers, data in requests_list:
                    try:
                        response = requests.post(url, headers=headers, json=data, timeout=30)
                        if response.status_code != 200:
                            raise Exception(f"ElevenLabs API error: {response.text}")
                        responses.append(response.content)
                    except Exception as e:
                        self.log_error(f"Error generating ElevenLabs TTS: {str(e)}")
                        # If ElevenLabs fails, fall back to OpenAI
                        self.log_warning("ElevenLabs failed, switching to OpenAI TTS")
                        self.elevenlabs_available = False
                        return self.generate_openai_tts_batch(texts, voice_ids, gender_preferences)
                
                # Wait for a moment to ensure all audio is fully generated
                time.sleep(10)
                
                # Verify all audio data
                for i, audio_data_item in enumerate(responses):
                    if not audio_data_item or len(audio_data_item) < 1000:
                        raise Exception(f"Invalid audio data received for text {i}")
                
                self.log_success(f"Successfully generated {len(responses)} ElevenLabs audio files")
                return responses
                
            else:
                # ElevenLabs not available, use OpenAI
                self.log_info("ElevenLabs not available, using OpenAI TTS as fallback")
                return self.generate_openai_tts_batch(texts, voice_ids, gender_preferences)
            
        except Exception as e:
            # Final fallback attempt with OpenAI if ElevenLabs completely fails
            if self.openai_client and "OpenAI" not in str(e):
                self.log_warning(f"ElevenLabs TTS failed ({str(e)}), trying OpenAI as final fallback")
                try:
                    return self.generate_openai_tts_batch(texts, voice_ids, gender_preferences)
                except Exception as openai_error:
                    self.log_error(f"Both ElevenLabs and OpenAI TTS failed. OpenAI error: {str(openai_error)}")
                    raise Exception(f"All TTS services failed. ElevenLabs: {str(e)}, OpenAI: {str(openai_error)}")
            else:
                self.log_error(f"TTS generation failed: {str(e)}")
                raise

    def create_base_video(self, image_data, audio_data, duration=3, zoom_in=False, video_size="9:16"):
        """
        Creates a basic video from an image and audio.
        
        Parameters:
        ----------
        image_data : bytes
            Image data.
        audio_data : bytes
            Audio data.
        duration : int
            Video duration in seconds.
        zoom_in : bool
            Whether to add a zoom effect.
        video_size : str
            Desired aspect ratio ("9:16" or "1:1").
            
        Returns:
        -------
        bytes
            Generated video data.
        """
        self.log_info("Creating basic video from image and audio")
        
        # Determining video size
        if video_size == "1:1":
            width, height = 1080, 1080
        else:  # 9:16
            width, height = 1080, 1920
            
        self.log_info(f"Video size: {width}x{height}")
        
        # Saving image and audio to temporary files
        timestamp = str(int(time.time()))
        temp_image = os.path.join(self.temp_dir, f"temp_image_{timestamp}.jpg")
        temp_audio_file = os.path.join(self.temp_dir, f"temp_audio_{timestamp}.mp3")
        
        with open(temp_image, "wb") as f:
            f.write(image_data)
        with open(temp_audio_file, "wb") as f: # Use temp_audio_file
            f.write(audio_data)
        
        # Building ffmpeg command
        output_file = os.path.join(self.temp_dir, f"base_video_{timestamp}.mp4")
        
        # Adding zoom effect if required
        zoom_filter = ""
        if zoom_in:
            zoom_filter = ",zoompan=z='1.5-0.005*on':d=90:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        
        # Building the command
        command = [
            'ffmpeg', '-y',
            '-loop', '1',
            '-i', temp_image,
            '-i', temp_audio_file, # Use temp_audio_file
            '-vf', f'scale={width}:{height},crop={width}:{height}{zoom_filter}',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            output_file
        ]
        
        # Running the command
        self.log_info(f"Executing ffmpeg command: {' '.join(command)}")
        import subprocess
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Checking if the file was created successfully
        if os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
            self.log_success("Successfully created basic video")
            
            # Reading the file
            with open(output_file, "rb") as f:
                video_data = f.read()
            
            # Cleaning up temporary files
            for file_to_remove in [temp_image, temp_audio_file, output_file]:
                try:
                    if os.path.exists(file_to_remove):
                        os.remove(file_to_remove)
                except Exception as e:
                    self.log_warning(f"Error cleaning up temporary file {file_to_remove}: {str(e)}")
            
            return video_data
        else:
            self.log_error("Error creating basic video")
            return None

    def wait_for_animations(self, animation_tasks):
        """
        Public interface for the _wait_for_animations function.
        Waits for animation tasks to complete.
        
        Parameters:
        ----------
        animation_tasks : list
            List of animation tasks.
            
        Returns:
        -------
        list
            List of completed tasks.
        """
        if not animation_tasks:
            self.log_warning("No animation tasks to wait for")
            return []
            
        self.log_info(f"Waiting for {len(animation_tasks)} animation tasks to complete")
        
        completed_tasks = []
        pending_tasks = animation_tasks.copy()
        
        max_wait_time = 1800  # 30 minutes (increased from 900 seconds for better animation completion)
        self.log_info(f"Setting max_wait_time for animation batch to {max_wait_time} seconds.")
        check_interval = 5  # 5 seconds
        start_time = time.time()
        
        while pending_tasks and (time.time() - start_time < max_wait_time):
            self.log_info(f"Checking status of {len(pending_tasks)} animation tasks")
            
            still_pending = []
            
            for task in pending_tasks:
                task_id = task['task_id']
                row_index = task['row']
                column = task['column']
                service = task.get('service', 'kling')  # Default to Kling
                
                self.log_info(f"Checking status for task {task_id} (row {row_index})")
                
                # Checking status by service type
                status_data = None
                if service.lower() == 'minimax':
                    status_data = self.minimax_api.check_animation_status(task_id)
                else:
                    status_data = self.kling_api.check_animation_status(task_id)
                
                if not status_data:
                    self.log_error(f"Failed to get status for task {task_id}")
                    still_pending.append(task)
                    continue
                    
                status = status_data.get('status')
                
                if status == 'completed':
                    video_url = status_data.get('video_url')
                    if video_url:
                        self.log_success(f"Animation completed successfully: {task_id}")
                        
                        # Updating the sheet with the animated video URL
                        self._update_sheet_animated_url(row_index, column, video_url)
                        
                        # Adding to the list of completed tasks
                        completed_tasks.append({
                            'task_id': task_id,
                            'row': row_index,
                            'column': column,
                            'video_url': video_url
                        })
                    else:
                        self.log_error(f"Animation completed but no video URL: {task_id}")
                        still_pending.append(task)
                        
                elif status == 'failed':
                    self.log_error(f"Animation failed: {task_id}")
                    
                else:
                    self.log_info(f"Animation still processing ({status}): {task_id}")
                    still_pending.append(task)
            
            pending_tasks = still_pending
            
            if pending_tasks:
                progress = f"{len(completed_tasks)}/{len(animation_tasks)} tasks completed"
                self.log_info(f"{progress}, waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                
                # Increasing check interval if it takes a long time
                if time.time() - start_time > 120:  # After 2 minutes
                    check_interval = min(check_interval * 1.5, 30)  # Gradual increase up to 30 seconds
        
        # Checking if time ran out
        if pending_tasks:
            self.log_warning(f"Wait time expired, {len(pending_tasks)} tasks still processing")
            
        self.log_info(f"Completed {len(completed_tasks)} out of {len(animation_tasks)} animation tasks")
        return completed_tasks

    def skip_remaining_zapcap_tasks(self):
        """Skips remaining ZapCap tasks and proceeds to the next step"""
        self.log_warning("Skipping remaining ZapCap tasks and proceeding to the next step")
        return []

    def download_and_process_images(self, row_data):
        """
        Downloads and processes images/videos from row data.
        
        Parameters:
        ----------
        row_data : dict
            Row data from the sheet.
            
        Returns:
        -------
        bytes
            Processed video data.
        """
        self.log_info("Starting download and processing of images/videos")
        
        # Determining video size
        video_size = row_data.get('Size', '9:16')
        if video_size == "1:1":
            width, height = 1080, 1080
        else:  # 9:16
            width, height = 1080, 1920
            
        self.log_info(f"Video size: {width}x{height}")
        
        # Check links for images/videos
        image_links = []
        for i in range(1, 11):  # Support for up to 10 images/videos
            link = row_data.get(f'Image Link {i}', '').strip()
            if link:
                image_links.append(link)
        
        if not image_links:
            self.log_error("No image/video links found")
            return None
        
        self.log_info(f"Found {len(image_links)} image/video links")
        
        # Download all images/videos
        image_data_list = []
        for i, link in enumerate(image_links):
            try:
                self.log_info(f"Downloading image/video {i+1} from {link}")
                response = requests.get(link, timeout=30)
                if response.status_code == 200:
                    image_data_list.append(response.content)
                else:
                    self.log_error(f"Error downloading image/video {i+1}: {response.status_code}")
            except Exception as e:
                self.log_error(f"Error downloading image/video {i+1}: {str(e)}")
        
        if not image_data_list:
            self.log_error("Failed to download any image/video")
            return None
        
        # If there is only one image/video, return it
        if len(image_data_list) == 1:
            self.log_info("Only one image/video found")
            return image_data_list[0]
        
        # If there are multiple images/videos, combine them
        self.log_info(f"Combining {len(image_data_list)} images/videos")
        return self._combine_images_to_video(image_data_list, video_size)

    def _combine_images_to_video(self, image_data_list, video_size):
        """
        Assembles a video from images.
        
        Parameters:
        ----------
        image_data_list : list
            List of image data.
        video_size : str
            Desired aspect ratio ("9:16" or "1:1").
            
        Returns:
        -------
        bytes
            Combined video data.
        """
        self.log_info("Combining images into a video")
        
        # Determine video size
        if video_size == "1:1":
            width, height = 1080, 1080
        else:  # 9:16
            width, height = 1080, 1920
            
        self.log_info(f"Video size: {width}x{height}")
        
        # Build video from images
        video_data = b""
        for image_data in image_data_list:
            created_video_data = self.create_base_video(image_data, b"") # Use a different variable name
            if created_video_data: # Check if video data was created
                 video_data += created_video_data
        
        self.log_success("Created video from images")
        return video_data

    def animate_images_batch(self, rows):
        """
        Creates animation tasks for multiple rows from the sheet.
        
        Parameters:
        ----------
        rows : list
            List of rows from the sheet to process.
            
        Returns:
        -------
        list
            List of created animation tasks.
        """
        self.log_info(f"Starting to create animation tasks for {len(rows)} rows")
        
        animation_tasks = []
        
        for row_data in rows:
            row_index = row_data.get('row')
            self.log_info(f"Processing row {row_index}")
            
            # Checking if there is already an animated video URL
            animated_url = row_data.get('Animated Image 1')
            if animated_url:
                self.log_info(f"Row {row_index} already has an animated video link: {animated_url}")
                continue
                
            # Determining the animation service based on the row setting
            animation_service_input = str(row_data.get('Animate the images?', '')).strip().lower()
            if 'minimax' in animation_service_input or 'hailuo' in animation_service_input:
                service = 'minimax'
            else:
                service = 'kling'  # Default
            self.log_info(f"Using animation service: {service}")
            
            # Determining video size
            video_size = row_data.get('Size', '9:16')
            self.log_info(f"Video size: {video_size}")
            
            # Checking image links
            image_links = []
            for i in range(1, 5):  # Support for 4 images
                link = row_data.get(f'Image Link {i}', '').strip()
                if link:
                    image_links.append(link)
            
            if not image_links:
                self.log_warning(f"No image links found in row {row_index}")
                continue
                
            self.log_info(f"Found {len(image_links)} image links in row {row_index}")
            
            # Animating each image
            for i, image_url in enumerate(image_links, start=1):
                self.log_info(f"Animating image {i} out of {len(image_links)}: {image_url}")
                column = f'Animated Image {i}'
                
                task_id = None
                
                # Activating the appropriate animation service
                if service == 'minimax':
                    task_id = self.minimax_api.animate_image(image_url, video_size)
                else:
                    task_id = self.kling_api.animate_image(image_url, video_size)
                    
                if task_id:
                    self.log_success(f"Animation task created successfully: {task_id}")
                    
                    # Adding task to the task list
                    task = {
                        'task_id': task_id,
                        'row': row_index,
                        'column': column,
                        'service': service,
                        'image_url': image_url
                    }
                    animation_tasks.append(task)
                    
                    # Saving task to file
                    self._save_task_to_file(task)
                    
                    # Short wait between tasks
                    if i < len(image_links) or rows.index(row_data) < len(rows) - 1:
                        self.log_info("Waiting 5 seconds before the next task...")
                        time.sleep(5)
                else:
                    self.log_error(f"Failed to create animation task for image {i} in row {row_index}")
        
        self.log_info(f"Finished creating animation tasks. Total {len(animation_tasks)} tasks created")
        return animation_tasks

    def _save_task_to_file(self, task):
        """
        Saves a task to a JSON file.
        
        Parameters:
        ----------
        task : dict
            Task details to save.
        """
        tasks_file = "active_tasks.json"
        tasks = []
        
        # Reading existing tasks if the file already exists
        if os.path.exists(tasks_file):
            try:
                with open(tasks_file, 'r') as f:
                    tasks_data = json.load(f)
                    if isinstance(tasks_data, list): # Ensure tasks_data is a list
                        tasks = tasks_data
                    else: # If not a list (e.g. a dict), initialize as empty list
                        tasks = []
            except Exception as e:
                self.log_error(f"Error reading tasks file: {str(e)}")
                tasks = [] # Initialize as empty list on error
        
        
        # Add the new task
        tasks.append(task)
        
        # Save back to file
        try:
            with open(tasks_file, 'w') as f:
                json.dump(tasks, f)
            self.log_info(f"Task saved to file {tasks_file}")
        except Exception as e:
            self.log_error(f"Error saving tasks file: {str(e)}")

    def _update_sheet_animated_url(self, row_index, column, url):
        """
        Updates the animated video URL in the sheet.
        
        Parameters:
        ----------
        row_index : int
            Row number in the sheet.
        column : str
            Name of the column to update.
        url : str
            URL of the animated video.
        """
        try:
            # Find the column number by name
            all_values = self.sheet.get_all_values()
            headers = all_values[0]
            
            # Search for the column in the headers
            column_index = -1
            for i, header_name in enumerate(headers):
                if header_name.lower() == column.lower() or header_name.lower() == config.COLUMNS.get(column, column).lower():
                    column_index = i
                    break
            
            if column_index == -1:
                self.log_error(f"No column named {column} or {config.COLUMNS.get(column, column)} found")
                return False
                
            # Update the target cell
            cell_to_update = self.sheet.cell(row_index, column_index + 1)  # Google Sheets is 1-indexed
            cell_to_update.value = url
            self.sheet.update_cell(row_index, column_index + 1, url)
            
            self.log_success(f"Updated animated video URL in row {row_index}, column {column}: {url}")
            return True
            
        except Exception as e:
            self.log_error(f"Error updating the sheet: {str(e)}")
            return False

    def _process_zapcap_batch(self, rows):
        """
        Process multiple rows for ZapCap submission, now with batching.
        
        Parameters:
        ----------
        rows : list
            List of row data dictionaries to process.
        """
        ZAPCAP_BATCH_SIZE = 10
        self.log_info(f"Processing {len(rows)} rows for ZapCap submission with batch_size={ZAPCAP_BATCH_SIZE}")
        
        vertical_col = config.COLUMNS.get('VERTICAL', 'Vertical')
        
        total_successful_submissions = 0
        total_attempted_submissions = 0
        
        current_zapcap_batch_tasks = []

        for i, row_data in enumerate(rows):
            row_index = row_data.get('original_row_index')
            if not row_index:
                self.log_error("Row data missing original_row_index in _process_zapcap_batch. Skipping.")
                continue
            
            if not row_data.get(vertical_col, '').strip():
                self.log_info(f"Skipping row {row_index} in _process_zapcap_batch - empty Vertical column")
                continue

            self.log_info(f"Processing row {row_index} ({i+1}/{len(rows)}) for ZapCap submission in _process_zapcap_batch")
            total_attempted_submissions += 1
            
            animated_links = [
                row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{j}', f'Animated Image {j}')) 
                for j in range(1, 5) 
                if row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{j}', f'Animated Image {j}'))
            ]
            
            submission_details = None # To store result from _submit_combined_to_zapcap

            if not animated_links:
                self.log_info(f"Row {row_index}: No animated links found. Will use static images for ZapCap.")
                try:
                    # Pass the pre-generated audio data to the processing function
                    audio_for_row = row_data.get('audio_data')  # Fixed: changed from 'actual_audio_data' to 'audio_data'
                    submission_details = self._process_multiple_images_row(row_data, row_index, return_submission_details=True, actual_audio_data=audio_for_row)
                except Exception as e:
                    self.log_error(f"Error processing multiple images for row {row_index} in _process_zapcap_batch: {str(e)}")
                    self.log_error(traceback.format_exc())
                    self._update_sheet_status(row_index, f"Error in _process_zapcap_batch (static): {str(e)}")
            else:
                self.log_info(f"Row {row_index}: Found {len(animated_links)} animated links. Processing animated videos.")
                try:
                    # Pass the pre-generated audio data to the processing function
                    audio_for_row = row_data.get('audio_data')  # Fixed: changed from 'actual_audio_data' to 'audio_data'
                    submission_details = self._process_multiple_animated_row(row_data, row_index, return_submission_details=True, actual_audio_data=audio_for_row)
                except Exception as e:
                    self.log_error(f"Error processing animated videos for row {row_index} in _process_zapcap_batch: {str(e)}")
                    self.log_error(traceback.format_exc())
                    self._update_sheet_status(row_index, f"Error in _process_zapcap_batch (animated): {str(e)}")
            
            if submission_details and submission_details.get("task_id") and submission_details.get("video_id"):
                total_successful_submissions += 1
                file_name_from_sheet = row_data.get(config.COLUMNS.get('NAME', 'Name'), f"video_row_{row_index}")
                
                task_to_monitor = {
                    "task_id": submission_details["task_id"],
                    "video_id": submission_details["video_id"],
                    "row": row_index, # This is original_row_index
                    "file_name": file_name_from_sheet
                }
                current_zapcap_batch_tasks.append(task_to_monitor)
                self.log_info(f"ZapCap task {task_to_monitor['task_id']} for row {row_index} added to current batch (size: {len(current_zapcap_batch_tasks)}).")

                if len(current_zapcap_batch_tasks) >= ZAPCAP_BATCH_SIZE:
                    self.log_info(f"ZapCap batch reached size {ZAPCAP_BATCH_SIZE}. Monitoring {len(current_zapcap_batch_tasks)} tasks.")
                    # Option 1: Synchronous monitoring
                    self.monitor_tasks_batch(current_zapcap_batch_tasks.copy()) 
                    # Option 2: Asynchronous (Threaded) monitoring - uncomment to use
                    # self.log_info(f"Starting new thread to monitor ZapCap batch of {len(current_zapcap_batch_tasks)} tasks.")
                    # monitor_thread = threading.Thread(
                    #     target=self.monitor_tasks_batch,
                    #     args=(current_zapcap_batch_tasks.copy(),), # Pass a copy
                    #     daemon=True
                    # )
                    # monitor_thread.start()
                    current_zapcap_batch_tasks.clear()
            else:
                self.log_warning(f"No submission details returned for row {row_index} or task/video ID missing. Not added to batch.")

        # After the loop, monitor any remaining tasks in the current batch
        if current_zapcap_batch_tasks:
            self.log_info(f"End of rows. Monitoring remaining {len(current_zapcap_batch_tasks)} ZapCap tasks in the last batch.")
            # Option 1: Synchronous monitoring
            self.monitor_tasks_batch(current_zapcap_batch_tasks)
            # Option 2: Asynchronous (Threaded) monitoring - uncomment to use
            # self.log_info(f"Starting new thread to monitor final ZapCap batch of {len(current_zapcap_batch_tasks)} tasks.")
            # final_monitor_thread = threading.Thread(
            #     target=self.monitor_tasks_batch,
            #     args=(current_zapcap_batch_tasks.copy(),), # Pass a copy
            #     daemon=True
            # )
            # final_monitor_thread.start()
            current_zapcap_batch_tasks.clear() # Clear after starting thread or synchronous call

        self.log_info(f"Finished _process_zapcap_batch. Total successful submissions initiated: {total_successful_submissions} out of {total_attempted_submissions} attempts.")
        # The pending_zapcap_tasks list (self.pending_zapcap_tasks) is no longer populated here.
        # The main run() method's final monitor_tasks_batch call will handle any tasks that might have been added there directly,
        # or if we decide to re-introduce population of self.pending_zapcap_tasks from here (e.g. for failed submissions to retry).
        # For now, each batch is monitored immediately (either sync or async).
        return {'total_successful_submissions': total_successful_submissions, 'total_attempted_submissions': total_attempted_submissions}

    def upload_to_bucket_and_update_sheet(self, local_file_path, row_index, desired_file_name):
        """Uploads a file to GCS and updates the sheet with the URL and status."""
        if not self.bucket:
            self.log_error(f"GCS bucket not initialized. Cannot upload {local_file_path}.")
            self._update_sheet_status(row_index, "Error: GCS bucket not available for upload")
            return False

        if not os.path.exists(local_file_path):
            self.log_error(f"Local file not found for upload: {local_file_path}")
            self._update_sheet_status(row_index, f"Error: Local file {os.path.basename(local_file_path)} not found for GCS upload")
            return False

        try:
            # Sanitize desired_file_name to prevent issues with GCS object names
            # Keep basic characters, replace others with underscore
            safe_file_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', os.path.basename(desired_file_name))
            if not safe_file_name.lower().endswith('.mp4'):
                safe_file_name += ".mp4"
            
            gcs_object_name = f"fb_ui_assets/{safe_file_name}"
            
            blob = self.bucket.blob(gcs_object_name)
            
            self.log_info(f"Uploading file {local_file_path} to GCS as {gcs_object_name}")
            blob.upload_from_filename(local_file_path)
            
            # Make the blob publicly viewable (optional, depends on bucket/project settings and needs)
            # Consider security implications before enabling public access broadly.
            # blob.make_public()
            
            public_url = blob.public_url
            self.log_success(f"File {safe_file_name} uploaded successfully to GCS: {gcs_object_name}")
            self.log_info(f"Public URL: {public_url}")

            # Update Google Sheet with the final URL and status
            url_updated = self._update_sheet_final_url(row_index, public_url)
            status_updated = self._update_sheet_status(row_index, f"Completed: Video uploaded to GCS - {safe_file_name}")
            
            if url_updated and status_updated:
                self.log_success(f"Sheet updated successfully for row {row_index} with GCS URL and status.")
                return True
            else:
                self.log_error(f"Failed to update sheet for row {row_index} after GCS upload.")
                # Even if sheet update fails, the file is in GCS. Consider how to handle this.
                return False # Or True, depending on whether GCS upload alone is considered a success for retry logic

        except Exception as e_upload:
            self.log_error(f"Error during GCS upload or sheet update for row {row_index} (file: {local_file_path}): {str(e_upload)}")
            self.log_error(traceback.format_exc())
            self._update_sheet_status(row_index, f"Error: GCS upload/Sheet update failed - {str(e_upload)}")
            return False

    def _detect_language(self, language_input_str, text_content):
        """
        Detects language from user input or from the text itself.
        """
        self.log_info(f"Detecting language from input: '{language_input_str}'")
        
        # If input is empty, auto-detect based on text
        if not language_input_str:
            # Basic check - if there are more Hebrew letters, it's likely Hebrew
            hebrew_chars = sum(1 for c in text_content if '\u0590' <= c <= '\u05FF')
            if hebrew_chars > len(text_content) * 0.3:  # If more than 30% of characters are Hebrew
                self.log_info("Detected Hebrew language based on text content")
                return "he"
            else:
                self.log_info("Language not clearly detected, using English as default")
                return "en"
        
        # Cleaning and converting to a uniform format
        language_input_cleaned = language_input_str.strip().lower()
        
        # Checking if it's already a valid language code
        if language_input_cleaned in self.language_mapping:
            return language_input_cleaned
            
        # Checking if it's a full language name
        if language_input_cleaned in self.language_names_mapping:
            return self.language_names_mapping[language_input_cleaned]
            
        # Special mappings
        if language_input_cleaned in ['heb', 'hebrew', 'ivrit', 'he-il']:
            return 'he'
        elif language_input_cleaned in ['eng', 'english', 'en-us', 'en-gb']:
            return 'en'
        elif language_input_cleaned in ['spa', 'spanish']:
            return 'es'
        elif language_input_cleaned in ['fre', 'french']:
            return 'fr'
        
        # If not detected, use English as default
        self.log_warning(f"Language not detected from input: {language_input_cleaned}, using English")
        return 'en'
            
    def _select_voice(self, voice_input):
        """
         Selects a voice from user input.
         
         Parameters:
         ----------
         voice_input : str
             Voice input from the user.
             
         Returns:
         -------
         str or bytes
             Voice ID or audio data if it's a URL.
         """
        self.log_info(f"Selecting voice from input: {voice_input}")
        
        # If input is empty, select randomly
        if not voice_input:
            voice_id = random.choice(self.voice_codes)
            self.log_info(f"Random voice selected: {voice_id}")
            return voice_id
            
        # Check if it's a URL to an audio file
        voice_input_lower = voice_input.lower().strip()
        if (voice_input_lower.startswith('http://') or 
            voice_input_lower.startswith('https://') or
            voice_input_lower.endswith('.mp3') or
            voice_input_lower.endswith('.wav') or
            voice_input_lower.endswith('.m4a') or
            voice_input_lower.endswith('.aac')):
            
            self.log_info(f"Voice input is URL, downloading audio: {voice_input}")
            try:
                # Download the audio file
                response = requests.get(voice_input, timeout=60)
                response.raise_for_status()
                
                audio_data = response.content
                if audio_data and len(audio_data) > 1000:
                    self.log_success(f"Successfully downloaded voice audio from URL ({len(audio_data)} bytes)")
                    return audio_data  # Return audio data instead of a voice code
                else:
                    self.log_error(f"Downloaded audio data is too small or empty from URL: {voice_input}")
                    # Fall back to a random voice
                    voice_id = random.choice(self.voice_codes)
                    self.log_info(f"Fallback to random voice: {voice_id}")
                    return voice_id
                    
            except Exception as e:
                self.log_error(f"Error downloading voice audio from URL {voice_input}: {str(e)}")
                # Fall back to a random voice
                voice_id = random.choice(self.voice_codes)
                self.log_info(f"Fallback to random voice: {voice_id}")
                return voice_id
            
        # If there's a voice code, use it directly
        return voice_input
        
    def _submit_to_zapcap(self, text, video_url, language_code, row_index, template_id=""):
        """
        Submits a request to ZapCap to create a video with subtitles.
        
        Parameters:
        ----------
        text : str
            Text for narration and subtitles.
        video_url : str
            Link to an image or video.
        language_code : str
            Language code.
        row_index : int
            Row number in the sheet.
        template_id : str, optional
            Template ID to submit.
            
        Returns:
        -------
        str
            Task ID or None if failed.
        """
        self.log_info(f"Submitting request to ZapCap for row {row_index}")
        
        try:
            # Step 1: Uploading the video using a URL
            upload_url = f"{self.zapcap_base_url}/videos/url"
            headers = {
                "x-api-key": self.zapcap_api_key,
                "Content-Type": "application/json"
            }
            upload_payload = {"url": video_url}

            self.log_info(f"Sending upload request to ZapCap: {upload_url}")
            upload_resp = requests.post(upload_url, headers=headers, json=upload_payload, timeout=60)
            self.log_info(f"Upload response status: {upload_resp.status_code}")

            if upload_resp.status_code != 201:
                self.log_error(f"Upload failed: {upload_resp.text}")
                return None

            video_id = upload_resp.json().get("id")
            if not video_id:
                self.log_error("video_id not returned from upload")
                return None

            # Step 2: Creating a processing task for the video
            task_url = f"{self.zapcap_base_url}/videos/{video_id}/task"
            if not template_id: # Ensure template_id has a value
                template_id_to_use = os.getenv("ZAPCAP_TEMPLATE_ID") or "default-template-id"
            else:
                template_id_to_use = template_id


            task_body = {"templateId": template_id_to_use, "language": language_code, "autoApprove": True}

            self.log_info(f"Creating task in ZapCap: {task_url}")
            task_resp = requests.post(task_url, headers=headers, json=task_body, timeout=120)  # Increased timeout to 120 seconds for ZapCap
            self.log_info(f"Task creation status: {task_resp.status_code}")

            if task_resp.status_code not in [200,201]:
                self.log_error(f"Task creation failed: {task_resp.text}")
                return None

            task_id_response = task_resp.json().get("taskId") or task_resp.json().get("id")
            if task_id_response:
                self.log_success(f"ZapCap task created: {task_id_response} for video {video_id}")
                self._update_sheet_task_id(row_index, "ZapCap Task ID", task_id_response)
                return {"video_id": video_id, "task_id": task_id_response} # Changed: returning an object
            else:
                self.log_error(f"taskId not returned from ZapCap response for video {video_id}")
                return None

        except Exception as e:
            self.log_error(f"Error submitting request to ZapCap: {str(e)}")
            return None

    def _update_sheet_task_id(self, row_index, column, task_id):
        """
        Updates the task ID in the sheet.
        
        Parameters:
        ----------
        row_index : int
            Row number in the sheet.
        column : str
            Name of the column to update.
        task_id : str
            Task ID.
        """
        try:
            # Finding column number by name
            all_values = self.sheet.get_all_values()
            headers = all_values[0]
            
            # Searching for the column in headers
            column_index = -1
            for i, header_name in enumerate(headers):
                if header_name == column:
                    column_index = i
                    break
            
            if column_index == -1:
                # If the column does not exist, try to add it
                column_index = len(headers)
                headers.append(column)
                self.sheet.update_cell(1, column_index + 1, column)
                
            # Update the target cell
            self.sheet.update_cell(row_index, column_index + 1, task_id)
            
            self.log_success(f"Updated task ID in row {row_index}, column {column}: {task_id}")
            return True
            
        except Exception as e:
            self.log_error(f"Error updating the sheet: {str(e)}")
            return False
            
    def monitor_tasks_batch(self, tasks):
        """
        Monitors ZapCap tasks and updates their status.
        
        Parameters:
        ----------
        tasks : list
            List of ZapCap tasks to monitor.
            
        Returns:
        -------
        list
            List of completed tasks.
        """
        if not tasks:
            self.log_warning("No ZapCap tasks to monitor")
            return []
            
        self.log_info(f"Starting to monitor {len(tasks)} ZapCap tasks")
        
        completed_tasks = []
        pending_tasks = tasks.copy()
        
        max_wait_time = 3600  # 60 minutes - significantly increased for better ZapCap task completion time
        check_interval = 10  # 10 seconds
        start_time = time.time()
        
        while pending_tasks and (time.time() - start_time < max_wait_time):
            self.log_info(f"Checking status of {len(pending_tasks)} ZapCap tasks")
            
            still_pending = []
            
            for task_item in pending_tasks:
                task_id = task_item['task_id']
                row_index = task_item['row']
                video_id = task_item.get('video_id')
                file_name_for_bucket = task_item.get('file_name', f"zapcap_video_{task_id}") # Get the file name
                
                self.log_info(f"Checking status of task {task_id} (row {row_index}, video {video_id}), target file name: {file_name_for_bucket}")
                
                # Check status
                if not video_id: # If there is no video_id, use the function that checks by task_id only
                    self.log_info(f"No video_id for task {task_id} in row {row_index}. Checking status by task_id only.")
                    status_data = self._check_zapcap_status_by_task_id(task_id)
                else:
                    status_data = self._check_zapcap_status(video_id, task_id)
                
                if not status_data:
                    self.log_error(f"Failed to get status for task {task_id} (video {video_id})")
                    still_pending.append(task_item)
                    continue
                    
                status = status_data.get('status')
                
                if status == 'completed':
                    video_url = status_data.get('video_url') or status_data.get('downloadUrl')
                    if video_url:
                        self.log_success(f"Task completed successfully: {task_id}")
                        
                        # Download the finished video
                        try:
                            self.log_info(f"Downloading video from {video_url} for task {task_id}")
                            r = requests.get(video_url, timeout=300)  # Increased timeout to 5 minutes
                            r.raise_for_status()
                            
                            # Use tempfile to avoid collisions
                            import tempfile
                            with tempfile.NamedTemporaryFile(suffix=".mp4", dir=self.temp_dir, delete=False) as temp_file:
                                temp_file.write(r.content)
                                temp_local = temp_file.name
                            
                            self.log_success(f"Downloaded video {task_id} ({len(r.content)//1024} KB) to file {temp_local}")

                            # Upload to bucket + update the sheet
                            upload_success = self.upload_to_bucket_and_update_sheet(temp_local, row_index, file_name_for_bucket)
                            
                            # Clean up temporary file
                            try:
                                os.remove(temp_local)
                                self.log_info(f"Cleaned up temporary file {temp_local}")
                            except Exception as e_cleanup:
                                self.log_warning(f"Error cleaning up temporary file {temp_local}: {e_cleanup}")
                            
                            if upload_success:
                                # Clear ZapCap Task ID and Status from the sheet after success
                                try:
                                    zapcap_task_col = config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID')
                                    col_letter = self._get_column_letter(zapcap_task_col)
                                    if col_letter:
                                        cell_range = f"{col_letter}{row_index}"
                                        self.sheet.update(cell_range, [[""]])
                                    
                                    status_col = config.COLUMNS.get('STATUS', 'Status')
                                    col_letter = self._get_column_letter(status_col)
                                    if col_letter:
                                        cell_range = f"{col_letter}{row_index}"
                                        self.sheet.update(cell_range, [[""]])
                                        
                                    self.log_info(f"Cleared ZapCap Task ID and Status for row {row_index}")
                                except Exception as e_clear:
                                    self.log_error(f"Error clearing ZapCap columns for row {row_index}: {e_clear}")
                                
                                completed_tasks.append({
                                    "task_id": task_id,
                                    "video_id": video_id,
                                    "row": row_index,
                                    "file_name": file_name_for_bucket,
                                    "video_url": video_url
                                })
                            else:
                                self.log_error(f"Upload and sheet update failed for downloaded video {task_id}. Will retry later.")
                                still_pending.append(task_item) # Re-add to pending if upload/sheet update fails

                        except Exception as dl_err:
                            self.log_error(f"Error downloading/uploading video {task_id} (video {video_id}): {dl_err}")
                            self.log_error(traceback.format_exc())
                            still_pending.append(task_item) # Re-add to pending if download/upload fails
                    else:
                        self.log_error(f"Task completed but no video URL: {task_id} (video {video_id})")
                        self.log_error(f"Status response: {status_data}")
                        still_pending.append(task_item) # Re-add to pending
                        
                elif status == 'failed':
                    self.log_error(f"Task failed: {task_id} (video {video_id}) in row {row_index}")
                    # IMPORTANT: Keep the Task ID even for failed tasks - give them another chance in future runs
                    # Sometimes ZapCap reports "failed" temporarily but tasks can recover
                    self._update_sheet_status(row_index, f"ZapCap Failed: Task {task_id} - preserving for future retry")
                    self.log_info(f"Keeping Task ID {task_id} for row {row_index} despite failure - will be checked again in the next run")
                    # Do NOT clear the ZapCap Task ID - let future runs check it again
                    # Do not re-add failed tasks to pending list - let future runs handle them
                    
                elif status == 'not_found':
                    self.log_warning(f"Task not found in ZapCap: {task_id} (video {video_id}) in row {row_index}")
                    # IMPORTANT: DON'T clear Task ID - preserve it for future runs!
                    self._update_sheet_status(row_index, f"ZapCap task not found: {task_id} - preserving for future retry")
                    self.log_info(f"Keeping Task ID {task_id} for row {row_index} to be checked in future runs")
                    
                    # Do NOT try to recreate immediately - preserve the Task ID for future runs
                    # The task might appear later or might still be processing
                    # Future runs will check this Task ID again
                    # Do not re-add to pending list - let future runs handle it
                    
                else: # status is 'processing' or other
                    self.log_info(f"Task still processing ({status}): {task_id} (video {video_id})")
                    still_pending.append(task_item)
            
            pending_tasks = still_pending
            
            if pending_tasks:
                progress = f"{len(completed_tasks)}/{len(tasks)} tasks completed"
                self.log_info(f"{progress}, waiting {check_interval} seconds before the next check...")
                time.sleep(check_interval)
                
                # Increase the check interval if it takes a long time
                if time.time() - start_time > 180:  # After 3 minutes
                    check_interval = min(int(check_interval * 1.5), 60)  # Gradual increase up to 60 seconds
        
        # Check if time ran out
        if pending_tasks:
            self.log_warning(f"Wait time expired, {len(pending_tasks)} tasks still processing")
            
        self.log_info(f"Completed {len(completed_tasks)} out of {len(tasks)} ZapCap tasks")
        return completed_tasks
        
    def _check_zapcap_status(self, video_id, task_id):
        """
        Checks task status in ZapCap.
        
        Parameters:
        ----------
        video_id : str
            Video ID in ZapCap.
        task_id : str
            Task ID.
            
        Returns:
        -------
        dict
            Information about the task status.
        """
        self.log_info(f"Checking ZapCap task status {task_id} for video {video_id}")
        
        # Endpoint structure for ZapCap task status based on provided documentation:
        # GET /videos/{videoId}/task/{id}
        url = f"{self.zapcap_base_url}/videos/{video_id}/task/{task_id}"
        
        headers = {
            "x-api-key": self.zapcap_api_key 
        }
            
        try:
            response = requests.get(url, headers=headers, timeout=120)  # Increased timeout to 120 seconds for ZapCap
            
            # Checking if the API returned a client error (like 404) or server error
            if response.status_code == 404:
                self.log_error(f"Error 404 - Resource not found: {url}")
                self.log_error(f"Response content: {response.text}")
                return None # Or other handling as needed
            elif response.status_code != 200:
                self.log_error(f"Error checking status: {response.status_code} - {response.text}")
                return None
                
            result = response.json()
            self.log_info(f"Response from ZapCap status check ({video_id}/{task_id}): {result}")
            
            # Mapping ZapCap status to a uniform format
            # According to the documentation, the field is 'status' and the values are:
            # "pending", "transcribing", "transcriptionCompleted", "rendering", "completed", "failed"
            zapcap_status = result.get('status', '').lower()
            
            if zapcap_status == 'completed':
                status = 'completed'
            elif zapcap_status in ["pending", "transcribing", "transcriptioncompleted", "rendering"]: # transcriptionCompleted without a space
                status = 'processing'
            elif zapcap_status == "failed":
                status = 'failed'
            else:
                status = zapcap_status # If there's an unrecognized status, keep it as is
                self.log_warning(f"Unrecognized ZapCap status: {zapcap_status} for task {task_id}")
                
            response_data = {
                'status': status
            }
            
            # If completed, add the video URL
            # According to the documentation, the field is 'downloadUrl'
            if status == 'completed':
                video_url = result.get('downloadUrl') 
                if video_url:
                    response_data['video_url'] = video_url
                else:
                    self.log_warning(f"Task {task_id} completed but downloadUrl not found in response: {result}")
                    # In this case, we might want to return a 'failed' or 'processing' status to try again
                    # For now, leave it as 'completed' but without a URL
                    
            return response_data
            
        except requests.exceptions.RequestException as e: # Handling network errors
            self.log_error(f"Network error checking ZapCap status ({video_id}/{task_id}): {str(e)}")
            return None
        except ValueError as e: # Handling JSON errors
            self.log_error(f"JSON error decoding ZapCap status response ({video_id}/{task_id}): {str(e)}")
            self.log_error(f"Response content that caused the error: {response.text if 'response' in locals() else 'No response object'}")
            return None
        except Exception as e:
            self.log_error(f"General error checking ZapCap status ({video_id}/{task_id}): {str(e)}")
            return None

    def _check_zapcap_status_by_task_id(self, task_id):
        """
        Check ZapCap task status using only task_id (for existing tasks from sheet).
        
        Parameters:
        ----------
        task_id : str
            Task ID to check.
            
        Returns:
        -------
        dict
            Task status information.
        """
        if not task_id:
            self.log_error(f"Missing task_id for status check")
            return None
        
        self.log_info(f"Checking ZapCap task status by task_id only: {task_id}")
        
        # According to ZapCap API documentation, we need to find the video ID first
        # Let's try to get all videos and find the one with our task ID
        headers = {
            "x-api-key": self.zapcap_api_key 
        }
        
        try:
            # First, try to get all videos to find the video ID for our task
            videos_url = f"{self.zapcap_base_url}/videos"
            self.log_info(f"Getting all videos to find video ID for task {task_id}")
            
            # Try multiple pages to find the task
            video_id = None
            for page in range(1, 11):  # Check first 10 pages
                page_videos_url = videos_url
                if page > 1:
                    page_videos_url += f"?page={page}"
                    
                self.log_info(f"Searching page {page} for task {task_id}: {page_videos_url}")
                videos_response = requests.get(page_videos_url, headers=headers, timeout=120)
                
                if videos_response.status_code == 200:
                    videos_data = videos_response.json()
                    videos = videos_data.get('data', []) if isinstance(videos_data, dict) else videos_data
                    
                    if not videos:
                        self.log_info(f"No videos found on page {page}, stopping search")
                        break
                    
                    self.log_info(f"Page {page}: Found {len(videos)} videos")
                    
                    # Look for our task ID in the videos
                    if isinstance(videos, list):
                        for video in videos:
                            if isinstance(video, dict):
                                # Check if this video has our task ID
                                video_tasks = video.get('tasks', [])
                                if isinstance(video_tasks, list):
                                    for task in video_tasks:
                                        if isinstance(task, dict) and task.get('id') == task_id:
                                            video_id = video.get('id')
                                            self.log_info(f"Found video ID {video_id} for task {task_id} on page {page}")
                                            break
                                if video_id:
                                    break
                    if video_id:
                        break
                else:
                    self.log_warning(f"Failed to get videos page {page}: {videos_response.status_code}")
                    break
                
                # If we found the video ID, use the correct API endpoint
                if video_id:
                    correct_url = f"{self.zapcap_base_url}/videos/{video_id}/task/{task_id}"
                    self.log_info(f"Using correct API endpoint: {correct_url}")
                    
                    task_response = requests.get(correct_url, headers=headers, timeout=120)
                    if task_response.status_code == 200:
                        result = task_response.json()
                        self.log_info(f"Response from ZapCap status check (correct endpoint): {result}")
                        
                        # Map ZapCap status to a uniform format
                        zapcap_status = result.get('status', '').lower()
                        
                        if zapcap_status == 'completed':
                            status = 'completed'
                        elif zapcap_status in ["pending", "transcribing", "transcriptioncompleted", "rendering"]:
                            status = 'processing'
                        elif zapcap_status == "failed":
                            status = 'failed'
                        else:
                            status = zapcap_status
                            self.log_warning(f"Unrecognized ZapCap status: {zapcap_status} for task {task_id}")
                            
                        response_data = {
                            'status': status,
                            'video_id': video_id
                        }
                        
                        # If completed, add the video URL
                        if status == 'completed':
                            video_url = result.get('downloadUrl') 
                            if video_url:
                                response_data['video_url'] = video_url
                                response_data['downloadUrl'] = video_url
                            else:
                                self.log_warning(f"Task {task_id} completed but downloadUrl not found in response: {result}")
                                
                        return response_data
                    else:
                        self.log_warning(f"Error checking task status at correct endpoint: {task_response.status_code} - {task_response.text}")
                else:
                    self.log_warning(f"Could not find video ID for task {task_id} in videos list")
            else:
                self.log_warning(f"Error getting videos list: {videos_response.status_code} - {videos_response.text}")
        except Exception as e_correct_api:
            self.log_warning(f"Error using correct API approach: {e_correct_api}")
        
        # Fallback: Try multiple possible endpoints for task status - EXPANDED ENDPOINTS
        possible_urls = [
            # Standard API endpoints
            f"{self.zapcap_base_url}/api/v1/tasks/{task_id}",
            f"{self.zapcap_base_url}/tasks/{task_id}",
            f"{self.zapcap_base_url}/task/{task_id}",
            # Alternative API structures based on real API behavior
            f"{self.zapcap_base_url}/api/tasks/{task_id}",
            f"{self.zapcap_base_url}/v1/tasks/{task_id}",
            # Try task monitoring endpoints
            f"{self.zapcap_base_url}/api/v1/monitoring/tasks/{task_id}",
            f"{self.zapcap_base_url}/monitoring/tasks/{task_id}",
            # Try with different path structures
            f"{self.zapcap_base_url}/videos/tasks/{task_id}",
            f"{self.zapcap_base_url}/api/videos/tasks/{task_id}",
        ]
        
        headers = {
            "x-api-key": self.zapcap_api_key 
        }
        
        for url in possible_urls:
            try:
                self.log_info(f"Trying endpoint: {url}")
                response = requests.get(url, headers=headers, timeout=120)  # Increased timeout to 120 seconds for ZapCap
                
                if response.status_code == 200:
                    result = response.json()
                    self.log_info(f"Response from ZapCap status check (task only {task_id}): {result}")
                    
                    # Map ZapCap status to a uniform format
                    zapcap_status = result.get('status', '').lower()
                    
                    if zapcap_status == 'completed':
                        status = 'completed'
                    elif zapcap_status in ["pending", "transcribing", "transcriptioncompleted", "rendering"]:
                        status = 'processing'
                    elif zapcap_status == "failed":
                        status = 'failed'
                    else:
                        status = zapcap_status
                        self.log_warning(f"Unrecognized ZapCap status: {zapcap_status} for task {task_id}")
                        
                    response_data = {
                        'status': status
                    }
                    
                    # If completed, add the video URL
                    if status == 'completed':
                        video_url = result.get('downloadUrl') 
                        if video_url:
                            response_data['video_url'] = video_url
                        else:
                            self.log_warning(f"Task {task_id} completed but downloadUrl not found in response: {result}")
                            
                    return response_data
                
                elif response.status_code == 404:
                    self.log_info(f"Task {task_id} not found at endpoint: {url}")
                    continue  # Try next endpoint
                else:
                    self.log_warning(f"Error checking status at {url}: {response.status_code} - {response.text}")
                    continue  # Try next endpoint
                    
            except requests.exceptions.RequestException as e:
                self.log_warning(f"Network error checking ZapCap status at {url}: {str(e)}")
                continue  # Try next endpoint
            except ValueError as e:
                self.log_warning(f"JSON error decoding ZapCap status response from {url}: {str(e)}")
                continue  # Try next endpoint
            except Exception as e:
                self.log_warning(f"General error checking ZapCap status at {url}: {str(e)}")
                continue  # Try next endpoint
        
        # If all endpoints failed
        self.log_warning(f"Task {task_id} not found in ZapCap using any endpoint - task may have been deleted or never existed")
        return {"status": "not_found"}

    def _update_sheet_final_url(self, row_index, video_url):
        """
        Updates the final video URL in the sheet.
        
        Parameters:
        ----------
        row_index : int
            Row number in the sheet.
        video_url : str
            Final video URL.
        """
        return self._update_sheet_animated_url(row_index, config.COLUMNS.get('FINAL_VIDEO_URL', "Final Video url"), video_url)

    def _update_sheet_status(self, row_index, status_message, column_name=None):
        """
        Updates the status of a row in the Google Sheet.
        
        Parameters:
        ----------
        row_index : int
            The sheet row number to update (1-indexed, but gspread uses 1-indexed for actual data rows after header).
        status_message : str
            The status message to set for the row.
        column_name : str, optional
            The name of the column to update. If None, the status column named 'Status' (case-insensitive) is used.
            If the specified column or default 'Status' column doesn't exist, it will be created.
        """
        try:
            headers = self.sheet.row_values(1) # Get header row to find column index
            
            target_column_name = column_name
            if target_column_name is None:
                # Try to find a default 'Status' column, case-insensitive
                default_status_col_name = config.COLUMNS.get('STATUS', 'Status') # Get from config or default to 'Status'
                found_status_col = False
                for h in headers:
                    if h.strip().lower() == default_status_col_name.strip().lower():
                        target_column_name = h # Use the exact header name found
                        found_status_col = True
                        break
                if not found_status_col:
                    target_column_name = default_status_col_name # Use the default/config name if not found, it will be created
            
            col_index_1_based = -1
            for i, header in enumerate(headers):
                if header.strip().lower() == target_column_name.strip().lower():
                    col_index_1_based = i + 1
                    break
            
            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            full_status_message = f"{current_time_str} - {status_message}"

            if col_index_1_based != -1:
                self.sheet.update_cell(row_index, col_index_1_based, full_status_message)
                self.log_info(f"Sheet status updated for row {row_index}, column '{target_column_name}': {full_status_message}")
            else:
                # Column doesn't exist, try to add it at the end and then update
                self.log_info(f"Column '{target_column_name}' not found. Attempting to add it.")
                new_col_index_1_based = len(headers) + 1
                self.sheet.update_cell(1, new_col_index_1_based, target_column_name) # Add header for the new column
                self.sheet.update_cell(row_index, new_col_index_1_based, full_status_message) # Update the cell in the new column
                self.log_success(f"Created column '{target_column_name}' and updated status for row {row_index}: {full_status_message}")
            return True

        except gspread.exceptions.APIError as ge:
            self.log_error(f"Google Sheets API error updating status for row {row_index}: {str(ge)}")
            self.log_error(traceback.format_exc())
            return False
        except Exception as e:
            self.log_error(f"General error updating sheet status for row {row_index}: {str(e)}")
            self.log_error(traceback.format_exc())
            return False

    def cleanup_temp_files(self):
        """
        Cleans up temporary files.
        """
        self.log_info("Cleaning up temporary files")
        
        try:
            # Delete all files in the temp directory
            for file_to_remove in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file_to_remove)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        self.log_info(f"Deleted temporary file: {file_to_remove}")
                except Exception as e:
                    self.log_error(f"Error deleting temporary file {file_to_remove}: {str(e)}")
                    
            self.log_success("Temporary file cleanup completed")
            
        except Exception as e:
            self.log_error(f"Error cleaning up temporary files: {str(e)}")
            
    def _get_random_bg_music_path(self):
        """
        Returns a random background music file path from the BG MUSIC directory.
        
        Returns:
        -------
        str or None
            Path to a random MP3 file from BG MUSIC directory, or None if no files available.
        """
        if not self.bg_music_files:
            self.log_info("No background music files available.")
            return None
        
        random_bg_file = random.choice(self.bg_music_files)
        bg_music_path = os.path.join(self.bg_music_dir, random_bg_file)
        
        if os.path.exists(bg_music_path):
            self.log_info(f"Selected background music: {random_bg_file}")
            return bg_music_path
        else:
            self.log_warning(f"Selected background music file does not exist: {bg_music_path}")
            return None
            
    def combine_videos_with_effects(self, video_sources, audio_data=None, zoom_effect=False, aspect_ratio="9:16"):
        """
        Combines videos or images with effects.
        
        Parameters:
        ----------
        video_sources : list
            List of video sources (URLs or file data).
        audio_data : bytes, optional
            Audio data to add to the video.
        zoom_effect : bool, default=False
            Whether to apply a zoom effect to each segment.
        aspect_ratio : str, default="9:16"
            Aspect ratio of the video ("9:16" or "1:1").
            
        Returns:
        -------
        bytes
            Combined video data.
        """
        self.log_info(f"Combining {len(video_sources)} videos/images with effects")
        self.log_info(f"Zoom effect: {zoom_effect}, aspect ratio: {aspect_ratio}")
        
        if len(video_sources) == 0:
            self.log_error("No video sources provided")
            return None
            
        # Check if there is audio to add and measure its duration
        audio_duration = None
        temp_audio_for_probe = None # Initialize variable for NamedTemporaryFile

        if audio_data:
            self.log_info(f"combine_videos_with_effects: Received audio_data with size: {len(audio_data)} bytes.")
            try:
                # Create a temporary file in self.temp_dir for ffprobe
                # Ensure self.temp_dir is an absolute path
                if not os.path.isabs(self.temp_dir):
                     self.temp_dir = os.path.abspath(self.temp_dir)
                     if not os.path.exists(self.temp_dir):
                         os.makedirs(self.temp_dir)
                
                with tempfile.NamedTemporaryFile(suffix=".mp3", dir=self.temp_dir, delete=False) as tmp_f:
                    tmp_f.write(audio_data)
                    temp_audio_for_probe = tmp_f.name
                
                self.log_info(f"Temporary audio file for ffprobe: {temp_audio_for_probe}")

                import subprocess
                probe_command = [
                    'ffprobe', '-v', 'error', 
                    '-show_entries', 'format=duration', 
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    temp_audio_for_probe # Use the named temporary file
                ]
                
                audio_duration_str = subprocess.check_output(probe_command, stderr=subprocess.DEVNULL).decode('utf-8').strip()
                if audio_duration_str:
                    audio_duration = float(audio_duration_str)
                    self.log_info(f"VO Audio duration measured by ffprobe: {audio_duration} seconds.")
                else:
                    self.log_warning("ffprobe did not return a duration for the VO audio.")
                    audio_duration = None # Ensure it's None if ffprobe fails

            except Exception as e_ffprobe:
                self.log_warning(f"Could not measure VO audio duration using ffprobe: {str(e_ffprobe)}")
                self.log_error(traceback.format_exc())
                audio_duration = None # Ensure it's None on error
            finally:
                # Clean up the temporary file for ffprobe if it was created
                if temp_audio_for_probe and os.path.exists(temp_audio_for_probe):
                    try:
                        os.remove(temp_audio_for_probe)
                        self.log_info(f"Cleaned up temporary ffprobe audio file: {temp_audio_for_probe}")
                    except Exception as e_remove:
                        self.log_warning(f"Error cleaning up temporary ffprobe audio file: {e_remove}")
        else:
            self.log_info("combine_videos_with_effects: No audio_data (VO) received.")
        
        # Checking if video sources exist
        if not video_sources:
            self.log_error("No video sources provided")
            return None
            
        # Determine video size
        if aspect_ratio == "1:1":
            width, height = 1080, 1080
        else:  # 9:16
            width, height = 1080, 1920
            
        self.log_info(f"Video size: {width}x{height}")
        
        # Choose processing method - MoviePy by default (nicer cross-fade transitions)
        # ffmpeg is used only if MoviePy is unavailable (minimal runtime environment).
        try:
            import moviepy
            # Pass the determined audio_duration to _combine_videos_moviepy
            return self._combine_videos_moviepy(video_sources, audio_data, zoom_effect, width, height, audio_duration=audio_duration)
        except ImportError:
            self.log_warning("MoviePy unavailable - falling back to ffmpeg (hard transitions)")
            # Pass the determined audio_duration to _combine_videos_ffmpeg
            return self._combine_videos_ffmpeg(video_sources, audio_data, zoom_effect, width, height, audio_duration=audio_duration)
            
    def _combine_videos_moviepy(self, video_sources, audio_data=None, zoom_effect=False, width=1080, height=1920, audio_duration=None):
        self.log_info(f"_combine_videos_moviepy: Starting. Received audio_data: {'Yes' if audio_data else 'No'}, Size: {len(audio_data) if audio_data else 'N/A'} bytes. Received audio_duration: {audio_duration}")
        
        process_id = str(uuid.uuid4())[:8]
        thread_id = threading.current_thread().name.replace("-", "_")
        # process_temp_dir is already an absolute path because self.temp_dir is absolute
        process_temp_dir = os.path.join(self.temp_dir, f"process_{process_id}_{thread_id}")
        os.makedirs(process_temp_dir, exist_ok=True)
        self.log_info(f"Using specific temp directory for this MoviePy task: {process_temp_dir}")
        
        safety_margin = 0.05
        # original_cwd = os.getcwd() # No longer needed
        
        final_video_data = None # Initialize to ensure it's always defined

        try:
            # os.chdir(process_temp_dir) # REMOVED: We will use absolute paths instead
            
            from moviepy.editor import VideoFileClip, ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
            from moviepy.video.fx import all as vfx
            
            clips = []
            target_w_float, target_h_float = float(width), float(height)

            for i, source_item in enumerate(video_sources):
                # First save to temporary file to check actual content type
                temp_file_abs = os.path.join(process_temp_dir, f"temp_{i}.dat")
                
                if isinstance(source_item, str) and (source_item.startswith('http://') or source_item.startswith('https://')):
                    self.log_info(f"Downloading source {i+1} from {source_item}")
                    response = requests.get(source_item, timeout=60)
                    if response.status_code != 200:
                        self.log_error(f"Error downloading source {i+1}: {response.status_code}")
                        continue
                    source_data = response.content
                else:
                    source_data = source_item
                
                # Ensure source_data is bytes
                if isinstance(source_data, str):
                    source_data = source_data.encode('utf-8')
                
                # Save to temporary file first
                with open(temp_file_abs, 'wb') as f:
                    f.write(source_data)
                    
                # Check actual content type and rename with proper extension
                is_image = self._is_image_file(temp_file_abs)
                
                if is_image:
                    source_file_abs = os.path.join(process_temp_dir, f"source_{i}.jpg")
                    self.log_info(f"Source {i+1} detected as image, saving as: {source_file_abs}")
                else:
                    source_file_abs = os.path.join(process_temp_dir, f"source_{i}.mp4")
                    self.log_info(f"Source {i+1} detected as video, saving as: {source_file_abs}")
                
                # Rename temp file to final name
                try:
                    os.rename(temp_file_abs, source_file_abs)
                except Exception as rename_err:
                    self.log_warning(f"Cannot rename file: {rename_err}, using temp file")
                    source_file_abs = temp_file_abs
                
                current_clip = None
                if is_image:
                    self.log_info(f"Processing image {i+1} ({source_file_abs}) into a clip")
                    current_clip = ImageClip(source_file_abs) # Use absolute path
                    current_clip = current_clip.set_duration(3)
                    if zoom_effect:
                        self.log_info(f"Applying zoom effect to image {i+1} (pre-scaling)")
                        current_clip = current_clip.resize(1.2)
                else:
                    self.log_info(f"Processing video {i+1} ({source_file_abs})")
                    current_clip = VideoFileClip(source_file_abs) # Use absolute path
                
                if current_clip: # ... (rest of the clip processing logic remains the same)
                    orig_w, orig_h = current_clip.size
                    self.log_info(f"Source clip {i+1}: original dimensions {orig_w}x{orig_h}")
                    source_aspect_ratio = orig_w / orig_h
                    target_aspect_ratio = target_w_float / target_h_float
                    if source_aspect_ratio > target_aspect_ratio:
                        temp_h = target_h_float
                        temp_w = temp_h * source_aspect_ratio
                    else:
                        temp_w = target_w_float
                        temp_h = temp_w / source_aspect_ratio
                    current_clip = current_clip.resize(width=int(round(temp_w)), height=int(round(temp_h)))
                    self.log_info(f"Clip {i+1}: dimensions after resize-to-cover {current_clip.w}x{current_clip.h}")
                    current_clip = vfx.crop(current_clip, 
                                            width=int(target_w_float), 
                                            height=int(target_h_float), 
                                            x_center=current_clip.w/2, 
                                            y_center=current_clip.h/2)
                    self.log_info(f"Clip {i+1}: dimensions after crop {current_clip.w}x{current_clip.h}")
                    if zoom_effect:
                        self.log_info(f"Applying zoom effect to clip {i+1}")
                        def zoom(t):
                            return 1.0 + (0.3 * t / current_clip.duration)
                        current_clip = current_clip.resize(lambda t: zoom(t))
                        self.log_info(f"Clip {i+1}: zoom effect applied")
                    else:
                        current_clip = current_clip.resize(width=int(target_w_float), height=int(target_h_float))
                        self.log_info(f"Clip {i+1}: final dimensions after last resize {current_clip.w}x{current_clip.h}")
                    clips.append(current_clip)
                else:
                    self.log_warning(f"Skipping source {i+1} due to clip creation failure.")

            if not clips:
                self.log_error("No clips to process")
                return None
                
            self.log_info(f"Combining {len(clips)} clips with dissolve transitions (0.5s)")
            fade_duration = 0.5
            clips_cf = [clips[0]]
            for c_item in clips[1:]:
                clips_cf.append(c_item.crossfadein(fade_duration))
            final_clip_obj = concatenate_videoclips(clips_cf, method="compose")
            
            video_duration = final_clip_obj.duration
            self.log_info(f"Original video duration: {video_duration} seconds")
            
            audio_clip_obj = None # Initialize to ensure it's defined for finally block
            final_audio_to_set = None # Will hold the final audio (VO, BG, or composite)

            if audio_data: # If there is voice-over data
                self.log_info("_combine_videos_moviepy: Processing VO data (TEST MODE - BG MUSIC DISABLED).")
                audio_vo_mp3_path = os.path.join(process_temp_dir, "audio_vo_original.mp3") 
                with open(audio_vo_mp3_path, 'wb') as f:
                    f.write(audio_data)
                
                # Step 1: Load the original MP3 VO clip
                try:
                    original_vo_clip = AudioFileClip(audio_vo_mp3_path)
                    self.log_info(f"_combine_videos_moviepy: Original MP3 VO clip loaded. Duration: {original_vo_clip.duration} seconds.")

                    # Step 2: Explicitly write it to a WAV file
                    audio_vo_wav_path = os.path.join(process_temp_dir, "audio_vo_converted.wav")
                    self.log_info(f"_combine_videos_moviepy: Writing original VO to WAV: {audio_vo_wav_path}")
                    original_vo_clip.write_audiofile(audio_vo_wav_path, codec='pcm_s16le') # Standard WAV codec
                    self.log_info(f"_combine_videos_moviepy: Successfully wrote VO to WAV.")
                    
                    # FFprobe check on the newly created WAV file
                    if os.path.exists(audio_vo_wav_path):
                        try:
                            probe_wav_command = [
                                'ffprobe', '-v', 'error',
                                '-show_entries', 'stream=codec_name,channels,sample_rate,duration,bit_rate', 
                                '-of', 'default=noprint_wrappers=1',
                                audio_vo_wav_path
                            ]
                            self.log_info(f"Running ffprobe on converted WAV file: {' '.join(probe_wav_command)}")
                            probe_wav_output = subprocess.check_output(probe_wav_command, stderr=subprocess.STDOUT).decode('utf-8').strip()
                            if probe_wav_output:
                                self.log_info(f"ffprobe WAV stream info for {audio_vo_wav_path}:\n{probe_wav_output}")
                            else:
                                self.log_warning(f"ffprobe found NO stream info in converted WAV {audio_vo_wav_path}")
                        except subprocess.CalledProcessError as e_probe_wav:
                            self.log_error(f"ffprobe check on WAV failed for {audio_vo_wav_path}. Code: {e_probe_wav.returncode}\nOutput: {e_probe_wav.output.decode('utf-8', errors='ignore')}")
                        except Exception as e_probe_wav_general:
                            self.log_error(f"General error during ffprobe WAV check for {audio_vo_wav_path}: {e_probe_wav_general}")
                    else:
                        self.log_warning(f"Converted WAV file {audio_vo_wav_path} not found for ffprobe check.")

                    original_vo_clip.close() # Close the original mp3 clip

                    # Step 3: Load the VO from the newly created WAV file
                    vo_clip = AudioFileClip(audio_vo_wav_path)
                    self.log_info(f"_combine_videos_moviepy: VO clip re-loaded from WAV. Duration: {vo_clip.duration} seconds.")

                    # Amplify VO slightly
                    vo_clip = vo_clip.volumex(1.15) # Amplify VO by 15%
                    self.log_info(f"_combine_videos_moviepy: VO volume amplified by 15%. New duration: {vo_clip.duration}")

                except Exception as e_vo_conversion:
                    self.log_error(f"_combine_videos_moviepy: Error during VO MP3->WAV conversion or loading: {e_vo_conversion}")
                    self.log_error(traceback.format_exc())
                    # Fallback: try using the original mp3 clip if WAV conversion failed
                    if 'original_vo_clip' in locals() and original_vo_clip:
                         self.log_warning("_combine_videos_moviepy: Falling back to using original MP3 VO clip due to WAV conversion error.")
                         vo_clip = original_vo_clip # Already loaded
                    elif os.path.exists(audio_vo_mp3_path): # If original_vo_clip object doesn't exist but file does
                        try:
                            vo_clip = AudioFileClip(audio_vo_mp3_path)
                            self.log_warning("_combine_videos_moviepy: Re-loaded original MP3 VO clip as fallback.")
                        except Exception as e_fallback_load:
                            self.log_error(f"_combine_videos_moviepy: Failed to load even the original MP3 as fallback: {e_fallback_load}")
                            audio_clip_obj = None # Ensure this is None
                            final_audio_to_set = None
                            # Skip further audio processing for this clip if VO cannot be loaded
                            pass # Will proceed to the 'else' for 'if audio_data'
                    else:
                        self.log_error("_combine_videos_moviepy: VO MP3 file does not exist, cannot proceed with audio.")
                        audio_clip_obj = None
                        final_audio_to_set = None
                        pass
                
                if 'vo_clip' in locals() and vo_clip: # Check if vo_clip was successfully loaded/created
                    if audio_duration is None: 
                        audio_duration = vo_clip.duration 
                        self.log_warning(f"_combine_videos_moviepy: audio_duration (from ffprobe) was None. Using VO clip's (WAV or MP3) own duration: {audio_duration}")
                    
                    safety_margin = min(0.05, audio_duration * 0.01) if audio_duration else 0.05
                    safe_audio_duration = max(0.1, (audio_duration - safety_margin) if audio_duration else vo_clip.duration - safety_margin) 
                    self.log_info(f"_combine_videos_moviepy: Target safe_audio_duration for VO: {safe_audio_duration} seconds.")

                    # BG MUSIC ENABLED AGAIN
                    final_audio_list_for_composite = [vo_clip.set_duration(safe_audio_duration)]

                    bg_music_path = self._get_random_bg_music_path()
                    if bg_music_path:
                        self.log_info(f"_combine_videos_moviepy: Attempting to add background music from: {bg_music_path}")
                        try:
                            bg_music_clip = AudioFileClip(bg_music_path)
                            self.log_info(f"_combine_videos_moviepy: BG music clip loaded. Original duration: {bg_music_clip.duration} seconds.")
                            
                            bg_music_clip = bg_music_clip.volumex(0.08) # Lowered BG music to 8%
                            self.log_info(f"_combine_videos_moviepy: BG music volume adjusted to 0.08.")
                            
                            if bg_music_clip.duration > safe_audio_duration:
                                bg_music_clip = bg_music_clip.subclip(0, safe_audio_duration)
                                self.log_info(f"_combine_videos_moviepy: BG music SUBCLIPPED to {safe_audio_duration} seconds.")
                            else:
                                bg_music_clip = bg_music_clip.loop(duration=safe_audio_duration)
                                self.log_info(f"_combine_videos_moviepy: BG music LOOPED to {safe_audio_duration} seconds.")
                            
                            fade_duration_bg = min(1.5, bg_music_clip.duration * 0.1)
                            if bg_music_clip.duration > fade_duration_bg and fade_duration_bg > 0:
                                 bg_music_clip = bg_music_clip.audio_fadeout(fade_duration_bg)
                                 self.log_info(f"_combine_videos_moviepy: BG music FADEOUT applied for {fade_duration_bg} seconds.")
                            else:
                                self.log_info("_combine_videos_moviepy: BG music fadeout skipped (clip too short or fade_duration_bg is zero).")

                            final_audio_list_for_composite.append(bg_music_clip)
                            self.log_info(f"_combine_videos_moviepy: BG music processed and added for composition.")

                        except Exception as e_bg_music:
                            self.log_error(f"_combine_videos_moviepy: Error processing background music: {e_bg_music}. Proceeding with VO only (if available).")
                            self.log_error(traceback.format_exc())
                            # BG music processing failed, vo_clip (if exists) is already in final_audio_list_for_composite
                    else:
                        self.log_info("_combine_videos_moviepy: No background music selected/available. Proceeding with VO only (if available).")
                    
                    if final_audio_list_for_composite:
                        if len(final_audio_list_for_composite) > 1:
                             self.log_info(f"_combine_videos_moviepy: Preparing to composite {len(final_audio_list_for_composite)} audio clips.")
                             final_audio_to_set = CompositeAudioClip(final_audio_list_for_composite)
                             self.log_info(f"_combine_videos_moviepy: Successfully composited audio. Composite duration: {final_audio_to_set.duration}")
                        else: # Only VO was available and successfully processed
                             final_audio_to_set = final_audio_list_for_composite[0]
                             self.log_info(f"_combine_videos_moviepy: Using VO only (processed). Final audio duration: {final_audio_to_set.duration}")
                        audio_clip_obj = final_audio_to_set # For cleanup
                    else:
                        # This case should ideally not be reached if audio_data was present and vo_clip loading succeeded initially
                        self.log_error("_combine_videos_moviepy: No audio clips available for final_audio_to_set even though VO was present.")
                        final_audio_to_set = None
                        audio_clip_obj = None
                        
                else: # This else handles cases where vo_clip could not be prepared from the start
                    self.log_error("_combine_videos_moviepy: vo_clip is not available after attempting load/conversion. No audio will be added.")

            else:
                self.log_info("_combine_videos_moviepy: No voice-over data (audio_data is None). No audio will be added.")

            # Video duration adjustment and setting audio
            if final_audio_to_set: 
                target_duration_for_video = final_audio_to_set.duration
                self.log_info(f"_combine_videos_moviepy: Final audio to set. Target duration for video: {target_duration_for_video} seconds.")

                if abs(video_duration - target_duration_for_video) > 0.2: 
                    self.log_info(f"_combine_videos_moviepy: Adjusting video duration from {video_duration} to match audio duration {target_duration_for_video}")
                    if video_duration > target_duration_for_video and target_duration_for_video > 0:
                        self.log_info("_combine_videos_moviepy: Shortening video to match audio (speedup).")
                        speedup_factor = video_duration / target_duration_for_video
                        final_clip_obj = final_clip_obj.fx(vfx.speedx, factor=speedup_factor)
                        final_clip_obj = final_clip_obj.subclip(0, target_duration_for_video)
                    elif target_duration_for_video > video_duration and video_duration > 0:
                        self.log_info("_combine_videos_moviepy: Looping video to match audio duration.")
                        final_clip_obj = final_clip_obj.loop(duration=target_duration_for_video)
                    else:
                        self.log_warning(f"_combine_videos_moviepy: Cannot adjust video duration. Video_duration: {video_duration}, target_audio_duration: {target_duration_for_video}. Using original video duration or target audio if possible.")
                        # If one of them is zero or negative, this could be an issue. Default to the valid one.
                        final_clip_obj = final_clip_obj.set_duration(max(target_duration_for_video, video_duration) if target_duration_for_video > 0 else video_duration) 
                
                self.log_info(f"_combine_videos_moviepy: Setting final audio to video. Audio duration: {final_audio_to_set.duration}")
                final_clip_obj = final_clip_obj.set_audio(final_audio_to_set)
                final_clip_obj = final_clip_obj.set_duration(final_audio_to_set.duration) 
                self.log_info(f"_combine_videos_moviepy: Final clip duration with audio set to: {final_clip_obj.duration} seconds.")
            else:
                self.log_info(f"_combine_videos_moviepy: No audio to set. Video duration remains: {video_duration} seconds.")
                final_clip_obj = final_clip_obj.set_duration(video_duration)
            
            unique_timestamp = str(int(time.time() * 1000))
            # Ensure final_output_file and temp_audiofile are absolute paths within process_temp_dir
            final_output_file_abs = os.path.join(process_temp_dir, f"final_output_{unique_timestamp}_{thread_id}.mp4") # ABSOLUTE PATH
            
            self.log_info(f"_combine_videos_moviepy: Preparing to write video file to {final_output_file_abs} using NVENC (if available)")
            
            ffmpeg_video_params = [
                '-c:v', 'h264_nvenc',
                '-preset', 'p7',      # p1 (slowest, best quality) to p7 (fastest, lowest quality)
                '-rc', 'vbr',         # Rate control: Variable Bitrate
                '-cq', '23',          # Constant Quality level for VBR (18-28 is typical)
                '-b:v', '4M',         # Target average video bitrate
                '-maxrate', '6M',    # Maximum video bitrate
                '-bufsize', '2M',     # Decoder buffer size (half of -b:v is often recommended for streaming compatibility)
                '-threads', '1'       # Typically recommended for NVENC to avoid issues
            ]

            try:
                final_clip_obj.write_videofile(
                    final_output_file_abs, 
                    codec='h264_nvenc', 
                    audio_codec='aac',
                    audio_fps=44100, # Explicitly set audio sample rate
                    fps=30,
                    logger='bar',
                    threads=4, 
                    preset='ultrafast',
                    ffmpeg_params=ffmpeg_video_params + ['-loglevel', 'error']
                )
                self.log_info(f"_combine_videos_moviepy: Video file writing with NVENC supposedly complete to {final_output_file_abs}")
            except Exception as e_nvenc:
                self.log_warning(f"_combine_videos_moviepy: NVENC encoding failed: {e_nvenc}. Falling back to libx264 (CPU).")
                self.log_error(traceback.format_exc())
                ffmpeg_video_params_cpu = [
                    '-c:v', 'libx264',
                    '-preset', 'medium',
                    '-crf', '23',
                    '-threads', '4'
                ]
                final_clip_obj.write_videofile(
                    final_output_file_abs, 
                    codec='libx264',
                    audio_codec='aac',
                    audio_fps=44100, # Explicitly set audio sample rate for fallback as well
                    fps=30,
                    logger='bar',
                    threads=4, 
                    preset='medium', 
                    ffmpeg_params=['-loglevel', 'error']
                )
                self.log_info(f"_combine_videos_moviepy: Video file writing with libx264 (fallback) complete to {final_output_file_abs}")

            with open(final_output_file_abs, 'rb') as f:
                final_video_data = f.read()
                
            self.log_success(f"Successfully combined videos with effects using MoviePy. File size: {len(final_video_data) // 1024} KB")
            # return final_video_data
            
        except Exception as e_moviepy:
            self.log_error(f"Error combining videos with effects using MoviePy: {str(e_moviepy)}")
            self.log_error(traceback.format_exc())
            final_video_data = None # Ensure it's None on error
            # return None
            
        finally:
            # try: # REMOVED: os.chdir no longer used
            #     os.chdir(original_cwd)
            # except Exception as e_chdir:
            #     self.log_warning(f"Could not return to original working directory: {e_chdir}")
            try:
                if 'clips' in locals() and clips: 
                    for clip_obj_item in clips: 
                        if hasattr(clip_obj_item, 'close') and callable(clip_obj_item.close):
                            try: clip_obj_item.close(); self.log_info(f"Closed clip: {clip_obj_item}")
                            except: pass 
                if 'audio_clip_obj' in locals() and audio_clip_obj and hasattr(audio_clip_obj, 'close'):
                    try: audio_clip_obj.close(); self.log_info("Closed audio_clip_obj")
                    except: pass
                if 'final_clip_obj' in locals() and final_clip_obj and hasattr(final_clip_obj, 'close'):
                    try: final_clip_obj.close(); self.log_info("Closed final_clip_obj")
                    except: pass

                if os.path.exists(process_temp_dir):
                    import shutil
                    shutil.rmtree(process_temp_dir)
                    self.log_info(f"Deleted temporary directory: {process_temp_dir}")
                else:
                    self.log_warning(f"Temporary directory {process_temp_dir} not found for deletion, it might have been cleaned up already or not created.")
            except Exception as e_cleanup: 
                self.log_error(f"Error during cleanup in _combine_videos_moviepy: {str(e_cleanup)}")
            
            return final_video_data

    def _combine_videos_ffmpeg(self, video_sources, audio_data=None, zoom_effect=False, width=1080, height=1920, audio_duration=None):
        """
        Combines videos or images with effects using ffmpeg.
        
        Parameters:
        ----------
        video_sources : list
            List of video sources (URLs or file data).
        audio_data : bytes, optional
            Audio data to add to the video.
        zoom_effect : bool, default=False
            Whether to apply a zoom effect to each segment.
        width : int
            Video width.
        height : int
            Video height.
        audio_duration : float, optional
            Audio duration in seconds.
            
        Returns:
        -------
        bytes
            Combined video data.
        """
        self.log_info("Using ffmpeg for video processing")
        
        # Importing required modules
        import subprocess
        import uuid
        import os
        import time
        import shutil
        import traceback
        
        # Creating a temporary directory for this process
        process_id = str(uuid.uuid4())[:8]
        process_temp_dir = os.path.join(self.temp_dir, f"process_{process_id}")
        os.makedirs(process_temp_dir, exist_ok=True)
        self.log_info(f"Created temporary directory: {process_temp_dir}")
        
        try:
            # Downloading and preparing source files
            source_files = []
            
            for i, source_item in enumerate(video_sources):
                # Determining unique file names
                raw_file = os.path.join(process_temp_dir, f"raw_input_{i}.dat")
                source_video_file = os.path.join(process_temp_dir, f"source_video_{i}.mp4")
                
                # Downloading or saving the source
                if isinstance(source_item, str) and (source_item.startswith('http://') or source_item.startswith('https://')):
                    self.log_info(f"Downloading source {i+1} from {source_item}")
                    try:
                        response = requests.get(source_item, timeout=60)
                        if response.status_code != 200:
                            self.log_error(f"Error downloading source {i+1}: {response.status_code}")
                            continue
                        with open(raw_file, 'wb') as f:
                            f.write(response.content)
                    except Exception as e:
                        self.log_error(f"Error downloading source {i+1}: {str(e)}")
                        continue
                else:
                    # This is already binary file data
                    with open(raw_file, 'wb') as f:
                        f.write(source_item)
                
                # Checking if it's a video or image
                is_image = self._is_image_file(raw_file)
                
                if is_image:
                    # Converting image to video
                    self.log_info(f"Image detected. Converting image {i+1} to video")
                    image_file = raw_file
                    
                    # Setting zoom effect if required
                    zoom_filter = ""
                    if zoom_effect:
                        # Use a simpler and more reliable zoom effect
                        zoom_filter = ",zoompan=z='1.0+0.2*on/90':d=90:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    
                    # Building a dynamic filter to maintain aspect ratio and center crop
                    if width == height:
                        # 1:1 ratio – no complex expression needed
                        scale_crop_filter = f'scale={width}:{height},crop={width}:{height}{zoom_filter}'
                    else:
                        # 9:16 ratio (or any rectangular ratio) – dynamic scale so no stretching occurs
                        scale_crop_filter = (
                            f"scale='if(gt(a,{width}/{height}),{width},-2)':'if(gt(a,{width}/{height}),-2,{height})',"
                            f"crop={width}:{height}{zoom_filter}"
                        )
                    
                    # Command with basic parameters for converting image to video
                    command = [ 
                        'ffmpeg', '-y',
                        '-loop', '1',
                        '-i', image_file,
                        '-vf', scale_crop_filter,
                        # '-c:v', 'libx264', # Old CPU encoder
                        '-c:v', 'h264_nvenc',        # NVIDIA GPU encoder
                        '-preset', 'p7',              # NVENC fastest preset (p1=slowest, p7=fastest)
                        '-rc', 'vbr',                 # Rate control: Variable Bitrate
                        '-cq', '23',                  # Constant Quality level (lower is better, 18-28 is typical)
                        '-b:v', '4M',                 # Target video bitrate (4 Mbps to keep file size reasonable)
                        '-maxrate', '6M',            # Max video bitrate
                        '-bufsize', '8M',            # Buffer size
                        '-threads', '1',              # Limit to 1 thread when using NVENC for this type of operation
                        '-t', '3',  # 3 seconds duration
                        '-pix_fmt', 'yuv420p',
                        source_video_file
                    ]
                    
                    self.log_info(f"Running ffmpeg command: {' '.join(command)}")
                    try:
                        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                        self.log_info(f"Image to video conversion completed successfully")
                    except subprocess.CalledProcessError as e:
                        self.log_error(f"Error converting image: {str(e)}")
                        self.log_error(f"Error output: {e.stderr}")
                        
                        # Try with even simpler parameters
                        simpler_command = [
                            'ffmpeg', '-y',
                            '-loop', '1',
                            '-i', image_file,
                            '-c:v', 'libx264',
                            '-t', '3',
                            '-pix_fmt', 'yuv420p',
                            source_video_file
                        ]
                        try:
                            self.log_info(f"Trying with a simpler command: {' '.join(simpler_command)}")
                            result = subprocess.run(simpler_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                            self.log_info(f"Image to video conversion completed successfully (simple attempt)")
                        except subprocess.CalledProcessError as e2:
                            self.log_error(f"The second attempt also failed: {str(e2)}")
                            self.log_error(f"Simpler command error output: {e2.stderr}") # Log stderr for simpler command
                            continue
                else:
                    # Copying video without change
                    shutil.copy(raw_file, source_video_file)
                    self.log_info(f"Copied video {i+1} without change")
                
                # Ensuring the created file exists
                if os.path.exists(source_video_file) and os.path.getsize(source_video_file) > 1000:
                    source_files.append(source_video_file)
                    self.log_info(f"Added source file: {source_video_file}, size: {os.path.getsize(source_video_file)} bytes")
                else:
                    self.log_error(f"Source file missing or too small: {source_video_file}")
                    continue
            
            # Checking if there are files to process
            if not source_files:
                self.log_error("No source files to process")
                return None
            
            # Creating the segments file according to ffmpeg's standard format (concat demuxer)
            segments_file = os.path.join(process_temp_dir, "segments.txt")
            with open(segments_file, 'w') as f:
                for source_file_item in source_files:
                    # Using the standard format: file '[path]'
                    # Using absolute path to prevent duplicate path issues
                    absolute_path = os.path.abspath(source_file_item)
                    f.write(f"file '{absolute_path}'\n")
                    # Not using unsupported commands like transition or duration
                
            # Checking if the segments file was created
            if not os.path.exists(segments_file) or os.path.getsize(segments_file) == 0:
                self.log_error("Segments file is empty or was not created")
                return None
            
            # Displaying segments file content for debugging purposes
            try:
                with open(segments_file, 'r') as f:
                    segments_content = f.read()
                self.log_info(f"Segments file content:\n{segments_content}")
            except Exception as e:
                self.log_error(f"Error reading segments file: {str(e)}")

            
            # Creating combined video (without audio at this stage)
            combined_video_no_audio = os.path.join(process_temp_dir, "combined_no_audio.mp4")
            concat_command = [ 
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', segments_file,
                # '-c:v', 'copy', # Using stream copy for better performance - might not work with different source params
                '-c:v', 'h264_nvenc',        # Use NVENC for combining as well if re-encoding is needed
                '-preset', 'p7',
                '-rc', 'vbr', '-cq', '23',
                '-b:v', '4M',
                '-maxrate', '6M',
                '-bufsize', '8M',
                '-threads', '1',
                '-pix_fmt', 'yuv420p', # Ensure consistent pixel format
                combined_video_no_audio
            ]
            
            # Running the combine command
            self.log_info(f"Running video combine command: {' '.join(concat_command)}")
            success = False
            e_concat = None # Variable to store potential exception
            try:
                result = subprocess.run(concat_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                self.log_info("Video combining completed successfully")
                success = True
            except subprocess.CalledProcessError as e_call:
                e_concat = e_call
                self.log_error(f"Error combining videos: {str(e_concat)}")
                if e_concat.stderr:
                    self.log_error(f"Error output: {e_concat.stderr}")
                success = False
            
            # If stream copy failed, try with alternative strategies
            if not success or not os.path.exists(combined_video_no_audio) or os.path.getsize(combined_video_no_audio) < 10000:
                self.log_info("Alternative attempt with re-encoding")
                
                # Try to change segments file format if the issue is with file paths
                if not success and e_concat and e_concat.stderr and ("No such file or directory" in e_concat.stderr or "Invalid data found" in e_concat.stderr):
                    self.log_info("File path issue, trying alternative solution")
                    try:
                        # Creating a new segments file with relative paths
                        with open(segments_file, 'w') as f:
                            for source_file_item in source_files:
                                # Using filename only
                                filename = os.path.basename(source_file_item)
                                source_dir = os.path.dirname(source_file_item)
                                # Copying the file to the process directory if not already there
                                if source_dir != process_temp_dir:
                                    new_path = os.path.join(process_temp_dir, filename)
                                    shutil.copy(source_file_item, new_path)
                                    f.write(f"file '{filename}'\n")
                                else:
                                    f.write(f"file '{filename}'\n")
                        
                        # Changing current directory to the process directory
                        original_dir = os.getcwd()
                        os.chdir(process_temp_dir)
                        
                        # Retrying with the corrected file
                        concat_command_fixed = [
                            'ffmpeg', '-y',
                            '-f', 'concat',
                            '-safe', '0',
                            '-i', "segments.txt",
                            '-c:v', 'copy',
                            "combined_no_audio.mp4"
                        ]
                        
                        self.log_info(f"Running combine command with relative paths: {' '.join(concat_command_fixed)}")
                        result = subprocess.run(concat_command_fixed, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                        success = True
                        
                        # Returning to the original directory
                        os.chdir(original_dir)
                        
                    except Exception as e_alt:
                        self.log_error(f"Error in alternative attempt: {str(e_alt)}")
                        # Returning to original directory in case of error
                        if 'original_dir' in locals():
                            os.chdir(original_dir)
                
                # If still failed, try with re-encoding (now NVENC is the re-encode attempt)
                if not success:
                    # concat_command_reencode was the old name, now it's just the concat_command above
                    # If the above NVENC command failed, it might be a deeper issue.
                    # For now, we assume if the first NVENC concat failed, we log and return None
                    self.log_error("Video combining with NVENC failed. Check FFmpeg logs if available.")
                    return None
            
            # Checking that the combined video was created
            if not success or not os.path.exists(combined_video_no_audio) or os.path.getsize(combined_video_no_audio) < 10000:
                self.log_error("Combined video not created or too small")
                return None
                
            # Checking if audio needs to be added
            final_output_file = combined_video_no_audio
            
            if audio_data:
                self.log_info("Adding audio to combined video")
                
                # Saving audio to file
                audio_file = os.path.join(process_temp_dir, "audio.mp3")
                with open(audio_file, 'wb') as f:
                    f.write(audio_data)
                
                # Ensuring audio file was created
                if not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
                    self.log_error("Audio file not created or too small")
                else:
                    # Adding audio to video
                    final_output_file = os.path.join(process_temp_dir, "final_output.mp4")
                    audio_command = [
                        'ffmpeg', '-y',
                        '-i', combined_video_no_audio, # This is now NVENC encoded
                        '-i', audio_file,
                        '-c:v', 'copy', # Video is already encoded with NVENC, so copy it
                        '-c:a', 'aac',  
                        '-shortest',    
                        final_output_file
                    ]
                    
                    try:
                        self.log_info(f"Running add audio command: {' '.join(audio_command)}")
                        result = subprocess.run(audio_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                        self.log_info("Adding audio completed successfully")
                    except subprocess.CalledProcessError as e_audio:
                        self.log_error(f"Error adding audio: {str(e_audio)}")
                        if e_audio.stderr:
                            self.log_error(f"Error output: {e_audio.stderr}")
                        # If failed, use video without audio
                        final_output_file = combined_video_no_audio
            
            # Reading the final file
            if os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 10000:
                with open(final_output_file, 'rb') as f:
                    final_video_data = f.read()
                
                self.log_success(f"Successfully created combined video. Size: {len(final_video_data) // 1024} KB")
                return final_video_data
            else:
                self.log_error(f"Final file missing or too small: {final_output_file}")
                return None
            
        except Exception as e_main:
            self.log_error(f"Error in video combining process: {str(e_main)}")
            self.log_error(traceback.format_exc())
            return None
            
        finally:
            # Cleaning up temporary files
            try:
                if os.path.exists(process_temp_dir):
                    shutil.rmtree(process_temp_dir)
                    self.log_info(f"Deleted temporary files: {process_temp_dir}")
            except Exception as e_cleanup:
                self.log_error(f"Error cleaning up temporary files: {str(e_cleanup)}")

    def _submit_combined_to_zapcap(self, row_data, row_index, video_data, text, language_input="", template_id="", caption_position=None):
        self.log_info(f"Submitting combined video to ZapCap for row {row_index}. Caption: {caption_position}")
        
        temp_video_for_zapcap = None 
        try:
            # Create a dedicated directory for pre-ZapCap check files if it doesn't exist
            # This directory will be inside the main temp_dir to ensure it's cleaned up eventually
            pre_zapcap_check_dir = os.path.join(self.temp_dir, "pre_zapcap_check_videos")
            if not os.path.exists(pre_zapcap_check_dir):
                try:
                    os.makedirs(pre_zapcap_check_dir)
                    self.log_info(f"Created directory for pre-ZapCap check videos: {pre_zapcap_check_dir}")
                except OSError as e_mkdir:
                    self.log_warning(f"Could not create directory {pre_zapcap_check_dir}, will save to main temp: {e_mkdir}")
                    pre_zapcap_check_dir = self.temp_dir # Fallback to main temp_dir

            timestamp = int(time.time())
            original_filename_from_sheet = row_data.get(config.COLUMNS.get('NAME', 'Name'), f"video_row_{row_index}_ts{timestamp}")
            safe_original_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', original_filename_from_sheet)
            # Save a copy of the video_data being sent to ZapCap for local inspection
            check_video_filename = f"PRE_ZAPCAP_{safe_original_filename}.mp4"
            check_video_filepath = os.path.join(pre_zapcap_check_dir, check_video_filename)

            try:
                with open(check_video_filepath, 'wb') as f_check:
                    f_check.write(video_data)
                self.log_info(f"Saved a pre-ZapCap check copy of the video to: {check_video_filepath} (Size: {len(video_data)//1024} KB)")
                
                # Add ffprobe check for audio streams on the saved file
                if os.path.exists(check_video_filepath):
                    try:
                        probe_command = [
                            'ffprobe', '-v', 'error',
                            '-select_streams', 'a', # Select only audio streams
                            '-show_entries', 'stream=codec_name,channels,sample_rate,bit_rate', 
                            '-of', 'default=noprint_wrappers=1',
                            check_video_filepath
                        ]
                        self.log_info(f"Running ffprobe on pre-ZapCap file: {' '.join(probe_command)}")
                        probe_output = subprocess.check_output(probe_command, stderr=subprocess.STDOUT).decode('utf-8').strip()
                        if probe_output:
                            self.log_info(f"ffprobe audio stream info for {check_video_filepath}:\n{probe_output}")
                        else:
                            self.log_warning(f"ffprobe found NO audio streams in {check_video_filepath}")
                    except subprocess.CalledProcessError as e_probe:
                        self.log_error(f"ffprobe check failed for {check_video_filepath}. Return code: {e_probe.returncode}\nOutput: {e_probe.output.decode('utf-8', errors='ignore')}")
                    except Exception as e_probe_general:
                        self.log_error(f"General error during ffprobe check for {check_video_filepath}: {e_probe_general}")

            except Exception as e_save_check:
                self.log_warning(f"Could not save a pre-ZapCap check copy of the video {check_video_filepath}: {e_save_check}")

            with tempfile.NamedTemporaryFile(suffix=".mp4", dir=self.temp_dir, delete=False) as tmp_vf:
                tmp_vf.write(video_data)
                temp_video_for_zapcap = tmp_vf.name 
            self.log_info(f"Saved video temporarily for ZapCap upload: {temp_video_for_zapcap}")

            language_code = self._detect_language(language_input.strip(), text)
            upload_url = f"{self.zapcap_base_url}/videos"
            headers = {"x-api-key": self.zapcap_api_key}

            with open(temp_video_for_zapcap, "rb") as vf:
                files = {"file": (os.path.basename(temp_video_for_zapcap), vf, "video/mp4")}
                self.log_info(f"Uploading file directly to ZapCap: {upload_url} (from {temp_video_for_zapcap})")
                up_resp = requests.post(upload_url, headers=headers, files=files, timeout=120)

            self.log_info(f"Upload status: {up_resp.status_code}")
            if up_resp.status_code != 201:
                self.log_error(f"Direct upload failed: {up_resp.text}")
                raise requests.exceptions.HTTPError(f"ZapCap upload failed: {up_resp.status_code} - {up_resp.text}")
            
            video_id_json = up_resp.json() 
            video_id = video_id_json.get("id")
            if not video_id:
                self.log_error("video_id not returned from upload")
                raise ValueError("video_id not returned from ZapCap upload")

            task_url = f"{self.zapcap_base_url}/videos/{video_id}/task"
            template_id_to_use = template_id or os.getenv("ZAPCAP_TEMPLATE_ID")
            if not template_id_to_use:
                self.log_error("ZAPCAP_TEMPLATE_ID not set and no Template ID provided - cannot create task")
                raise ValueError("ZapCap Template ID missing")

            task_body = {"templateId": template_id_to_use, "language": language_code, "autoApprove": True}
            if caption_position is not None:
                caption_position_cleaned = str(caption_position).strip().lower()
                top_value = None
                if caption_position_cleaned == "upper": top_value = 20
                elif caption_position_cleaned == "center": top_value = 50
                elif caption_position_cleaned == "low": top_value = 60
                else:
                    try: top_value = int(caption_position)
                    except ValueError: self.log_warning(f"Caption position '{caption_position}' not recognized. Ignoring.")
                if top_value is not None:
                    task_body.setdefault("renderOptions", {}).setdefault("styleOptions", {})["top"] = top_value
                    self.log_info(f"Added to task_body: renderOptions.styleOptions.top = {top_value}")

            self.log_info(f"Creating task in ZapCap: {task_url} with body: {task_body}")
            task_resp = requests.post(task_url, headers=headers, json=task_body, timeout=120)  # Increased timeout to 120 seconds for ZapCap
            self.log_info(f"Task creation status: {task_resp.status_code}")
            if task_resp.status_code not in [200, 201]:
                self.log_error(f"Task creation failed: {task_resp.text}")
                raise requests.exceptions.HTTPError(f"ZapCap task creation failed: {task_resp.status_code} - {task_resp.text}")

            task_id_response = task_resp.json().get("taskId") or task_resp.json().get("id")
            if task_id_response:
                self.log_success(f"ZapCap task created: {task_id_response}")
                self._update_sheet_task_id(row_index, "ZapCap Task ID", task_id_response)
                return {"video_id": video_id, "task_id": task_id_response}
            else:
                self.log_error("taskId not returned from ZapCap response")
                raise ValueError("taskId not returned from ZapCap task creation")
        
        except requests.exceptions.RequestException as req_err: 
            self.log_error(f"Request error during ZapCap submission: {req_err}")
            self.log_error(traceback.format_exc())
            return None
        except json.JSONDecodeError as json_err: 
            self.log_error(f"JSON decoding error in ZapCap logic: {json_err}")
            if 'up_resp' in locals() and hasattr(up_resp, 'text'): self.log_error(f"Upload Response text causing JSON error: {up_resp.text[:500]}")
            elif 'task_resp' in locals() and hasattr(task_resp, 'text'): self.log_error(f"Task Response text causing JSON error: {task_resp.text[:500]}")
            self.log_error(traceback.format_exc())
            return None
        except ValueError as val_err: 
            self.log_error(f"ValueError in ZapCap submission: {val_err}")
            self.log_error(traceback.format_exc())
            return None
        except Exception as zerr: 
            self.log_error(f"Unexpected error in _submit_combined_to_zapcap: {zerr}")
            self.log_error(traceback.format_exc())
            return None
        finally:
            if temp_video_for_zapcap and os.path.exists(temp_video_for_zapcap):
                try:
                    os.remove(temp_video_for_zapcap)
                    self.log_info(f"Cleaned up temporary video for ZapCap: {temp_video_for_zapcap}")
                except Exception as e_remove_zapcap_temp:
                    self.log_warning(f"Could not remove temp ZapCap video {temp_video_for_zapcap}: {e_remove_zapcap_temp}")

    def _process_multiple_images_row(self, row_data, row_index, return_submission_details=False, actual_audio_data=None):
        try:
            self.log_info(f"Processing multiple images for row {row_index} (audio provided externally: {'Yes' if actual_audio_data else 'No'})")
            
            text = row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '')
            # actual_audio_data is now passed as a parameter
            if text and actual_audio_data is None:
                self.log_warning(f"Row {row_index}: Script text exists but no pre-generated audio_data provided. Video will likely have no VO.")
            elif not text:
                 self.log_info(f"Row {row_index}: No script text, so no VO expected.")

            image_urls = [row_data.get(config.COLUMNS.get(f'IMAGE_LINK_{i}', f'Image Link {i}')) for i in range(1, 5) if row_data.get(config.COLUMNS.get(f'IMAGE_LINK_{i}', f'Image Link {i}'))]
            
            if not image_urls: 
                self.log_warning(f"No image URLs for row {row_index} in _process_multiple_images_row. Cannot create combined video.")
                self._update_sheet_status(row_index, "Skipped: No image URLs for ZapCap video")
                return None if return_submission_details else False # Adjusted return

            zoom_in_flag_str = str(row_data.get(config.COLUMNS.get('ZOOM_IN', 'Zoom in?'), 'no')).strip().lower()
            zoom_effect_bool = zoom_in_flag_str == 'yes'
            current_aspect_ratio_str = row_data.get(config.COLUMNS.get('SIZE', 'Size'), '9:16')

            with timer(f"FFMPEG_Video_Effects_Row_{row_index}"):
                combined_video_data = self.combine_videos_with_effects(
                    image_urls, 
                    audio_data=actual_audio_data,
                    zoom_effect=zoom_effect_bool,
                    aspect_ratio=current_aspect_ratio_str
                )
            
            if combined_video_data is None: 
                self.log_error(f"Combined video (images) not created for row {row_index}. Skipping ZapCap submission.")
                self._update_sheet_status(row_index, "Error: Failed to create combined video for ZapCap")
                return None if return_submission_details else False # Adjusted return

            language_val = row_data.get(config.COLUMNS.get('LANGUAGE', 'Language'), '') 
            zapcap_template_val = row_data.get(config.COLUMNS.get('ZAPCAP_TEMPLATE','ZapCap Template'), '') 
            caption_pos_val = row_data.get(config.COLUMNS.get('CAPTION_POSITION', 'Caption Position'), None)

            with timer(f"ZapCap_Submit_Row_{row_index}"):
                submission_result = self._submit_combined_to_zapcap(
                    row_data,            
                    row_index,           
                    combined_video_data, 
                    text,                
                    language_val,        
                    zapcap_template_val, 
                    caption_pos_val      
                )
            
            if return_submission_details:
                return submission_result
            else:
                if submission_result and submission_result.get("task_id") and submission_result.get("video_id"):
                    return True
                return False
            
        except Exception as e_outer_images: 
            self.log_error(f"Outer error in _process_multiple_images_row for row {row_index}: {str(e_outer_images)}") 
            self.log_error(traceback.format_exc())
            self._update_sheet_status(row_index, f"Critical Error in _process_multiple_images_row: {str(e_outer_images)}")
            return None if return_submission_details else False

    def _process_multiple_animated_row(self, row_data, row_index, return_submission_details=False, actual_audio_data=None):
        try:
            self.log_info(f"Processing multiple animated videos for row {row_index} (audio provided externally: {'Yes' if actual_audio_data else 'No'})")
            
            text = row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '')
            # actual_audio_data is now passed as a parameter
            if text and actual_audio_data is None:
                self.log_warning(f"Row {row_index} (animated): Script text exists but no pre-generated audio_data provided. Video will likely have no VO.")
            elif not text:
                self.log_info(f"Row {row_index} (animated): No script text, so no VO expected.")

            animated_video_urls = [row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}')) for i in range(1, 5) if row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}'))]
            
            if not animated_video_urls: 
                self.log_warning(f"No animated video URLs for row {row_index} in _process_multiple_animated_row. Cannot create combined video.")
                self._update_sheet_status(row_index, "Skipped: No animated video URLs for ZapCap")
                return None if return_submission_details else False # Adjusted return

            zoom_in_flag_str = str(row_data.get(config.COLUMNS.get('ZOOM_IN', 'Zoom in?'), 'no')).strip().lower()
            zoom_effect_bool = zoom_in_flag_str == 'yes'
            current_aspect_ratio_str = row_data.get(config.COLUMNS.get('SIZE', 'Size'), '9:16')

            with timer(f"FFMPEG_Animated_Effects_Row_{row_index}"):
                combined_video_data = self.combine_videos_with_effects(
                    animated_video_urls,
                    audio_data=actual_audio_data,
                    zoom_effect=zoom_effect_bool,
                    aspect_ratio=current_aspect_ratio_str
                )

            if combined_video_data is None: 
                self.log_error(f"Combined video (animated) not created for row {row_index}. Skipping ZapCap submission.")
                self._update_sheet_status(row_index, "Error: Failed to create animated combined video for ZapCap")
                return None if return_submission_details else False # Adjusted return

            language_val = row_data.get(config.COLUMNS.get('LANGUAGE', 'Language'), '')
            zapcap_template_val = row_data.get(config.COLUMNS.get('ZAPCAP_TEMPLATE','ZapCap Template'), '')
            caption_pos_val = row_data.get(config.COLUMNS.get('CAPTION_POSITION', 'Caption Position'), None)

            with timer(f"ZapCap_Submit_Animated_Row_{row_index}"):
                submission_result = self._submit_combined_to_zapcap(
                    row_data,            
                    row_index,           
                    combined_video_data, 
                    text,                
                    language_val,        
                    zapcap_template_val,  
                    caption_pos_val       
                )
            
            if return_submission_details:
                return submission_result
            else:
                if submission_result and submission_result.get("task_id") and submission_result.get("video_id"):
                    return True
                return False
        except Exception as e_outer_animated: 
            self.log_error(f"Outer error in _process_multiple_animated_row for row {row_index}: {str(e_outer_animated)}")
            self.log_error(traceback.format_exc())
            self._update_sheet_status(row_index, f"Critical Error in _process_multiple_animated_row: {str(e_outer_animated)}")
            return None if return_submission_details else False

    def _generate_vo_for_row(self, row_data):
        # ... (function code unchanged from the previous Step 3 implementation)
        row_idx = row_data.get('original_row_index', 'N/A')
        self.log_info(f"TTS Pool: Starting VO generation for row {row_idx}")
        text = row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '')
        actual_audio_data = None
        if text:
            voice_input = row_data.get(config.COLUMNS.get('VOICE', 'Voice'), '')
            selected_voice_result = self._select_voice(voice_input)
            
            # Get gender preference from VO Gender column
            vo_gender = row_data.get(config.COLUMNS.get('VO_GENDER', 'VO Gender'), '')
            self.log_info(f"TTS Pool: Row {row_idx} VO Gender preference: '{vo_gender}'")
            
            if selected_voice_result:
                # Check if _select_voice returned audio data (bytes) or voice ID (string)
                if isinstance(selected_voice_result, bytes):
                    # Voice was downloaded from URL - use it directly
                    actual_audio_data = selected_voice_result
                    self.log_info(f"TTS Pool: Row {row_idx} using downloaded voice audio. Size: {len(actual_audio_data)} bytes.")
                    return actual_audio_data
                else:
                    # Voice is a code - generate TTS
                    try:
                        with timer(f"TTS_Pipeline_Single_Row_{row_idx}"):
                            audio_data_list = self.generate_tts_batch([text], [selected_voice_result], [vo_gender])
                        if audio_data_list and audio_data_list[0]:
                            actual_audio_data = audio_data_list[0]
                            self.log_info(f"TTS Pool: Row {row_idx} VO generated. Size: {len(actual_audio_data)} bytes.")
                            return actual_audio_data
                        else:
                            self.log_warning(f"TTS Pool: Row {row_idx} VO generation returned no/empty audio.")
                    except Exception as e:
                        self.log_error(f"TTS Pool: Error generating VO for row {row_idx}: {e}")
                        self.log_error(traceback.format_exc())
            else:
                self.log_warning(f"TTS Pool: Row {row_idx} no voice selected, skipping VO.")
        else:
            self.log_info(f"TTS Pool: Row {row_idx} no script, skipping VO.")
        return None

    def _render_video_and_queue_for_zapcap(self, row_data_with_audio):
        # ... (function code unchanged from the previous Step 4 implementation)
        row_idx = row_data_with_audio.get('original_row_index', 'N/A')
        actual_audio_data = row_data_with_audio.get('audio_data')  # Fixed: consistent with how audio_data is stored
        self.log_info(f"VideoRenderQueueProducer: Starting video creation for row {row_idx}. Audio present: {'Yes' if actual_audio_data else 'No'}")

        animated_links = [row_data_with_audio.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}')) for i in range(1, 5) if row_data_with_audio.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}'))]
        
        video_sources_for_combine = animated_links if animated_links else [row_data_with_audio.get(config.COLUMNS.get(f'IMAGE_LINK_{i}', f'Image Link {i}')) for i in range(1, 5) if row_data_with_audio.get(config.COLUMNS.get(f'IMAGE_LINK_{i}', f'Image Link {i}'))]
        source_type = "animated links" if animated_links else "image URLs"

        if not video_sources_for_combine or all(not s for s in video_sources_for_combine):
            self.log_warning(f"VideoRenderQueueProducer: Row {row_idx}: No valid {source_type} found. Cannot create video.")
            self._update_sheet_status(row_idx, f"Skipped: No valid {source_type} for video creation (pipeline)")
            return

        zoom_in_flag_str = str(row_data_with_audio.get(config.COLUMNS.get('ZOOM_IN', 'Zoom in?'), 'no')).strip().lower()
        zoom_effect_bool = zoom_in_flag_str == 'yes'
        current_aspect_ratio_str = row_data_with_audio.get(config.COLUMNS.get('SIZE', 'Size'), '9:16')
        timer_tag_suffix = "Animated" if animated_links else "Static"

        with timer(f"FFMPEG_Pipeline_{timer_tag_suffix}_Row_{row_idx}"):
            combined_video_data = self.combine_videos_with_effects(
                video_sources_for_combine, 
                audio_data=actual_audio_data,
                zoom_effect=zoom_effect_bool,
                aspect_ratio=current_aspect_ratio_str
            )
        
        if combined_video_data:
            self.log_info(f"VideoRenderQueueProducer: Row {row_idx} video CREATED. Size: {len(combined_video_data)//1024}KB. Adding to ZapCap queue.")
            self.video_q.put((row_data_with_audio, combined_video_data))
        else:
            self.log_error(f"VideoRenderQueueProducer: Row {row_idx} video creation FAILED. Not adding to ZapCap queue.")
            self._update_sheet_status(row_idx, "Error: Failed to create combined video (pipeline queue stage)")

    def _zapcap_worker(self):
        """ (Consumer) Takes (row_data, video_data) from video_q, submits to ZapCap, and adds result to submitted_to_zapcap_tasks_list (thread-safe)."""
        thread_name = threading.current_thread().name
        self.log_info(f"ZapCapWorker ({thread_name}): Starting.")
        worker_submissions_count = 0

        while True:
            try:
                row_data, combined_video_data = self.video_q.get(timeout=10) 
                row_idx = row_data.get('original_row_index', 'N/A')
                self.log_info(f"ZapCapWorker ({thread_name}): Got video for row {row_idx} from queue. Processing.")

                text = row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '')
                language_val = row_data.get(config.COLUMNS.get('LANGUAGE', 'Language'), '') 
                zapcap_template_val = row_data.get(config.COLUMNS.get('ZAPCAP_TEMPLATE','ZapCap Template'), '') 
                caption_pos_val = row_data.get(config.COLUMNS.get('CAPTION_POSITION', 'Caption Position'), None)

                with timer(f"ZapCap_Submit_Worker_Row_{row_idx}"):
                    submission_details = self._submit_combined_to_zapcap(
                        row_data,            
                        row_idx,           
                        combined_video_data, 
                        text,                
                        language_val,        
                        zapcap_template_val, 
                        caption_pos_val      
                    )
                
                if submission_details and submission_details.get("task_id") and submission_details.get("video_id"):
                    task_to_monitor = {
                        "task_id": submission_details["task_id"],
                        "video_id": submission_details["video_id"],
                        "row": row_idx,
                        "file_name": row_data.get(config.COLUMNS.get('NAME', 'Name'), f"video_row_{row_idx}"),
                        "row_data": row_data.copy()  # Save row data for potential regeneration
                    }
                    with self._zap_lock: # Ensure thread-safe append
                        self.tasks_for_final_monitoring.append(task_to_monitor)
                    self.log_info(f"ZapCapWorker ({thread_name}): ZapCap submission successful for row {row_idx}. Task ID: {submission_details.get('task_id')} added to main monitoring list.")
                    worker_submissions_count += 1
                else:
                    self.log_error(f"ZapCapWorker ({thread_name}): ZapCap submission FAILED for row {row_idx}.")
                    self._update_sheet_status(row_idx, "Error: ZapCap submission failed in worker (pipeline)")
                
                self.video_q.task_done()

            except queue.Empty:
                if self.video_producers_done_event.is_set():
                    self.log_info(f"ZapCapWorker ({thread_name}): Queue empty and producers are done. Exiting.")
                    break
                else:
                    continue 
            except Exception as e_worker:
                self.log_error(f"ZapCapWorker ({thread_name}): Unexpected error: {e_worker}")
                self.log_error(traceback.format_exc())
        self.log_info(f"ZapCapWorker ({thread_name}): Exited. Initiated {worker_submissions_count} ZapCap submissions.")

    def run(self, process_mode="all", start_row=2, end_row=None, specific_rows=None):
        """
        Enhanced pipeline with proper skipping logic and ZapCap Task ID handling.
        """
        self.log_info(f"Starting VideoProcessor run. Mode: {process_mode}, Start: {start_row}, End: {end_row}, Specific: {specific_rows}")
        
        # Ensure instance-level lists/events are reset for each run
        self.tasks_for_final_monitoring = []
        if hasattr(self, 'video_producers_done_event'):
            self.video_producers_done_event.clear()
        else:
            self.log_error("Critical: video_producers_done_event not initialized!")
            self.video_producers_done_event = threading.Event() 
            self.video_producers_done_event.clear()

        if hasattr(self, 'video_q'):
            while not self.video_q.empty():
                try:
                    self.video_q.get_nowait()
                except queue.Empty:
                    break
                self.video_q.task_done()
        else:
            self.log_error("Critical: video_q not initialized!")
            self.video_q = queue.Queue(maxsize=getattr(config, 'VIDEO_QUEUE_SIZE', 8))
        
        try:
            # 1. Read all data from sheet
            data = self.read_google_sheet(start_row, end_row, specific_rows)
            if not data:
                self.log_error("No data found in sheet")
                return

            # 2. Apply row filtering based on mode
            if specific_rows:
                # If there are specific_rows, always use them regardless of process_mode
                data_for_pipeline = [row for row in data if row.get('original_row_index') in specific_rows]
                self.log_info(f"Processing {len(data_for_pipeline)} specific rows: {sorted(specific_rows)}")
            else:
                # Regular logic by row range
                if end_row is None:
                    # Find the maximum row index in the data instead of using len(data)
                    max_row_index = max(row.get('original_row_index', 0) for row in data) if data else start_row
                    end_row = max_row_index
                data_for_pipeline = [row for row in data if start_row <= row.get('original_row_index', 0) <= end_row]
                self.log_info(f"Processing rows from {start_row} to {end_row}. Filtered to {len(data_for_pipeline)} rows.")

            # 3. Handle orphaned videos FIRST (before animation check)
            self._handle_orphaned_videos(data_for_pipeline)

            # 4. Global Animation Stage with KLING Support (after cleaning orphaned videos)
            self.log_info(f"--- Global Animation Stage starting for {len(data_for_pipeline)} candidate rows ---")
            
            # Find all rows that need animation (including KLING)
            rows_needing_animation = []
            for row_data in data_for_pipeline:
                animate_val = row_data.get(config.COLUMNS.get('ANIMATE_IMAGES', 'Animate the images?'), '').strip()
                
                # Check if row needs animation - only MINIMAX or KLING
                needs_animation = (
                    'KLING' in animate_val.upper() or 
                    'MINIMAX' in animate_val.upper()
                )
                
                if needs_animation:
                    final_video_url = row_data.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'), '').strip()
                    animated_cols = [config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}') for i in range(1, 5)]
                    existing_animated_images = any(row_data.get(col, '').strip() for col in animated_cols)
                    
                    # Check if animated images already exist
                    if existing_animated_images:
                        self.log_info(f"Animation Stage: Row {row_data.get('original_row_index', 'N/A')} SKIPPED - already has animated images")
                        continue
                    
                    # FIXED: Animate if needs animation and no existing animated images, regardless of Final Video URL
                    rows_needing_animation.append(row_data)
                    self.log_info(f"Animation Stage: Row {row_data.get('original_row_index', 'N/A')} needs animation - {animate_val} (Final Video: {'Yes' if final_video_url else 'No'})")

            if rows_needing_animation:
                self.log_info(f"Animation Stage: Processing {len(rows_needing_animation)} rows that need animation.")
                animation_candidate_rows = []
                animate_column = config.COLUMNS.get('ANIMATE_IMAGES', 'Animate the images?')
                
                for row_data_iter_anim in rows_needing_animation:
                    row_idx_log_anim = row_data_iter_anim.get('original_row_index', 'N/A')
                    animate_flag_anim = str(row_data_iter_anim.get(animate_column, '')).strip()
                    has_existing_animation_anim = any(row_data_iter_anim.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{j}', f'Animated Image {j}')) for j in range(1, 5))

                    # Check if needs animation - only MINIMAX or KLING
                    needs_anim = (
                        'KLING' in animate_flag_anim.upper() or 
                        'MINIMAX' in animate_flag_anim.upper()
                    )
                    
                    if needs_anim and not has_existing_animation_anim:
                        if 'row' not in row_data_iter_anim: row_data_iter_anim['row'] = row_idx_log_anim
                        animation_candidate_rows.append(row_data_iter_anim)
                    elif has_existing_animation_anim:
                        self.log_info(f"Animation Stage: Row {row_idx_log_anim} SKIPPED in processing - already has animated images")
                
                if animation_candidate_rows:
                    self.log_info(f"Animation Stage: Animating for {len(animation_candidate_rows)} rows.")
                    animation_tasks_created = self.animate_images_batch(animation_candidate_rows)
                    if animation_tasks_created:
                        self.log_info(f"Animation Stage: Waiting for {len(animation_tasks_created)} animation tasks (max {getattr(config, 'ANIMATION_MAX_WAIT_TIME', 900)}s overall)...")
                        self.wait_for_animations(animation_tasks_created)
                        
                        self.log_info("Animation Stage: Reloading sheet data after animations to get updated links.")
                        all_sheet_data_reloaded_anim = []
                        try:
                            # Define headers for reloading
                            headers_for_reload = [
                                'Country', 'Vertical', 'Language', 'Image Link 1', 'Image Link 2',
                                'Image Link 3', 'Image Link 4', 'Caption Position', 'Script', 'Voice',
                                'ZapCap Template', 'Zoom in?', 'Size', 'Animate the images?', 'Free Text',
                                'Name', 'Final Video url', 'Animated Image 1', 'Animated Image 2',
                                'Animated Image 3', 'Animated Image 4', 'Status', 'ZapCap Task ID'
                            ]
                            for col_key, col_name_from_config in config.COLUMNS.items():
                                if col_name_from_config not in headers_for_reload:
                                    headers_for_reload.append(col_name_from_config)
                            
                            all_sheet_data_reloaded_anim = self.sheet.get_all_records(expected_headers=headers_for_reload, head=1, default_blank='')
                        except Exception as e_reload_anim:
                            self.log_error(f"Failed to re-read sheet data after animation: {e_reload_anim}. Animation URLs might be missing for subsequent steps.")
                        
                        if all_sheet_data_reloaded_anim:
                            reloaded_rows_map_anim = { (i + 2): record for i, record in enumerate(all_sheet_data_reloaded_anim) }
                            updated_pipeline_data_anim = []
                            original_indices_in_run_anim = {r.get('original_row_index') for r in data_for_pipeline}

                            for original_idx_anim in original_indices_in_run_anim:
                                original_row_obj_anim = next((r for r in data_for_pipeline if r.get('original_row_index') == original_idx_anim), None)
                                if original_idx_anim in reloaded_rows_map_anim:
                                    new_row_data_anim = original_row_obj_anim.copy() if original_row_obj_anim else {}
                                    new_row_data_anim.update(reloaded_rows_map_anim[original_idx_anim])
                                    new_row_data_anim['original_row_index'] = original_idx_anim
                                    updated_pipeline_data_anim.append(new_row_data_anim)
                                elif original_row_obj_anim: # If not found in reload, keep original if it was part of the run
                                    updated_pipeline_data_anim.append(original_row_obj_anim)
                                else:
                                    self.log_warning(f"Logic error: Row {original_idx_anim} from original run selection not found in original data or reloaded map.")
                            data_for_pipeline = updated_pipeline_data_anim
                            self.log_info(f"Animation Stage: Sheet data reloaded. Pipeline now has {len(data_for_pipeline)} rows.")
                        else:
                            self.log_warning("Animation Stage: Failed to reload sheet data. Continuing with potentially stale animation links.")
                    else:
                        self.log_info("Animation Stage: No animation tasks were created by animate_images_batch.")
                else:
                    self.log_info("Animation Stage: No rows met criteria for new animation.")
                self.log_info("--- Pipeline: Finished Global Animation Stage ---")
            else:
                self.log_info("Animation Stage: No rows met criteria for new animation.")
                self.log_info("--- Pipeline: Finished Global Animation Stage ---")

            # 5. Main Pipeline: Enhanced logic with ZapCap Task ID checking
            self.log_info(f"--- Pipeline: Starting Main Data Processing for {len(data_for_pipeline)} rows ---")

            # Initialize pipeline resources
            zap_workers_actually_started = 0
            for i in range(min(4, len(data_for_pipeline))):
                try:
                    self.zap_pool.submit(self._zapcap_worker)
                    zap_workers_actually_started += 1
                except Exception as e:
                    self.log_error(f"Failed to start ZapCap worker {i}: {e}")

            if zap_workers_actually_started > 0:
                self.log_info(f"Pipeline: Launched {zap_workers_actually_started} ZapCap worker threads.")

            # Process each row with enhanced logic
            next_vo_future = None
            for i, row_data in enumerate(data_for_pipeline):
                row_idx = row_data.get('original_row_index', i + start_row)
                self.log_info(f"Pipeline Main Loop: Preparing row {row_idx} ({i+1}/{len(data_for_pipeline)}) for video processing.")

                # Enhanced logic: Check what's needed for this row
                final_video_url = row_data.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'), '').strip()
                existing_zapcap_task_id = row_data.get(config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID'), '').strip()
                script = row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '').strip()

                # Case 1: Already has Final Video URL - skip completely
                if final_video_url:
                    self.log_info(f"Pipeline: Row {row_idx} SKIPPED - already has Final Video URL.")
                    continue
                
                # Case 1.5: Already handled in orphaned videos check - skip
                if row_data.get('_zapcap_handled'):
                    self.log_info(f"Pipeline: Row {row_idx} SKIPPED - already handled in ZapCap check.")
                    continue

                # Case 2: Has ZapCap Task ID but no Final Video URL - check status
                if existing_zapcap_task_id:
                    self.log_info(f"Pipeline: Row {row_idx} has existing ZapCap Task ID: {existing_zapcap_task_id}. Checking status.")
                    should_create_new = self._handle_existing_zapcap_task(row_data, existing_zapcap_task_id)
                    if not should_create_new:
                        continue  # Task was handled (added to monitoring or completed)
                    # If should_create_new is True, fall through to create new video

                # Case 3: No Final Video URL and no ZapCap Task ID - create new video
                if not script:
                    self.log_info(f"Pipeline: Row {row_idx} SKIPPED - no script.")
                    continue

                # IMPORTANT: Check for images BEFORE creating audio to avoid wasted TTS calls
                animated_links = [row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}')) for i in range(1, 5) if row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{i}', f'Animated Image {i}'))]
                image_links = [row_data.get(config.COLUMNS.get(f'IMAGE_LINK_{i}', f'Image Link {i}')) for i in range(1, 5) if row_data.get(config.COLUMNS.get(f'IMAGE_LINK_{i}', f'Image Link {i}'))]
                
                if not animated_links and not image_links:
                    self.log_warning(f"Pipeline: Row {row_idx} SKIPPED - no valid images or animated images found. Cannot create video.")
                    self._update_sheet_status(row_idx, "Skipped: No valid images for video creation (pipeline)")
                    continue

                self.log_info(f"Pipeline: Row {row_idx} needs complete video creation (no Final Video URL, no ZapCap Task ID).")

                # TTS Processing with prefetch
                current_vo_data = None
                if next_vo_future is None:
                    self.log_info(f"Pipeline: Row {row_idx} is first with script or TTS not prefetched. Generating VO now (synchronously for this row).")
                    current_vo_data = self._generate_vo_for_row(row_data)
                else:
                    current_vo_data = next_vo_future.result()
                    self.log_info(f"Pipeline: VO for row {row_idx} (from future) ready. Size: {len(current_vo_data) if current_vo_data else 0}.")

                # Prefetch TTS for next row that needs processing
                if i + 1 < len(data_for_pipeline):
                    next_row_data = data_for_pipeline[i + 1]
                    next_final_url = next_row_data.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'), '').strip()
                    next_task_id = next_row_data.get(config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID'), '').strip()
                    next_script = next_row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '').strip()
                    
                    # Check if next row has images before prefetching TTS
                    next_animated_links = [next_row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{j}', f'Animated Image {j}')) for j in range(1, 5) if next_row_data.get(config.COLUMNS.get(f'ANIMATED_IMAGE_{j}', f'Animated Image {j}'))]
                    next_image_links = [next_row_data.get(config.COLUMNS.get(f'IMAGE_LINK_{j}', f'Image Link {j}')) for j in range(1, 5) if next_row_data.get(config.COLUMNS.get(f'IMAGE_LINK_{j}', f'Image Link {j}'))]
                    
                    # Only prefetch if next row needs complete processing AND has images
                    if not next_final_url and not next_task_id and next_script and (next_animated_links or next_image_links):
                        self.log_info(f"Pipeline: Submitting TTS prefetch for next row {next_row_data.get('original_row_index', i + start_row + 1)}.")
                        next_vo_future = self.tts_pool.submit(self._generate_vo_for_row, next_row_data)
                    else:
                        next_vo_future = None
                else:
                    next_vo_future = None

                # Video processing
                if current_vo_data:
                    self.log_info(f"Pipeline: Submitting video rendering & queueing for row {row_idx} to video_processing_pool.")
                    row_data_with_audio = row_data.copy()
                    row_data_with_audio['audio_data'] = current_vo_data
                    self.video_processing_pool.submit(self._render_video_and_queue_for_zapcap, row_data_with_audio)
                else:
                    self.log_info(f"Pipeline: Row {row_idx} SKIPPED - no audio data generated.")

            # Wait for all video processing to complete FIRST
            timeout_wait_for_video_pool = 300
            self.log_info(f"Pipeline: Waiting up to {timeout_wait_for_video_pool}s for video processing pool to finish.")
            self.video_processing_pool.shutdown(wait=True)
            
            # IMPORTANT FIX: Signal completion ONLY AFTER all videos are created and queued
            # This ensures ZapCap workers don't exit before videos arrive in the queue
            self.log_info("Pipeline: All videos created and queued. Now signaling ZapCap workers that producers are done.")
            self.video_producers_done_event.set()

            # Wait for ZapCap queue to be processed
            timeout_wait_for_zapcap_queue = 3600  # 60 minutes - significantly increased for better ZapCap processing and longer task completion time
            try:
                self.video_q.join(timeout=timeout_wait_for_zapcap_queue)
                self.log_info("Pipeline: ZapCap queue fully processed.")
            except:
                self.log_warning(f"Pipeline: ZapCap queue processing timed out after {timeout_wait_for_zapcap_queue}s.")

            # Final monitoring and cleanup
            self._final_monitoring_and_cleanup()

        except Exception as e:
            self.log_error(f"Pipeline run failed: {e}")
            self.log_error(traceback.format_exc())
        finally:
            self._cleanup_pipeline_resources()

    def _should_skip_row_completely(self, row_data):
        """Check if row should be skipped entirely (has Final Video URL)."""
        final_video_url = row_data.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'), '').strip()
        return bool(final_video_url)

    def _should_skip_row_for_video_processing(self, row_data):
        """Check if row should skip video processing (but might need ZapCap monitoring)."""
        return self._should_skip_row_completely(row_data)

    def _handle_orphaned_videos(self, data_for_pipeline):
        """Handle rows that have existing ZapCap Task IDs - check their status to see if they're completed or need monitoring.
        CONSERVATIVE APPROACH: Don't clear any Task IDs automatically - let them be checked."""
        self.log_info("--- Pipeline: Checking existing ZapCap Task IDs for completion status ---")
        
        completed_zapcap_rows = []
        
        for row_data in data_for_pipeline:
            final_video_url = row_data.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'), '').strip()
            zapcap_task_id = row_data.get(config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID'), '').strip()
            script = row_data.get(config.COLUMNS.get('SCRIPT', 'Script'), '').strip()
            
            # Only check rows that have ZapCap Task ID but no Final Video URL yet
            if not final_video_url and zapcap_task_id and script:
                # IMPORTANT: Don't automatically classify as "orphaned" - check status first
                # Even if Task ID looks suspicious, it might be real - let status check decide
                self.log_info(f"Pipeline: Found row {row_data.get('original_row_index', 'N/A')} with ZapCap Task ID: {zapcap_task_id} - will check status")
                completed_zapcap_rows.append(row_data)
        
        # NO MORE ORPHANED VIDEO DETECTION - preserve all Task IDs
        self.log_info("Pipeline: CONSERVATIVE MODE - preserving all ZapCap Task IDs for status checking")
        
        # Handle completed ZapCap tasks
        if completed_zapcap_rows:
            self.log_info(f"Pipeline: Found {len(completed_zapcap_rows)} rows with ZapCap Task IDs. Checking for completed tasks...")
            
            for row_data in completed_zapcap_rows:
                row_idx = row_data.get('original_row_index', 'N/A')
                zapcap_task_id = row_data.get(config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID'), '').strip()
                
                self.log_info(f"Pipeline: Checking ZapCap task {zapcap_task_id} for row {row_idx}")
                
                # Use the existing function to handle this
                should_create_new = self._handle_existing_zapcap_task(row_data, zapcap_task_id)
                
                if not should_create_new:
                    # Task was handled (completed or added to monitoring)
                    # Update the pipeline data to reflect that this row doesn't need processing
                    row_data['_zapcap_handled'] = True
        else:
            self.log_info("Pipeline: No rows with ZapCap Task IDs found.")

    def _handle_existing_zapcap_task(self, row_data, task_id):
        """Handle row with existing ZapCap Task ID - check status immediately and decide next action.
        Returns True if should create new video, False if task is being monitored/completed."""
        row_idx = row_data.get('original_row_index', 'N/A')
        
        try:
            self.log_info(f"Pipeline: Immediately checking ZapCap task {task_id} status for row {row_idx}")
            
            # Check status immediately
            status_result = self._check_zapcap_status_by_task_id(task_id)
            
            if status_result is None or status_result.get('status') == 'not_found':
                # Task not found - this means the task was deleted or never existed
                # Clear the Task ID and allow creation of a new video
                self.log_warning(f"Pipeline: ZapCap task {task_id} not found for row {row_idx}. Task may have been deleted or never existed. Clearing Task ID to allow new video creation.")
                
                try:
                    # Clear ZapCap Task ID
                    zapcap_task_col = config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID')
                    col_letter = self._get_column_letter(zapcap_task_col)
                    if col_letter:
                        cell_range = f"{col_letter}{row_idx}"
                        self.sheet.update(cell_range, [[""]])
                        self.log_info(f"Pipeline: Cleared ZapCap Task ID for row {row_idx}")
                    
                    # Update status to indicate we're creating new video
                    status_col = config.COLUMNS.get('STATUS', 'Status')
                    col_letter = self._get_column_letter(status_col)
                    if col_letter:
                        cell_range = f"{col_letter}{row_idx}"
                        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        status_message = f"{current_time_str} - ZapCap task not found, cleared Task ID, creating new video"
                        self.sheet.update(cell_range, [[status_message]])
                        self.log_info(f"Pipeline: Updated status for row {row_idx} - will create new video")
                except Exception as e_status:
                    self.log_error(f"Pipeline: Error updating sheet for row {row_idx}: {e_status}")
                
                # IMPORTANT: Return True to create new video since the old task doesn't exist
                return True  # Create new video since old task is gone
            
            elif status_result.get('status') == 'completed':
                # Task completed - download and process immediately
                self.log_info(f"Pipeline: ZapCap task {task_id} completed for row {row_idx}. Processing immediately.")
                
                download_url = status_result.get('downloadUrl') or status_result.get('video_url')
                if download_url:
                    try:
                        # Download video
                        self.log_info(f"Pipeline: Downloading video from {download_url} for task {task_id}")
                        video_response = requests.get(download_url, timeout=300)  # 5 minutes for video download
                        if video_response.status_code == 200:
                            video_data = video_response.content
                            self.log_info(f"Pipeline: Downloaded video {task_id} ({len(video_data) // 1024} KB)")
                            
                            # Upload to bucket and update sheet
                            file_name = row_data.get(config.COLUMNS.get('NAME', 'Name'), f"video_row_{row_idx}")
                            
                            # Save to temp file
                            import tempfile
                            with tempfile.NamedTemporaryFile(suffix=".mp4", dir=self.temp_dir, delete=False) as temp_file:
                                temp_file.write(video_data)
                                temp_file_path = temp_file.name
                            
                            self.log_info(f"Pipeline: Saved video to temp file {temp_file_path}")
                            
                            # Upload to bucket using the corrected function call
                            upload_success = self.upload_to_bucket_and_update_sheet(temp_file_path, row_idx, file_name)
                            
                            # Clean up temp file
                            try:
                                os.remove(temp_file_path)
                                self.log_info(f"Pipeline: Cleaned up temp file {temp_file_path}")
                            except Exception as e_cleanup:
                                self.log_warning(f"Pipeline: Error cleaning temp file {temp_file_path}: {e_cleanup}")
                            
                            if upload_success:
                                # Clear ZapCap Task ID and Status since we're done
                                try:
                                    zapcap_task_col = config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID')
                                    col_letter = self._get_column_letter(zapcap_task_col)
                                    if col_letter:
                                        cell_range = f"{col_letter}{row_idx}"
                                        self.sheet.update(cell_range, [[""]])
                                    
                                    status_col = config.COLUMNS.get('STATUS', 'Status')
                                    col_letter = self._get_column_letter(status_col)
                                    if col_letter:
                                        cell_range = f"{col_letter}{row_idx}"
                                        self.sheet.update(cell_range, [[""]])
                                        
                                    self.log_info(f"Pipeline: Cleared ZapCap columns for completed row {row_idx}")
                                except Exception as e_clear:
                                    self.log_error(f"Pipeline: Error clearing ZapCap columns for row {row_idx}: {e_clear}")
                                
                                self.log_success(f"Pipeline: Successfully processed completed ZapCap task {task_id} for row {row_idx}")
                                return False  # Don't create new video
                            else:
                                self.log_error(f"Pipeline: Failed to upload video for completed task {task_id} row {row_idx}")
                                # IMPORTANT: Don't create new video - preserve the Task ID and try upload again next run
                                self._update_sheet_status(row_idx, f"ZapCap completed but upload failed: {task_id} - will retry upload next run")
                                self.log_info(f"Pipeline: Preserving Task ID {task_id} for upload retry in next run")
                                return False  # Don't create new video, keep existing Task ID
                        else:
                            self.log_error(f"Pipeline: Failed to download video for task {task_id}: {video_response.status_code}")
                            self.log_error(f"Pipeline: Response text: {video_response.text[:500]}")
                            # IMPORTANT: Don't create new video - preserve Task ID and try download again next run
                            self._update_sheet_status(row_idx, f"ZapCap completed but download failed: {task_id} - will retry download next run")
                            self.log_info(f"Pipeline: Preserving Task ID {task_id} for download retry in next run")
                            return False  # Don't create new video, keep existing Task ID
                    except Exception as e_download:
                        self.log_error(f"Pipeline: Error downloading/processing completed task {task_id} for row {row_idx}: {e_download}")
                        self.log_error(traceback.format_exc())
                        # IMPORTANT: Don't create new video - preserve Task ID and try again next run
                        self._update_sheet_status(row_idx, f"ZapCap completed but processing error: {task_id} - will retry next run")
                        self.log_info(f"Pipeline: Preserving Task ID {task_id} for retry in next run after processing error")
                        return False  # Don't create new video, keep existing Task ID
                else:
                    self.log_error(f"Pipeline: No download URL for completed task {task_id} row {row_idx}")
                    self.log_error(f"Pipeline: Status result: {status_result}")
                    # IMPORTANT: Don't create new video - preserve Task ID and check again next run (URL might appear)
                    self._update_sheet_status(row_idx, f"ZapCap completed but no download URL: {task_id} - will check again next run")
                    self.log_info(f"Pipeline: Preserving Task ID {task_id} for URL check in next run")
                    return False  # Don't create new video, keep existing Task ID
            
            else:
                # Task exists but not completed - add to monitoring
                self.log_info(f"Pipeline: ZapCap task {task_id} status '{status_result.get('status')}' for row {row_idx}. Adding to monitoring.")
                task_to_monitor = {
                    "task_id": task_id,
                    "video_id": status_result.get('video_id'),
                    "row": row_idx,
                    "file_name": row_data.get(config.COLUMNS.get('NAME', 'Name'), f"video_row_{row_idx}"),
                    "row_data": row_data.copy()  # Make sure to copy the row data
                }
                
                with self._zap_lock:
                    self.tasks_for_final_monitoring.append(task_to_monitor)
                
                return False  # Don't create new video, wait for completion
            
        except Exception as e:
            self.log_error(f"Pipeline: Error handling existing ZapCap task {task_id} for row {row_idx}: {e}")
            self.log_error(traceback.format_exc())
            # IMPORTANT: Don't create new video even on error - preserve Task ID for future runs
            self._update_sheet_status(row_idx, f"Error checking ZapCap task: {task_id} - will retry next run")
            self.log_info(f"Pipeline: Preserving Task ID {task_id} for retry in next run after general error")
            return False  # Don't create new video, keep existing Task ID

    def _final_monitoring_and_cleanup(self):
        """Enhanced final monitoring with column cleanup."""
        # Existing monitoring logic
        ZAPCAP_MONITOR_BATCH_SIZE = 10
        MONITOR_BATCH_DELAY_SECONDS = 5

        if self.tasks_for_final_monitoring:
            self.log_info(f"--- Pipeline: Starting Final Batched Monitoring for {len(self.tasks_for_final_monitoring)} ZapCap tasks ---")
            for i in range(0, len(self.tasks_for_final_monitoring), ZAPCAP_MONITOR_BATCH_SIZE):
                batch_to_monitor = self.tasks_for_final_monitoring[i:i + ZAPCAP_MONITOR_BATCH_SIZE]
                self.log_info(f"Pipeline: Monitoring ZapCap batch {i//ZAPCAP_MONITOR_BATCH_SIZE + 1}/{math.ceil(len(self.tasks_for_final_monitoring)/ZAPCAP_MONITOR_BATCH_SIZE)} (Tasks: {[t.get('task_id') for t in batch_to_monitor]})")
                self.monitor_tasks_batch(batch_to_monitor)
                if (i + ZAPCAP_MONITOR_BATCH_SIZE) < len(self.tasks_for_final_monitoring) and MONITOR_BATCH_DELAY_SECONDS > 0:
                    self.log_info(f"Pipeline: Delaying {MONITOR_BATCH_DELAY_SECONDS}s before next ZapCap monitoring batch...")
                    time.sleep(MONITOR_BATCH_DELAY_SECONDS)
            self.log_info("--- Pipeline: Finished Final Batched ZapCap Monitoring ---")
        
        # NEW: Clean up ZapCap Task ID and Status columns
        self._cleanup_zapcap_columns()

    def _cleanup_zapcap_columns(self):
        """Clean up ZapCap Task ID and Status columns ONLY after successful completion.
        ULTRA-CONSERVATIVE: Only clean rows that have Final Video URL to preserve Task IDs for future checking."""
        try:
            self.log_info("Pipeline: Starting ULTRA-CONSERVATIVE cleanup of ZapCap columns...")
            
            # Read current sheet data
            data = self.read_google_sheet()
            if not data:
                self.log_warning("No data found for cleanup")
                return
            
            # Find ONLY rows that have Final Video URL (successfully completed)
            completed_rows = []
            
            for row_data in data:
                final_video_url = row_data.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'), '').strip()
                zapcap_task_id = row_data.get(config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID'), '').strip()
                
                # ONLY clean rows that have successfully completed (have Final Video URL)
                if final_video_url and zapcap_task_id:
                    completed_rows.append(row_data.get('original_row_index'))
            
            if completed_rows:
                self.log_info(f"Pipeline: Cleaning up ZapCap columns for {len(completed_rows)} SUCCESSFULLY COMPLETED rows: {completed_rows}")
                self.log_info("Pipeline: PRESERVING ALL Task IDs and Status messages for rows without Final Video URL!")
                
                # Clear the columns for completed rows only
                for row_idx in completed_rows:
                    try:
                        # Clear ZapCap Task ID
                        zapcap_task_col = config.COLUMNS.get('ZAPCAP_TASK_ID', 'ZapCap Task ID')
                        col_letter = self._get_column_letter(zapcap_task_col)
                        if col_letter:
                            cell_range = f"{col_letter}{row_idx}"
                            self.sheet.update(cell_range, [[""]])
                        
                        # Clear Status
                        status_col = config.COLUMNS.get('STATUS', 'Status')
                        col_letter = self._get_column_letter(status_col)
                        if col_letter:
                            cell_range = f"{col_letter}{row_idx}"
                            self.sheet.update(cell_range, [[""]])
                        
                        self.log_info(f"Cleaned Task ID and Status for successfully completed row {row_idx}")
                        
                    except Exception as e:
                        self.log_error(f"Failed to clean up row {row_idx}: {e}")
                
                self.log_info("Pipeline: Successfully cleaned up ZapCap columns for completed rows ONLY.")
            else:
                self.log_info("Pipeline: No completed rows found that need ZapCap column cleanup.")
                
        except Exception as e:
            self.log_error(f"Pipeline: Error during ZapCap column cleanup: {e}")

    def _cleanup_pipeline_resources(self):
        """Clean up pipeline resources."""
        self.log_info("--- Pipeline: Main Data Processing Finished ---")
        
        # Shutdown pools
        self.log_info("Shutting down TTS pool...")
        self.tts_pool.shutdown(wait=True)
        self.log_info("TTS pool shut down.")
        
        self.log_info("Shutting down Video Processing pool...")
        self.video_processing_pool.shutdown(wait=True)
        self.log_info("Video Processing pool shut down.")
        
        self.log_info("Shutting down ZapCap Submission pool...")
        self.zap_pool.shutdown(wait=True)
        self.log_info("ZapCap Submission pool shut down.")
        
        # Clean up temp files
        self.cleanup_temp_files()
        
        self.log_info("Run completed.")

    def _get_column_letter(self, column_name):
        """Get the column letter for a given column name."""
        try:
            headers = self.sheet.row_values(1)
            if column_name in headers:
                col_index = headers.index(column_name)
                # Convert to Excel column letters (A, B, C, ..., AA, AB, etc.)
                result = ""
                while col_index >= 0:
                    result = chr(col_index % 26 + 65) + result
                    col_index = col_index // 26 - 1
                return result
            return None
        except Exception as e:
            self.log_error(f"Error getting column letter for {column_name}: {e}")
            return None

    def read_google_sheet(self, start_row=2, end_row=None, specific_rows=None):
        """Read all data from the Google Sheet."""
        try:
            # IMPORTANT FIX: Use specific column indices to avoid duplicate column name issues
            # There are two "Voice" columns in the sheet - we want the first one (column 10)
            user_provided_headers = [
                'Country', 'Vertical', 'Language', 'Image Link 1', 'Image Link 2',
                'Image Link 3', 'Image Link 4', 'Caption Position', 'Script', 'Voice',
                'ZapCap Template', 'Zoom in?', 'Size', 'Animate the images?', 'Free Text',
                'Name', 'Final Video url', 'Animated Image 1', 'Animated Image 2',
                'Animated Image 3', 'Animated Image 4', 'Status', 'ZapCap Task ID'
            ]
            for col_key, col_name_from_config in config.COLUMNS.items():
                if col_name_from_config not in user_provided_headers:
                    user_provided_headers.append(col_name_from_config)

            self.log_info(f"Effective headers for sheet reading: {user_provided_headers}")
            all_sheet_data = []
            try:
                # IMPORTANT FIX: Read raw data and manually map to avoid duplicate column issues
                all_values = self.sheet.get_all_values()
                if not all_values or len(all_values) < 2:
                    self.log_warning("Sheet is empty or has no data rows.")
                    return
                
                headers = all_values[0]  # First row is headers
                self.log_info(f"Actual sheet headers: {headers}")
                
                # Find the correct Voice column dynamically
                voice_column_index = None
                for i, header in enumerate(headers):
                    if header == 'Voice':
                        voice_column_index = i
                        break
                
                if voice_column_index is not None:
                    self.log_info(f"Using Voice column at index {voice_column_index}: '{headers[voice_column_index]}'")
                else:
                    self.log_error(f"Voice column not found in headers: {headers}")
                    voice_column_index = 9  # Fallback to old behavior
                
                # Convert to records manually
                for i, row_values in enumerate(all_values[1:], start=2):  # Skip header row
                    record = {}
                    for j, header in enumerate(user_provided_headers):
                        if j < len(row_values):
                            # Special handling for Voice column - use the correct index
                            if header == 'Voice' and voice_column_index is not None and voice_column_index < len(row_values):
                                record[header] = row_values[voice_column_index]
                            else:
                                # Find the header in the actual sheet headers
                                try:
                                    actual_index = headers.index(header)
                                    record[header] = row_values[actual_index] if actual_index < len(row_values) else ''
                                except ValueError:
                                    record[header] = ''  # Header not found
                        else:
                            record[header] = ''
                    
                    record['original_row_index'] = i
                    all_sheet_data.append(record)
                    
            except Exception as e_sheet_read_initial:
                self.log_error(f"CRITICAL: Failed to read sheet data initially: {e_sheet_read_initial}")
                self.log_error(traceback.format_exc())
                return

            if not all_sheet_data:
                self.log_warning("Sheet is empty or no data rows could be read.")
                return

            initial_rows = []
            vertical_col_name = config.COLUMNS.get('VERTICAL', 'Vertical')
            for i, record in enumerate(all_sheet_data):
                record['original_row_index'] = i + 2
                if not str(record.get(vertical_col_name, '')).strip():
                    continue
                initial_rows.append(record)
            self.log_info(f"Read {len(all_sheet_data)} total data rows from sheet, {len(initial_rows)} rows after filtering empty Vertical column.")

            selected_rows_for_run = []
            if specific_rows:
                valid_specific_rows = {int(r) for r in specific_rows if str(r).isdigit() and int(r) >= 2}
                selected_rows_for_run = [r for r in initial_rows if r.get('original_row_index') in valid_specific_rows]
                self.log_info(f"Processing {len(selected_rows_for_run)} specific rows: {sorted(list(valid_specific_rows))}")
                
                # Additional debug logging
                if not selected_rows_for_run:
                    self.log_warning(f"No rows found for specific rows: {sorted(list(valid_specific_rows))}")
                    self.log_warning(f"Available row indices: {[r.get('original_row_index') for r in initial_rows[:20]]}")
                
            else:
                actual_start_row = start_row if start_row >= 2 else 2
                
                # Important fix: Don't limit by the data that was read, let the system process everything
                if end_row is None:
                    # Instead of limiting by len(all_sheet_data), let's read the actual range from sheet
                    try:
                        # Check how many rows are actually in the sheet by reading the first column
                        all_values = self.sheet.get_all_values()
                        actual_total_rows = len(all_values)
                        self.log_info(f"Sheet contains {actual_total_rows} total rows (including headers)")
                        actual_end_row = actual_total_rows  # Includes the header row, so the last row is actually actual_total_rows
                    except Exception as e_count:
                        self.log_warning(f"Failed to get actual row count, using fallback: {e_count}")
                        actual_end_row = len(all_sheet_data) + 1  # Fallback to the old method
                else:
                    actual_end_row = end_row
                
                # Now filter the rows by the actual range
                selected_rows_for_run = [r for r in initial_rows if actual_start_row <= r.get('original_row_index', -1) <= actual_end_row]
                self.log_info(f"Processing rows from {actual_start_row} to {actual_end_row}. Filtered to {len(selected_rows_for_run)} rows from {len(initial_rows)} available rows.")

            if not selected_rows_for_run:
                self.log_warning("Pipeline: No rows to process after initial filtering and row selection.")
                self.cleanup_temp_files()
                self.log_success("Processing finished (no rows for pipeline).")
                return

            data_for_pipeline = selected_rows_for_run

            return data_for_pipeline

        except Exception as e:
            self.log_error(f"Error reading Google Sheet: {e}")
            self.log_error(traceback.format_exc())
            return None