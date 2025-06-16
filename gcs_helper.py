import os
import uuid # Imported uuid
from typing import Optional, List, Tuple, Any
from google.cloud import storage
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import RefreshError
import asyncio

# Optional: point to your JSON key via env var (or omit for ADC)
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
GCS_PROJECT_ID = os.getenv("GC_PROJECT_ID")

def get_client() -> storage.Client:
    """
    Return an authenticated GCS client. 
    If GOOGLE_APPLICATION_CREDENTIALS is set, uses that JSON key,
    otherwise falls back to ADC or project ID.
    """
    if SERVICE_ACCOUNT_JSON:
        return storage.Client.from_service_account_json(SERVICE_ACCOUNT_JSON)
    if GCS_PROJECT_ID:
        return storage.Client(project=GCS_PROJECT_ID)
    return storage.Client()

def blob_exists_and_download_to_variable(
    client: storage.Client,
    bucket_name: str,
    blob_path: str
) -> Optional[str]:
    """
    Check for a blob in GCS; if it exists, download its contents as UTF-8 text.

    Args:
        client: Authenticated google.cloud.storage.Client
        bucket_name: Name of your GCS bucket
        blob_path:    Path/key of the object in that bucket

    Returns:
        File contents as a str if present, otherwise None.
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if not blob.exists():
            return None
        data = blob.download_as_string()
        return data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)
    except GoogleAPIError as e:
        print(f"[GCS Error] {bucket_name}/{blob_path}: {e}")
        return None
    except Exception as e:
        print(f"[Unexpected Error] {bucket_name}/{blob_path}: {e}")
        return None

def upload_markdown_content(client: storage.Client, bucket_name: str, gcs_path: str, md_content: str) -> bool:
    """
    Upload markdown content to Google Cloud Storage.

    Args:
        client: Google Cloud Storage client instance
        bucket_name (str): Name of the GCS bucket
        gcs_path (str): Path where the markdown content will be stored in GCS
        md_content (str): Markdown content as string

    Returns:
        bool: True if upload was successful, False otherwise
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        
        # Upload the markdown content
        blob.upload_from_string(md_content, content_type='text/markdown')
        print(f'Uploaded markdown content to Google Cloud Storage bucket {bucket_name}/{gcs_path}.')
        return True
    except RefreshError as e: # Added specific exception handling
        print(f'GCS Authentication Error during markdown upload: {str(e)}. Please re-authenticate.')
        raise  # Re-raise the exception to stop the calling process
    except Exception as e:
        print(f'Error uploading markdown content: {str(e)}')
        return False
    
def upload_file(client, bucket_name, file_path, blob_path):
    try: # Added try block
        blob = client.bucket(bucket_name).blob(blob_path)
        blob.upload_from_filename(file_path, timeout=90)
        print(f'Uploaded {file_path} to Google Cloud Storage bucket {bucket_name}/{blob_path}.')
        return True
    except RefreshError as e: # Added specific exception handling
        print(f'GCS Authentication Error during file upload: {str(e)}. Please re-authenticate.')
        raise  # Re-raise the exception to stop the calling process
    except Exception as e: # Added general exception handling
        print(f'Error uploading file {file_path} to {bucket_name}/{blob_path}: {str(e)}')
        return False

async def upload_artifacts_to_gcs(
    workdir: str,
    bucket_name: str,
    ctx: Optional[Any] = None  # FastMCP Context or similar logger
) -> Tuple[List[str], Optional[str]]:
    """
    Scans a working directory for files (excluding script.py) and uploads them to GCS.

    Args:
        workdir: The local directory containing files to upload.
        bucket_name: The GCS bucket name.
        ctx: An optional context object (like FastMCP's) for logging.

    Returns:
        A tuple containing:
        - A list of GCS URIs for successfully uploaded artifacts.
        - An error message string if an error occurred, otherwise None.
    """
    artifacts_uploaded: List[str] = []
    error_msg_from_helper: Optional[str] = None

    # Check if BUCKET_NAME is valid before proceeding
    if not bucket_name or bucket_name == "YOUR_BUCKET_NAME" or bucket_name.strip() == "":
        log_msg = "GCS_HELPER: BUCKET_NAME is not configured or is invalid. Skipping artifact upload."
        if ctx and hasattr(ctx, 'warning'):
            await ctx.warning(log_msg)
        elif ctx and hasattr(ctx, 'info'): # Fallback if no warning method
            await ctx.info(log_msg)
        else:
            print(f"WARNING: {log_msg}") # Basic print if no ctx or suitable log method
        return [], "BUCKET_NAME not configured or invalid. Artifacts were not uploaded."

    try:
        if ctx and hasattr(ctx, 'info'):
            await ctx.info(f"GCS_HELPER: Scanning '{workdir}' for artifacts to upload to bucket '{bucket_name}'...")

        storage_client = storage.Client()  # Assumes GOOGLE_APPLICATION_CREDENTIALS or ADC is set up
        bucket = storage_client.bucket(bucket_name)
        
        found_files_to_upload = []
        for item_name in os.listdir(workdir):
            item_path = os.path.join(workdir, item_name)
            # Ensure it's a file and not the script itself or any hidden files like .DS_Store
            if os.path.isfile(item_path) and item_name != "script.py" and not item_name.startswith('.'):
                found_files_to_upload.append((item_path, item_name))
        
        if not found_files_to_upload:
            if ctx and hasattr(ctx, 'info'):
                await ctx.info("GCS_HELPER: No artifacts found to upload.")
            return [], None  # No error, just no files

        if ctx and hasattr(ctx, 'info'):
            await ctx.info(f"GCS_HELPER: Found {len(found_files_to_upload)} artifact(s).")

        for local_path, fname in found_files_to_upload:
            # Using a subfolder "artifacts" for better organization in the bucket
            blob_name = f"artifacts/{uuid.uuid4().hex}/{fname}"
            blob = bucket.blob(blob_name)
            
            if ctx and hasattr(ctx, 'info'):
                await ctx.info(f"GCS_HELPER: Uploading '{fname}' to gs://{bucket_name}/{blob_name}")
            
            # blob.upload_from_filename() is synchronous.
            # For a truly non-blocking server, this should be run in a thread pool:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, blob.upload_from_filename, local_path)
            # If asyncio.to_thread is available (Python 3.9+), it's cleaner:
            # await asyncio.to_thread(blob.upload_from_filename, local_path)
            artifacts_uploaded.append(f"gs://{bucket_name}/{blob_name}")
        
        if ctx and hasattr(ctx, 'info'):
            await ctx.info(f"GCS_HELPER: Successfully uploaded {len(artifacts_uploaded)} artifact(s).")

    except Exception as e:
        error_msg_from_helper = f"GCS_HELPER: Error during artifact upload: {str(e)}"
        if ctx and hasattr(ctx, 'error'):
            await ctx.error(error_msg_from_helper)
        elif ctx and hasattr(ctx, 'info'): # Fallback
            await ctx.info(f"ERROR: {error_msg_from_helper}")
        else:
            print(f"ERROR: {error_msg_from_helper}")
        # Return any partially uploaded artifacts along with the error
        return artifacts_uploaded, error_msg_from_helper
        
    return artifacts_uploaded, None  # Success, no error message
