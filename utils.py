from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

from fastmcp import FastMCP, Context
import subprocess
import tempfile
import os
from typing import Dict, List, Any
import asyncio
import re # For validation
from dotenv import load_dotenv # For .env file

from gcs_helper import upload_artifacts_to_gcs # Import the helper

load_dotenv() # Load environment variables from .env

import logging # Ensure logging is imported
# Configure basic logging to see INFO level messages
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()])

# Configuration - BUCKET_NAME will now be loaded from .env or environment
BUCKET_NAME = os.getenv("BUCKET_NAME") 

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

# Create FastMCP server instance
mcp = FastMCP("Python Code Executor")

# --- Internal Library Validation Logic ---
async def _perform_library_validation(code: str, ctx: Context) -> Dict[str, Any]:
    """
    Internal logic to validate that the provided code only uses allowed libraries.
    """
    await ctx.info("Performing library validation")
    
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

        # Removed special handling for google.cloud.storage as it's no longer user-allowed

        if is_allowed:
            allowed_imports_details.append({"module": module_name_str})
        else:
            disallowed_imports_details.append({"module": module_name_str, "root_attempted": root_module_name})
            
    is_valid = not disallowed_imports_details
    validation_message = "All imports appear to be allowed." if is_valid else "Disallowed imports found."
    
    if disallowed_imports_details:
        await ctx.warning(f"Disallowed imports: {disallowed_imports_details}")
        
    return {
        "is_valid": is_valid,
        "validation_message": validation_message,
        "allowed_imports_found": allowed_imports_details,
        "disallowed_imports_found": disallowed_imports_details,
    }

# --- MCP Tool: Execute Python Code ---
@mcp.tool
async def execute_python_code(ctx: Context, code: str) -> Dict[str, Any]:
    """
    Executes the provided Python code in an isolated environment.
    Only allows a predefined set of libraries.
    Uploads any generated files (artifacts) to Google Cloud Storage using gcs_helper.

    Args:
        ctx: The MCP Context (injected by FastMCP).
        code: The Python code string to execute.
        
    Returns:
        A dictionary containing:
        - "output": The standard output from the code execution, or relevant error messages.
        - "artifacts": A list of GCS URIs for any generated files.
    """
    await ctx.info(f"Received code for execution ({len(code)} chars). Validating libraries...")
    
    validation_result = await _perform_library_validation(code, ctx)
    output_message = ""
    artifacts_uploaded: List[str] = []
    
    if not validation_result["is_valid"]:
        await ctx.error("Code validation failed. Execution aborted.")
        output_message = (
            f"ERROR: Code validation failed.\n{validation_result['validation_message']}\n"
            f"Disallowed imports: {validation_result['disallowed_imports_found']}"
        )
        return {
            "output": output_message,
            "artifacts": artifacts_uploaded
        }
    
    await ctx.info("Library validation passed. Proceeding with execution.")
    
    with tempfile.TemporaryDirectory() as workdir:
        await ctx.info(f"Created temporary directory: {workdir}")
        script_path = os.path.join(workdir, "script.py")
        
        with open(script_path, "w") as f:
            f.write(code)
        await ctx.info("Code written to script.py")
        
        # Initialize artifacts_uploaded here to ensure it's always a list
        artifacts_uploaded: List[str] = []

        try:
            await ctx.info("Executing Python code...")
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
                    await ctx.info(f"Code execution successful. Output: {output_message[:200]}...")
                else:
                    await ctx.error(f"Code execution failed with return code {proc.returncode}. Output: {output_message[:200]}...")

            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                output_message = "ERROR: Execution timed out after 60 seconds"
                await ctx.error(output_message)
        
        except FileNotFoundError:
            output_message = "ERROR: Python interpreter not found"
            await ctx.error(output_message)
        except Exception as e:
            output_message = f"ERROR: An unexpected error occurred during execution: {str(e)}"
            await ctx.error(output_message)

        # Upload artifacts if execution was at least attempted
        upload_error_message = None
        
        if BUCKET_NAME and BUCKET_NAME != "YOUR_BUCKET_NAME":
            uploaded_uris, error_from_helper = await upload_artifacts_to_gcs(
                workdir=workdir,
                bucket_name=BUCKET_NAME,
                ctx=ctx
            )
            artifacts_uploaded.extend(uploaded_uris)
            if error_from_helper:
                upload_error_message = error_from_helper
                output_message += f"\n[ARTIFACT UPLOAD WARNING]: {upload_error_message}"
        else:
            warning_msg = "BUCKET_NAME is not configured in environment. Skipping artifact upload."
            await ctx.warning(warning_msg)
            output_message += f"\n[ARTIFACT UPLOAD WARNING]: {warning_msg}"

    return {
        "output": output_message,
        "artifacts": artifacts_uploaded
    }

# --- MCP Resource: Allowed Libraries and Versions ---
@mcp.resource("docs://allowed-libraries-versions")
def get_allowed_libraries_versions_docs():
    """
    Provides a list of allowed Python libraries for code execution.
    Versions should be checked against the project's requirements.txt.
    """
    # These names should match the root import names used in _perform_library_validation
    # Now derived from the central config
    allowed_third_party_for_docs = list(ALLOWED_THIRD_PARTY_LIBS_CONFIG.values())
    
    # Attempt to read versions from requirements.txt if possible
    # This is a simplified parser, assumes format like 'library==version' or 'library'
    versions = {}
    try:
        req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "==" in line:
                        name, version = line.split("==", 1)
                        versions[name.lower()] = version
                    else:
                        versions[line.lower()] = "Not specified (latest or environment default)"
    except Exception:
        # Silently ignore errors in reading requirements for this informational resource
        pass

    doc_content = """# Allowed Python Libraries

This server allows Python code execution with a restricted set of libraries for security and stability.

## Third-Party Libraries Allowed:
"""
    for lib_name_display in allowed_third_party_for_docs:
        # Try to find version info
        # Determine the lookup name for requirements.txt (e.g., "docx" from "docx (for python-docx)")
        if " (for " in lib_name_display:
            lookup_name = lib_name_display.split(" (for ")[1][:-1].lower() # e.g. python-docx
        else:
            lookup_name = lib_name_display.lower()

        version_info = versions.get(lookup_name, "Version not pinned in requirements.txt, check file.")
        doc_content += f"- **{lib_name_display}**: `{version_info}`\n"

    doc_content += """
## Python Standard Library:
All modules from the Python Standard Library (e.g., `os`, `sys`, `json`, `datetime`, `re`, `math`, `collections`, `tempfile`, etc.) are also allowed and do not need to be listed here.

## Important Notes:
- Ensure your `requirements.txt` file accurately reflects the versions you intend to use for third-party libraries. This documentation provides a general list; `requirements.txt` is the source of truth for exact versions.
- Code attempting to import unlisted third-party libraries or modules will be rejected by the validation step before execution.
"""
    return doc_content

# To run this server (example, not for production directly without a proper ASGI server like Uvicorn/Hypercorn):
# Needs BUCKET_NAME environment variable or direct assignment above.
# Example: uvicorn utils:mcp.app --reload

if __name__ == "__main__":
    mcp.run(transport="streamable-http")