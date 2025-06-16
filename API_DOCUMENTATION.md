# Python Code Executor API Documentation

This API provides a secure Python code execution service with restricted library access and automatic artifact uploading to Google Cloud Storage.

## Base URL
```
http://localhost:8000
```

## Endpoints

### 1. Execute Python Code

Execute Python code in an isolated environment with library restrictions.

**Endpoint:** `POST /execute_python_code`

**Request Body:**
```json
{
  "code": "string"
}
```

**Parameters:**
- `code` (string, required): The Python code to execute. Can include markdown code block formatting (```python) which will be automatically cleaned.

**Response:**
```json
{
  "output": "string",
  "artifacts": ["string"]
}
```

**Response Fields:**
- `output` (string): The standard output from code execution, including any error messages
- `artifacts` (array): List of GCS URIs for any files generated during execution

**Status Codes:**
- `200 OK`: Code executed successfully (even if the code itself had runtime errors)
- `400 Bad Request`: Code validation failed due to disallowed library imports
- `500 Internal Server Error`: Server-side execution error (e.g., Python interpreter not found)

**Example Request:**
```bash
curl -X POST "http://localhost:8000/execute_python_code" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "import pandas as pd\nimport matplotlib.pyplot as plt\n\n# Create sample data\ndata = {\"x\": [1, 2, 3, 4], \"y\": [2, 4, 6, 8]}\ndf = pd.DataFrame(data)\n\n# Create plot\nplt.figure(figsize=(8, 6))\nplt.plot(df[\"x\"], df[\"y\"], marker=\"o\")\nplt.title(\"Sample Plot\")\nplt.xlabel(\"X values\")\nplt.ylabel(\"Y values\")\nplt.savefig(\"sample_plot.png\")\nplt.show()\n\nprint(\"Plot created successfully!\")\nprint(df.head())"
  }'
```

**Example Response:**
```json
{
  "output": "Plot created successfully!\n   x  y\n0  1  2\n1  2  4\n2  3  6\n3  4  8\n",
  "artifacts": [
    "gs://your-bucket-name/artifacts/2025-06-16/sample_plot.png"
  ]
}
```

### 2. Get Allowed Libraries Documentation

Retrieve documentation about allowed Python libraries and their versions.

**Endpoint:** `GET /docs/allowed-libraries-versions`

**Response:** Plain text documentation

**Example Request:**
```bash
curl -X GET "http://localhost:8000/docs/allowed-libraries-versions"
```

**Example Response:**
```
# Allowed Python Libraries

This server allows Python code execution with a restricted set of libraries for security and stability.

## Third-Party Libraries Allowed:
- **seaborn**: 0.12.2
- **pandas**: 2.0.3
- **openpyxl**: 3.1.2
- **docx (for python-docx)**: 0.8.11
- **reportlab**: 4.0.4
- **matplotlib**: 3.7.2

## Python Standard Library:
All modules from the Python Standard Library (e.g., `os`, `sys`, `json`, `datetime`, `re`, `math`, `collections`, `tempfile`, etc.) are also allowed and do not need to be listed here.

## Important Notes:
- Ensure your `requirements.txt` file accurately reflects the versions you intend to use for third-party libraries.
- Code attempting to import unlisted third-party libraries or modules will be rejected by the validation step before execution.
```

## Library Restrictions

### Allowed Third-Party Libraries
- **seaborn**: Statistical data visualization
- **pandas**: Data manipulation and analysis
- **openpyxl**: Excel file operations
- **python-docx**: Word document creation and manipulation
- **reportlab**: PDF generation
- **matplotlib**: Plotting and visualization

### Allowed Standard Library Modules
All Python standard library modules are permitted, including but not limited to:
- `os`, `sys`, `json`, `csv`
- `datetime`, `time`, `re`, `math`, `random`
- `collections`, `itertools`, `functools`
- `pathlib`, `tempfile`, `uuid`, `io`
- `typing`, `warnings`, `logging`
- `subprocess`, `asyncio`

### Import Validation
- The service validates all import statements before execution
- Both `import module` and `from module import item` syntax are supported
- Submodules of allowed libraries are permitted (e.g., `matplotlib.pyplot`)
- Any attempt to import disallowed libraries will result in a 400 error

## Environment Configuration

### Required Environment Variables
- `BUCKET_NAME`: Google Cloud Storage bucket name for artifact uploads

### Optional Environment Variables
- `HOST`: Server host (default: "0.0.0.0")
- `PORT`: Server port (default: "8000")

## Artifact Handling

### Automatic Upload
- All files created in the working directory during code execution are automatically uploaded to GCS
- Files are uploaded with a timestamp-based path structure
- Original filenames are preserved

### Artifact Response
- Successfully uploaded files are returned as GCS URIs in the `artifacts` array
- Upload warnings/errors are appended to the output message
- If `BUCKET_NAME` is not configured, artifacts won't be uploaded but execution continues

## Error Handling

### Validation Errors (400)
Returned when code contains disallowed imports:
```json
{
  "detail": "ERROR: Code validation failed.\nDisallowed imports found.\nDisallowed imports: [{'module': 'requests', 'root_attempted': 'requests'}]"
}
```

### Execution Timeout
Code execution is limited to 60 seconds. Timeout results in:
```json
{
  "output": "ERROR: Execution timed out after 60 seconds",
  "artifacts": []
}
```

### Server Errors (500)
- Python interpreter not found
- Unexpected execution errors
- Critical system failures

## Usage Examples

### Data Analysis Example
```python
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Load and analyze data
data = {'category': ['A', 'B', 'C', 'D'], 'values': [23, 45, 56, 78]}
df = pd.DataFrame(data)

# Create visualization
plt.figure(figsize=(10, 6))
sns.barplot(data=df, x='category', y='values')
plt.title('Category Analysis')
plt.savefig('analysis.png', dpi=300, bbox_inches='tight')

print("Analysis complete!")
print(df.describe())
```

### Document Generation Example
```python
from docx import Document
from reportlab.pdfgen import canvas
import os

# Create Word document
doc = Document()
doc.add_heading('Report Title', 0)
doc.add_paragraph('This is a sample report generated by the API.')
doc.save('report.docx')

# Create PDF document
c = canvas.Canvas('report.pdf')
c.drawString(100, 750, 'Sample PDF Report')
c.drawString(100, 730, 'Generated automatically')
c.save()

print("Documents created successfully!")
print(f"Files in directory: {os.listdir('.')}")
```

## Rate Limiting and Security

### Security Measures
- Library import validation prevents arbitrary package installation
- Code execution runs in isolated temporary directories
- 60-second timeout prevents infinite loops
- No network access to external resources (except through allowed libraries)

### Best Practices
- Keep code execution time under 60 seconds
- Use relative paths for file operations (working directory is temporary)
- Ensure all required data is included in the code string
- Handle exceptions appropriately in your code

## Interactive Documentation

The service provides interactive API documentation via FastAPI's built-in features:

- **Swagger UI**: Available at `http://localhost:8000/docs`
- **ReDoc**: Available at `http://localhost:8000/redoc`
- **OpenAPI JSON**: Available at `http://localhost:8000/openapi.json`

These interfaces allow you to test the API endpoints directly from your browser.
