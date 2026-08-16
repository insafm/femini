# Femini API

REST API server that exposes a FastAPI interface to the Femini worker, which automates the Gemini web app (gemini.google.com) via Playwright browser automation. Femini does not use an official Google AI Studio API/SDK; it interacts with the Gemini web UI through an automated browser.

## Overview

Femini API is a standalone FastAPI service that provides HTTP/REST interface to the femini-playwright automation engine. It features:

- **REST API** - Standard HTTP endpoints
- **SSE Streaming** - Real-time updates via Server-Sent Events
- **SQLite Logging** - All requests/responses logged
- **Independent Module** - Imports femini-playwright as dependency
- **Docker Ready** - Containerized deployment

## Architecture

```
┌──────────────────────────────────────┐
│         Femini API Container         │
│  ┌────────────────────────────────┐  │
│  │   FastAPI Server (Port 8000)   │  │
│  │   - REST Endpoints             │  │
│  │   - SSE Streaming              │  │
│  │   - Request Validation         │  │
│  └──────────┬─────────────────────┘  │
│             │                         │
│  ┌──────────▼─────────────────────┐  │
│  │   SQLite Database              │  │
│  │   - Request/Response Logs      │  │
│  │   - Status Tracking            │  │
│  └──────────┬─────────────────────┘  │
│             │                         │
│  ┌──────────▼─────────────────────┐  │
│  │   FeminiApp (Embedded)         │  │
│  │   - Playwright Automation      │  │
│  │   - Queue Management           │  │
│  │   - Gemini AI Integration      │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

## API Endpoints

### Submit Request
```http
POST /api/v1/submit
Content-Type: application/json

{
  "prompt": "Your prompt here",
  "is_image": false,
  "force_text": true,
  "return_image_data": false,
  "download": true,
  "filename_suffix": "_suffix",
  "save_dir": "custom_folder",
  "credential_key": "account1",
  "credential_mode": "random",
  "gemini_model": "Flash",
  "required_json_keys": ["data"],
  "retry": true
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "status": "pending",
  "created_at": "2026-02-15T10:00:00",
  "stream_url": "/api/v1/stream/uuid"
}
```

### Stream Updates (SSE)
```http
GET /api/v1/stream/{task_id}
Accept: text/event-stream
```

**Event Stream:**
```
data: {"status":"pending","task_id":"uuid","message":"Request queued"}

data: {"status":"processing","task_id":"uuid","message":"Processing request"}

data: {"status":"completed","task_id":"uuid","result":{"text":"Response..."},"processing_time":12.5}
```

### Get Status
```http
GET /api/v1/status/{task_id}
```

**Response:**
```json
{
  "task_id": "uuid",
  "status": "completed",
  "created_at": "2026-02-15T10:00:00",
  "updated_at": "2026-02-15T10:00:15",
  "processing_time": 12.5
}
```

### Get Result
```http
GET /api/v1/result/{task_id}
```

**Response:**
```json
{
  "task_id": "uuid",
  "status": "completed",
  "prompt": "Your prompt",
  "is_image": false,
  "result": {
    "text": "Gemini response here",
    "chat_id": "...",
    "account_id": "..."
  },
  "processing_time": 12.5
}
```

### List Requests
```http
GET /api/v1/requests?limit=50&offset=0&status=completed
```

### Get Statistics
```http
GET /api/v1/stats
```

### Health Check
```http
GET /api/v1/health
```

## Usage Examples

### cURL
```bash
# Submit request
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Hello!","is_image":false,"force_text":true}'

# Stream updates
curl -N http://localhost:12000/api/v1/stream/{task_id}

# Get result
curl http://localhost:12000/api/v1/result/{task_id}
```

### Python
```python
import requests
import json

# Submit request
response = requests.post(
    "http://localhost:12000/api/v1/submit",
    json={
        "prompt": "What is the capital of France?",
        "is_image": False,
        "force_text": True
    }
)
data = response.json()
task_id = data["task_id"]
print(f"Task ID: {task_id}")

# Stream updates (SSE)
response = requests.get(
    f"http://localhost:12000/api/v1/stream/{task_id}",
    stream=True
)

for line in response.iter_lines():
    if line.startswith(b'data: '):
        event_data = json.loads(line[6:])
        print(f"Status: {event_data['status']}")
        
        if event_data['status'] == 'completed':
            print(f"Result: {event_data['result']}")
            break
```

### JavaScript/Browser
```javascript
// Submit request
const response = await fetch('http://localhost:12000/api/v1/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        prompt: 'Tell me a joke',
        is_image: false,
        force_text: true
    })
});

const {task_id, stream_url} = await response.json();

// Stream updates
const eventSource = new EventSource(`http://localhost:12000${stream_url}`);

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Status:', data.status);
    
    if (data.status === 'completed') {
        console.log('Result:', data.result);
        eventSource.close();
    }
};
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# API Server Settings
API_HOST=0.0.0.0
API_PORT=12000

# Database Settings
DATABASE_PATH=data/femini_api.db

# Google Gemini Credentials
# The Playwright engine expects GEMINI_CREDENTIALS as a JSON array string.
# Example (single-line JSON string in .env):
GEMINI_CREDENTIALS='[
  {"email":"user@gmail.com","password":"pass","key":"account1"},
  {"email":"user2@gmail.com","password":"pass2","key":"account2"}
]'

# Credential Management
CREDENTIAL_MODE=default
DEFAULT_CREDENTIAL_INDEX=0

# Concurrency Settings
MAX_CONCURRENT_PER_CREDENTIAL=1
MAX_TOTAL_CONCURRENT=10
WORKER_TASK_TIMEOUT=400

# Browser Settings
HEADLESS=true
SLOW_MO=0
REQUEST_TIMEOUT=180
BROWSER_CONTEXT_TIMEOUT=300
MAX_REQUESTS_PER_CONTEXT=50

# Directory Paths
USER_DATA_BASE_DIR=/app/user_data
COOKIES_BASE_DIR=/app/cookies
DOWNLOAD_DIR=/app/downloads
LOG_DIR=/app/logs

# Gemini Settings
BASE_URL=https://gemini.google.com/app?hl=en-IN
MAX_TIMEOUT=180
TIMEOUT=60
IMAGE_GENERATION_TIMEOUT=600
MAX_RETRIES=6
GEMINI_MODEL=Flash

# Response Settings
SAVE_RESPONSES=false      # Set to false for strictly opt-in downloads
NEW_CHAT_PER_REQUEST=false
RETURN_IMAGE_DATA=false
REMOVE_WATERMARK=true     # Automatically remove watermark from images

# Logging
LOG_LEVEL=INFO

# Python Path
PYTHONPATH=/app
```

Notes:
- The Playwright engine uses the GEMINI_CREDENTIALS env var (see femini-playwright/src/config.py).
- Do not commit `.env` containing secrets to source control.

## Docker Deployment

### Build and Run
```bash
# From project root
docker-compose up -d femini-api

# Check logs
docker-compose logs -f femini-api

# Check health
curl http://localhost:12000/api/v1/health
```

### Environment Variables
```yaml
services:
  femini-api:
    environment:
      - API_PORT=12000
      - GEMINI_CREDENTIALS=[...]
      - LOG_LEVEL=INFO
```

## Development

### Local Setup
```bash
cd femini-api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy env file
cp .env.example .env
# Edit .env with your credentials

# Run server
python -m src.api_server
```

### Testing
```bash
# Test health
curl http://localhost:12000/api/v1/health

# Test submission
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Test","is_image":false}'

# View API docs
open http://localhost:12000/docs
```

## Database

SQLite database stores all API requests and responses:

**Location:** `/app/data/femini_api.db`

**Schema:**
- `task_id` - Unique identifier
- `prompt` - User prompt
- `status` - pending/processing/completed/failed
- `result_json` - Full result as JSON
- `processing_time` - Time in seconds
- `created_at`, `updated_at` - Timestamps
- `filename_suffix`, `save_dir` - Custom path parameters
- `download` - Boolean opt-in flag

## Monitoring

### Health Check
```bash
curl http://localhost:12000/api/v1/health
```

### Statistics
```bash
curl http://localhost:12000/api/v1/stats
```

### Logs
```bash
docker-compose logs -f femini-api
```

## Security Notes

⚠️ **Production Considerations:**

1. **Authentication** - Add API key authentication
2. **CORS** - Configure allowed origins
3. **Rate Limiting** - Implement rate limits
4. **HTTPS** - Use reverse proxy (nginx/traefik)
5. **Credentials** - Use secrets management

## Troubleshooting

### API not starting
```bash
# Check logs
docker-compose logs femini-api

# Check environment
docker-compose exec femini-api env

# Rebuild
docker-compose build --no-cache femini-api
```

### No response from worker
- Check CREDENTIALS are set correctly
- Verify Google account credentials
- Check browser logs
- Ensure headless mode works on your system

### Database errors
```bash
# Check database path
docker-compose exec femini-api ls -la /app/data/

# Check permissions
docker-compose exec femini-api touch /app/data/test.txt
```

## 📄 License

For educational and personal use only. See the root [LICENSE](../LICENSE) for details.