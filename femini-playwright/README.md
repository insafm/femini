# Femini Playwright

Production-ready async automation for the Gemini web app (gemini.google.com) using Playwright, featuring multiple Google credential support, concurrent processing, and Docker optimization.

> Note: Femini automates the Gemini web UI via browser automation; it does not use an official Google AI Studio API/SDK.

## 🚀 Features

- **Complete Selenium → Playwright Migration**: Async/await architecture with modern Playwright API
- **Multiple Google Credentials**: Support for multiple accounts with flexible selection modes (random, round-robin, least-busy, default)
- **True Concurrency**: Queue-based processing with proper semaphore control (1 request per credential simultaneously)
- **Docker Optimized**: Slim Python image with security hardening and health checks
- **Structured Logging**: JSON logging with file and console output using structlog
- **Resource Management**: Graceful shutdown, memory monitoring, and connection pooling
- **High Performance**: Reduced CPU/memory usage compared to Selenium
- **Production Ready**: Error handling, retries, circuit breakers, and monitoring

## 📋 Requirements

- Python 3.11+
- Docker & Docker Compose (optional)
- Google accounts with Gemini access

## 🛠️ Installation

### Option 1: Docker (Recommended)

```bash
# Clone repository
git clone <repository-url>
cd femini-playwright

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env

# Build and run
docker-compose up --build
```

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials
```

## ⚙️ Configuration

Create a `.env` file based on `.env.example`:

```env
# Multiple Google credentials (JSON array)
GEMINI_CREDENTIALS='[
  {
    "email": "account1@gmail.com",
    "password": "password1",
    "key": "account1"
  },
  {
    "email": "account2@gmail.com",
    "password": "password2",
    "key": "account2"
  }
]'

# Credential selection: random, round_robin, default, least_busy
CREDENTIAL_MODE=random

# Concurrency (should match credential count)
MAX_CONCURRENT_PER_CREDENTIAL=1
MAX_TOTAL_CONCURRENT=2

# Other settings...
HEADLESS=true
LOG_LEVEL=INFO
```

## 🎯 Usage

### Basic Text Request

```python
import asyncio
from src import FeminiApp, Request, setup_logging

async def main():
    setup_logging()

    app = FeminiApp()
    await app.initialize()

    try:
        # Submit text request
        request = Request(
            prompt="Hello! How are you today?",
            is_image=False
        )

        task_id = await app.submit_request(request)
        result = await app.wait_for_result(task_id)

        if result.success:
            print(f"Response: {result.result['text']}")
        else:
            print(f"Error: {result.error}")

    finally:
        await app.shutdown()

asyncio.run(main())
```

### Image Generation

```python
# Image generation request
request = Request(
    prompt="Generate a beautiful sunset",
    is_image=True,
    reference_image_name=None  # Optional reference image
)

task_id = await app.submit_request(request)
result = await app.wait_for_result(task_id, timeout=300.0)  # 5 min timeout

if result.success:
    print(f"Image URL: {result.result['url']}")
    print(f"Saved to: {result.result['path']}")
```

### Image Generation with Base64 Data

```python
# Image generation with base64 data return
request = Request(
    prompt="Generate a minimalist tech logo",
    is_image=True,
    return_image_data=True  # Return base64-encoded image data
)

task_id = await app.submit_request(request)
result = await app.wait_for_result(task_id, timeout=300.0)

if result.success:
    print(f"Image URL: {result.result['url']}")
    print(f"Saved to: {result.result['path']}")
    
    # Access base64-encoded image data directly
    if 'data' in result.result:
        image_base64 = result.result['data']
        image_size = result.result['size_bytes']
        
        # Decode back to bytes if needed
        import base64
        image_bytes = base64.b64decode(image_base64)
        
        # Use image_bytes for immediate processing without file I/O
```

### Batch Processing

```python
# Submit multiple requests
prompts = ["Question 1", "Question 2", "Question 3"]
task_ids = []

for prompt in prompts:
    request = Request(prompt=prompt, is_image=False)
    task_id = await app.submit_request(request)
    task_ids.append(task_id)

# Wait for all results
for task_id in task_ids:
    result = await app.wait_for_result(task_id)
    if result.success:
        print(f"✅ {task_id}: {result.result['text'][:50]}...")
```

## 🏗️ Architecture

```
┌─────────────────┐
│  Incoming       │
│  Requests       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Global Queue   │  ◄── Unlimited FIFO queue
│  (asyncio.Queue)│
└────────┬────────┘
         │
    ┌────┴────┬────────┬────────┐
    ▼         ▼        ▼        ▼
┌────────┐ ┌────────┐ ┌────────┐
│Worker 1│ │Worker 2│ │Worker N│  ◄── N = credential count
└───┬────┘ └───┬────┘ └───┬────┘
    │          │          │
    ▼          ▼          ▼
┌─────────────────────────────┐
│  Credential Manager         │  ◄── Selects credential
│  (random/round-robin/etc)   │
└───────────┬─────────────────┘
            │
    ┌───────┼───────┬───────┐
    ▼       ▼       ▼       ▼
┌────────┐┌────────┐┌────────┐
│Cred 1  ││Cred 2  ││Cred 3  │  ◄── Semaphore per credential
│Context ││Context ││Context │
└───┬────┘└───┬────┘└───┬────┘
    │         │         │
    ▼         ▼         ▼
┌─────────────────────────────┐
│  Gemini Client              │  ◄── Processes requests
│  (Playwright automation)    │
└─────────────────────────────┘
```

## 🔧 API Reference

### FeminiApp

Main application class for managing the entire system.

```python
class FeminiApp:
    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def submit_request(self, request: Request) -> str: ...
    async def get_result(self, task_id: str) -> Optional[TaskResult]: ...
    async def wait_for_result(self, task_id: str, timeout: float = 300.0) -> Optional[TaskResult]: ...
    def get_stats(self) -> Dict: ...
```

### Request

Represents a request to be processed.

```python
@dataclass
class Request:
    task_id: str
    prompt: str
    is_image: bool = False
    force_json: bool = False
    force_text: bool = False
    reference_image_name: Optional[str] = None
    chat_id: Optional[str] = None
    account_id: Optional[str] = None
    return_image_data: bool = False
    filename_suffix: str = ""
    save_dir: Optional[str] = None
    download: bool = False
    metadata: Optional[Dict[str, Any]] = None
```

### TaskResult

Result of a processed request.

```python
@dataclass
class TaskResult:
    task_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    credential_key: Optional[str] = None
    processing_time: Optional[float] = None
```

## 📊 Monitoring & Stats

Get real-time statistics:

```python
stats = app.get_stats()
print(f"Queue size: {stats['queue']['queue_size']}")
print(f"Active workers: {stats['queue']['worker_count']}")
print(f"Credentials: {stats['credentials']['total_credentials']}")
print(f"Mode: {stats['credentials']['mode']}")
```

## 🐳 Docker Commands

```bash
# Build and start
docker-compose up --build

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop and remove
docker-compose down

# Rebuild after changes
docker-compose up --build --force-recreate
```

## 🔍 Logging

Structured JSON logging with different levels:

- **DEBUG**: Detailed operation logs
- **INFO**: General operation info
- **WARNING**: Non-critical issues
- **ERROR**: Errors that don't stop operation

Logs are written to both console and `logs/femini.log`.

## 🛡️ Security

- Non-root Docker user
- Minimal attack surface
- No hardcoded credentials
- Secure cookie storage
- Input validation

## 🚦 Performance

| Metric | Selenium (Before) | Playwright (After) |
|--------|------------------|-------------------|
| Memory per browser | ~300MB+ | ~100MB per context |
| Startup time | 10-15s | 3-5s |
| Concurrent requests | Sequential | N simultaneous (N = credentials) |
| CPU usage | High | Low |
| Resource cleanup | Manual | Automatic |

## 🐛 Troubleshooting

### Common Issues

1. **Browser launch fails**
   - Ensure Docker has sufficient memory (2GB+)
   - Check Playwright installation: `playwright install chromium`

2. **Login fails**
   - Verify credentials in `.env`
   - Check Google account has Gemini access
   - Clear cookies directory and retry

3. **High memory usage**
   - Reduce `MAX_TOTAL_CONCURRENT`
   - Monitor with `docker stats`

4. **Slow responses**
   - Check network connectivity
   - Verify Google services are accessible
   - Reduce concurrent requests

### Debug Mode

Enable debug logging:

```env
LOG_LEVEL=DEBUG
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## 📄 License

This project is for **educational and personal use only**. Commercial use is strictly prohibited. See the root [LICENSE](../LICENSE) for the full terms and conditions.

## 🙏 Acknowledgments

- Built with [Playwright](https://playwright.dev/)
- Inspired by the original Selenium implementation
- Thanks to the async Python community

---

**Note**: This is a production-ready system. Always test thoroughly before deploying to production environments.