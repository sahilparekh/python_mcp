from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

import os
import logging # Ensure logging is imported
import asyncio
import tempfile
import re
from typing import Dict, List, Any

from fastapi import FastAPI, HTTPException, Body # For FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel # For request/response models if needed

from gcs_helper import upload_artifacts_to_gcs # Import the helper

# Configure basic logging to see INFO level messages
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()])

# Configuration - GCS_BUCKET_NAME will now be loaded from .env or environment
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

# --- Centralized Allowed Libraries Configuration ---
# Root module names for allowed third-party libraries
ALLOWED_THIRD_PARTY_LIBS_CONFIG = {
    "seaborn": "seaborn",
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "docx": "docx (for python-docx)", # Validation uses 'docx', docs display full name
    "reportlab": "reportlab",
    "matplotlib": "matplotlib",
}

# Create FastAPI server instance
app = FastAPI(title="Python Code Executor", version="1.0.0")

# --- Utility function to clean markdown code blocks ---
def clean_code_block(code: str) -> str:
    """
    Remove markdown code block demarcation (```python and ```) if present.
    
    Args:
        code: Raw code string that might be wrapped in markdown code blocks
        
    Returns:
        Cleaned code string without markdown demarcation
    """
    # Strip whitespace
    code = code.strip()
    
    # Check for code block patterns and remove them
    if code.startswith('```python') and code.endswith('```'):
        # Remove ```python at start and ``` at end
        code = code[9:-3].strip()  # 9 = len('```python')
    elif code.startswith('```') and code.endswith('```'):
        # Remove generic ``` at start and end
        code = code[3:-3].strip()
    
    return code

# --- Internal Library Validation Logic ---
async def _perform_library_validation(code: str) -> Dict[str, Any]:
    """
    Internal logic to validate that the provided code only uses allowed libraries.
    """
    logging.info("Performing library validation")
    
    # These are the *root* modules allowed.
    # Submodules of these are implicitly allowed (e.g., matplotlib.pyplot)
    allowed_third_party_libs = set(ALLOWED_THIRD_PARTY_LIBS_CONFIG.keys())
    
    # Standard library modules (not exhaustive, but common ones)
    # Users can generally import any standard library module.
    standard_libs = {
        "os", "sys", "json", "csv", "datetime", "time", "re", "math", "random",
        "collections", "itertools", "functools", "pathlib", "tempfile", "uuid",
        "io", "typing", "warnings", "logging", "subprocess", "asyncio"
    }
    
    all_allowed_roots = allowed_third_party_libs.union(standard_libs)
    
    # Regex to find import statements
    # Covers: import x; from x import y; import x.y as z; from x.y import z as a
    import_pattern = r'(?:^|;)\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))'
    
    imports_found = re.findall(import_pattern, code, re.MULTILINE)
    
    allowed_imports_details = []
    disallowed_imports_details = []
    
    for from_module, import_module in imports_found:
        module_name_str = from_module or import_module
        # Get the top-level package (e.g., "matplotlib.pyplot" -> "matplotlib")
        root_module_name = module_name_str.split('.')[0]
        
        is_allowed = root_module_name in all_allowed_roots

        if is_allowed:
            allowed_imports_details.append({"module": module_name_str})
        else:
            disallowed_imports_details.append({"module": module_name_str, "root_attempted": root_module_name})
            
    is_valid = not disallowed_imports_details
    validation_message = "All imports appear to be allowed." if is_valid else "Disallowed imports found."
    
    if disallowed_imports_details:
        logging.warning(f"Disallowed imports: {disallowed_imports_details}")
        
    return {
        "is_valid": is_valid,
        "validation_message": validation_message,
        "allowed_imports_found": allowed_imports_details,
        "disallowed_imports_found": disallowed_imports_details,
    }

# --- FastAPI Endpoint: Execute Python Code ---
class ExecuteCodeRequest(BaseModel):
    code: str

@app.post("/execute_python_code", summary="Execute Python Code")
async def execute_python_code(request: ExecuteCodeRequest) -> Dict[str, Any]:
    """
    Executes the provided Python code in an isolated environment.
    Only allows a predefined set of libraries.
    Uploads any generated files (artifacts) to Google Cloud Storage using gcs_helper.

    Args:
        request: A Pydantic model containing the 'code' string.
        
    Returns:
        A dictionary containing:
        - "output": The standard output from the code execution, or relevant error messages.
        - "artifacts": A list of GCS URIs for any generated files.
    """
    code = clean_code_block(request.code)
    logging.info(f"Received code for execution ({len(code)} chars). Validating libraries...")
    
    validation_result = await _perform_library_validation(code)
    output_message = ""
    artifacts_uploaded: List[str] = []
    
    if not validation_result["is_valid"]:
        logging.error("Code validation failed. Execution aborted.")
        output_message = (
            f"ERROR: Code validation failed.\n{validation_result['validation_message']}\n"
            f"Disallowed imports: {validation_result['disallowed_imports_found']}"
        )
        # Return a 400 Bad Request error
        raise HTTPException(status_code=400, detail=output_message)
    
    logging.info("Library validation passed. Proceeding with execution.")
    
    with tempfile.TemporaryDirectory() as workdir:
        logging.info(f"Created temporary directory: {workdir}")
        script_path = os.path.join(workdir, "script.py")
        
        with open(script_path, "w") as f:
            f.write(code)
        logging.info("Code written to script.py")
        
        artifacts_uploaded: List[str] = []

        try:
            logging.info("Executing Python code...")
            proc = await asyncio.create_subprocess_exec(
                "python", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, # Capture stderr to stdout
                cwd=workdir
            )
            
            try:
                stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=60.0)
                output_message = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
                if proc.returncode == 0:
                    logging.info(f"Code execution successful. Output: {output_message[:200]}...")
                else:
                    logging.error(f"Code execution failed with return code {proc.returncode}. Output: {output_message[:500]}...")
                    # No HTTPException here as we want to return the output

            except asyncio.TimeoutError:
                if proc.returncode is None: # Check if process is still running
                    try:
                        proc.kill()
                        await proc.wait() # Ensure process is reaped
                    except ProcessLookupError:
                        logging.warning("Process already terminated when trying to kill due to timeout.")
                output_message = "ERROR: Execution timed out after 60 seconds"
                logging.error(output_message)
                # Consider raising HTTPException for timeout if it's a client error
        
        except FileNotFoundError:
            output_message = "ERROR: Python interpreter not found"
            logging.error(output_message)
            raise HTTPException(status_code=500, detail=output_message) # Server-side issue
        except Exception as e:
            output_message = f"ERROR: An unexpected error occurred during execution: {str(e)}"
            logging.error(output_message, exc_info=True) # Log full traceback
            raise HTTPException(status_code=500, detail=output_message) # Server-side issue

        # Upload artifacts if execution was at least attempted
        upload_error_message = None
        
        if GCS_BUCKET_NAME and GCS_BUCKET_NAME != "YOUR_BUCKET_NAME":
            uploaded_uris, error_from_helper = await upload_artifacts_to_gcs(
                workdir=workdir,
                bucket_name=GCS_BUCKET_NAME,
                ctx=None  # gcs_helper supports None for ctx
            )
            artifacts_uploaded.extend(uploaded_uris)
            if error_from_helper:
                upload_error_message = error_from_helper
                output_message += f"\n[ARTIFACT UPLOAD WARNING]: {upload_error_message}"
                logging.warning(f"Artifact upload warning: {upload_error_message}")
        else:
            warning_msg = "GCS_BUCKET_NAME is not configured in environment. Skipping artifact upload."
            logging.warning(warning_msg)
            output_message += f"\n[ARTIFACT UPLOAD WARNING]: {warning_msg}"

    return {
        "output": output_message,
        "artifacts": artifacts_uploaded
    }

# --- FastAPI Endpoint: Allowed Libraries and Versions ---
@app.get("/docs/allowed-libraries-versions", summary="Get Allowed Libraries and Versions")
async def get_allowed_libraries_versions_docs() -> PlainTextResponse:
    """
    Provides a list of allowed Python libraries for code execution.
    Versions should be checked against the project's requirements.txt.
    """
    # These names should match the root import names used in _perform_library_validation
    # Now derived from the central config
    allowed_third_party_for_docs = list(ALLOWED_THIRD_PARTY_LIBS_CONFIG.values())
    
    versions = {}
    try:
        req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Handles 'library==version', 'library>=version', 'library'
                    match = re.match(r"^([a-zA-Z0-9_-]+)(?:[<>=!~]=?[\s]*[0-9\.\*a-zA-Z-]+)?", line)
                    if match:
                        lib_name = match.group(1).lower()
                        # Attempt to get full line for version, or mark as "any" or "pinned"
                        parts = re.split(r"[<>=!~]=", line, 1)
                        version_str = parts[1].strip() if len(parts) > 1 else "Any version specified or latest"
                        versions[lib_name] = version_str
    except Exception as e:
        logging.error(f"Error reading requirements.txt for docs: {e}", exc_info=True)
        # Silently ignore errors in reading requirements for this informational resource in terms of response
        pass

    doc_content = """# Allowed Python Libraries

This server allows Python code execution with a restricted set of libraries for security and stability.

## Third-Party Libraries Allowed:
"""
    for lib_name_display in allowed_third_party_for_docs:
        # Try to find version info
        # Determine the lookup name for requirements.txt (e.g., "python-docx" from "docx (for python-docx)")
        if " (for " in lib_name_display:
            # e.g. "python-docx" from "docx (for python-docx)"
            lookup_name = lib_name_display.split(" (for ")[1].replace(")", "").strip().lower()
        else:
            lookup_name = lib_name_display.lower()

        version_info = versions.get(lookup_name, "Version not explicitly pinned in requirements.txt, check file.")
        doc_content += f"- **{lib_name_display}**: `{version_info}`\n"

    doc_content += """
## Python Standard Library:
All modules from the Python Standard Library (e.g., `os`, `sys`, `json`, `datetime`, `re`, `math`, `collections`, `tempfile`, etc.) are also allowed and do not need to be listed here.

## Important Notes:
- Ensure your `requirements.txt` file accurately reflects the versions you intend to use for third-party libraries. This documentation provides a general list; `requirements.txt` is the source of truth for exact versions.
- Code attempting to import unlisted third-party libraries or modules will be rejected by the validation step before execution.
"""
    return PlainTextResponse(content=doc_content)


# To run this server (example, not for production directly without a proper ASGI server like Uvicorn/Hypercorn):
# Needs GCS_BUCKET_NAME environment variable or direct assignment above.
# Example: uvicorn utils:app --reload

if __name__ == "__main__":
    import uvicorn
    # It's good practice to make host and port configurable, e.g., via environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)