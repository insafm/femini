# Femini API - Curl Examples

This document provides comprehensive curl examples for all Femini API endpoints.

> Note: Femini automates the Gemini web app (gemini.google.com) via Playwright browser automation. It does not use an official Google AI Studio API/SDK. The Playwright worker requires one or more Google accounts with Gemini access provided via the GEMINI_CREDENTIALS environment variable.

Example GEMINI_CREDENTIALS (.env single-line JSON string):
```env
GEMINI_CREDENTIALS='[
  {"email":"user@gmail.com","password":"pass","key":"account1"},
  {"email":"user2@gmail.com","password":"pass2","key":"account2"}
]'
```

Use the API base URL (default):
```
http://localhost:12000
```

## Base URL
```
http://localhost:12000
```

## 1. Root Endpoint

### GET /
Get basic API information.

```bash
curl -X GET http://localhost:12000/
```

**Response:**
```json
{
  "name": "Femini Playwright API",
  "version": "1.0.0",
  "docs": "/docs",
  "health": "/api/v1/health"
}
```

## 2. Health Check

### GET /api/v1/health
Check the health status of the API and worker.

```bash
curl -X GET http://localhost:12000/api/v1/health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-15T13:00:00.000000",
  "database": "connected",
  "worker": "running"
}
```

## 3. Submit Request

### POST /api/v1/submit
Submit a new request to the Gemini worker.

#### Basic Text Request
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Hello! How are you today?",
    "is_image": false,
    "force_text": true
  }'
```

**Response:**
```json
{
  "task_id": "abc123-def456-ghi789",
  "status": "pending",
  "created_at": "2026-02-15T13:00:00.000000",
  "stream_url": "/api/v1/stream/abc123-def456-ghi789"
}
```

#### Image Generation Request
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Generate a beautiful sunset over mountains",
    "is_image": true,
    "return_image_data": true
  }'
```

#### Text Request with JSON Output
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "List 3 programming languages and their use cases in JSON format",
    "is_image": false,
    "force_json": true
  }'
```

#### Request with Chat Context
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What about Rust?",
    "is_image": false,
    "chat_id": "existing-chat-123",
    "account_id": "user-account-456"
  }'
```

#### Request with Reference Image
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Modify this image to be in black and white",
    "is_image": true,
    "return_image_data": true,
    "reference_image_name": "my-reference-image.jpg"
  }'
```

#### Conditional Downloads & Custom Paths
By default, files are not saved unless explicitly requested via `"download": true`.

**Save Image with Custom Suffix and Directory:**
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Cyberpunk city at night",
    "is_image": true,
    "download": true,
    "filename_suffix": "_cyberpunk",
    "save_dir": "downloads/wallpaper"
  }'
```

**Save Text Response with Custom Suffix:**
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a short story about a brave robot",
    "download": true,
    "filename_suffix": "_robot_story"
  }'
```
> [!NOTE]
> All relative paths in `save_dir` are automatically resolved against the project root.

## 4. Stream Request Updates

### GET /api/v1/stream/{task_id}
Stream real-time updates for a request using Server-Sent Events.

```bash
curl -X GET http://localhost:12000/api/v1/stream/abc123-def456-ghi789 \
  -H "Accept: text/event-stream"
```

**Streaming Response Example:**
```
data: {"status": "pending", "task_id": "abc123-def456-ghi789", "message": "Request queued, waiting for worker"}

data: {"status": "processing", "task_id": "abc123-def456-ghi789", "message": "Processing request", "credential_key": "account1"}

data: {"status": "completed", "task_id": "abc123-def456-ghi789", "message": "Request completed successfully", "processing_time": 15.23, "result": {"text": "Hello! I'm doing well, thank you for asking!"}, "credential_key": "account1"}
```

## 5. Get Task Status

### GET /api/v1/status/{task_id}
Get the current status of a request.

```bash
curl -X GET http://localhost:12000/api/v1/status/abc123-def456-ghi789
```

**Response:**
```json
{
  "task_id": "abc123-def456-ghi789",
  "status": "completed",
  "created_at": "2026-02-15T13:00:00.000000",
  "updated_at": "2026-02-15T13:00:15.230000",
  "credential_key": "account1",
  "processing_time": 15.23,
  "error": null
}
```

## 6. Get Task Result

### GET /api/v1/result/{task_id}
Get the full result of a completed request.

```bash
curl -X GET http://localhost:12000/api/v1/result/abc123-def456-ghi789
```

**Text Response:**
```json
{
  "task_id": "abc123-def456-ghi789",
  "status": "completed",
  "prompt": "Hello! How are you today?",
  "is_image": false,
  "created_at": "2026-02-15T13:00:00.000000",
  "updated_at": "2026-02-15T13:00:15.230000",
  "credential_key": "account1",
  "processing_time": 15.23,
  "result": {
    "text": "Hello! I'm doing well, thank you for asking! How can I help you today?"
  },
  "error": null
}
```

**Image Response (with return_image_data):**
```json
{
  "task_id": "def456-ghi789-jkl012",
  "status": "completed",
  "prompt": "Generate a beautiful sunset over mountains",
  "is_image": true,
  "created_at": "2026-02-15T13:00:00.000000",
  "updated_at": "2026-02-15T13:00:45.120000",
  "credential_key": "account1",
  "processing_time": 45.12,
  "result": {
    "image_url": "https://drive.google.com/file/d/1abc.../view",
    "image_data": "iVBORw0KGgoAAAANSUhEUgAA...",
    "filename": "sunset_mountains_20260215_130045.png"
  },
  "error": null
}
```

**JSON Response:**
```json
{
  "task_id": "ghi789-jkl012-mno345",
  "status": "completed",
  "prompt": "List 3 programming languages and their use cases in JSON format",
  "is_image": false,
  "created_at": "2026-02-15T13:00:00.000000",
  "updated_at": "2026-02-15T13:00:12.450000",
  "credential_key": "account1",
  "processing_time": 12.45,
  "result": {
    "json": {
      "languages": [
        {
          "name": "Python",
          "use_cases": ["Web development", "Data science", "Automation"]
        },
        {
          "name": "JavaScript",
          "use_cases": ["Web frontend", "Node.js backend", "Mobile apps"]
        },
        {
          "name": "Java",
          "use_cases": ["Enterprise applications", "Android apps", "Big data"]
        }
      ]
    }
  },
  "error": null
}
```

## 7. List Requests

### GET /api/v1/requests
List all requests with pagination and optional filtering.

#### List all requests (default pagination)
```bash
curl -X GET http://localhost:12000/api/v1/requests
```

#### List with custom pagination
```bash
curl -X GET "http://localhost:12000/api/v1/requests?limit=10&offset=0"
```

#### Filter by status
```bash
curl -X GET "http://localhost:12000/api/v1/requests?status=completed&limit=20"
```

**Response:**
```json
{
  "requests": [
    {
      "task_id": "abc123-def456-ghi789",
      "prompt": "Hello! How are you today?",
      "status": "completed",
      "is_image": false,
      "created_at": "2026-02-15T13:00:00.000000",
      "processing_time": 15.23
    },
    {
      "task_id": "def456-ghi789-jkl012",
      "prompt": "Generate a beautiful sunset...",
      "status": "completed",
      "is_image": true,
      "created_at": "2026-02-15T13:00:30.000000",
      "processing_time": 45.12
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0
}
```

## 8. Get System Statistics

### GET /api/v1/stats
Get system statistics including database and worker information.

```bash
curl -X GET http://localhost:12000/api/v1/stats
```

**Response:**
```json
{
  "database": {
    "total_requests": 25,
    "by_status": {
      "completed": 20,
      "processing": 3,
      "failed": 2
    },
    "avg_processing_time": 18.45
  },
  "worker": {
    "credentials": {
      "total_credentials": 1,
      "mode": "default",
      "usage_count": {
        "account1": 25
      },
      "active_tasks": {
        "account1": 1
      },
      "credential_keys": [
        "account1"
      ]
    },
    "browser": {
      "initialized": true,
      "total_credentials": 1,
      "credential_keys": [
        "account1"
      ],
      "semaphore_states": {
        "account1": 0
      },
      "shutdown_requested": false
    },
    "queue": {
      "total_enqueued": 25,
      "total_processed": 22,
      "total_failed": 2,
      "active_workers": 1,
      "queue_size": 1,
      "pending_tasks": [
        "current-task-123"
      ],
      "worker_count": 1,
      "running": true
    }
  }
}
```

## Error Examples

### 404 - Task Not Found
```bash
curl -X GET http://localhost:12000/api/v1/status/nonexistent-task-id
```

**Response:**
```json
{
  "detail": "Task not found"
}
```

### 500 - Server Error
```bash
# This would occur if the worker is not running or there's an internal error
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{"prompt": "", "is_image": false}'
```

**Response:**
```json
{
  "detail": "Internal server error message"
}
```

## Complete Workflow Example

Here's a complete example showing the typical workflow:

```bash
#!/bin/bash

# 1. Check health
echo "Checking health..."
curl -s http://localhost:12000/api/v1/health | jq

# 2. Submit a text request
echo -e "\nSubmitting text request..."
RESPONSE=$(curl -s -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain quantum computing in simple terms",
    "is_image": false,
    "force_text": true
  }')

TASK_ID=$(echo $RESPONSE | jq -r '.task_id')
echo "Task ID: $TASK_ID"

# 3. Stream updates (run in background or separate terminal)
echo -e "\nStreaming updates..."
curl -s -X GET http://localhost:12000/api/v1/stream/$TASK_ID \
  -H "Accept: text/event-stream" &
STREAM_PID=$!

# 4. Check status periodically
echo -e "\nChecking status..."
sleep 5
curl -s http://localhost:12000/api/v1/status/$TASK_ID | jq

# 5. Get final result
echo -e "\nGetting final result..."
sleep 10
curl -s http://localhost:12000/api/v1/result/$TASK_ID | jq

# Clean up stream process
kill $STREAM_PID 2>/dev/null
```

## Notes

- All requests use JSON format for request bodies and responses
- The API runs on port 12000 by default
- Task IDs are UUIDs and are unique for each request
- Image generation requests can take longer to complete (30-60 seconds typical)
- The `return_image_data` flag controls whether base64-encoded image data is included in the response
- Streaming endpoints use Server-Sent Events (SSE) format
- Error responses follow standard HTTP status codes with JSON error details