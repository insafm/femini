# Femini: Free & Unlimited Gemini AI API

> [!IMPORTANT]
> **Educational & Personal Use Disclaimer**: This project is designed as an educational tool for exploring browser automation. Please note that automating web interfaces may technically bypass standard usage patterns and could conflict with a service provider's Terms of Service. We recommend using this software responsibly and for personal learning only, as the author assumes no responsibility for any account-related consequences or legal issues.

Femini provides a production-ready, high-performance REST API for Google Gemini AI Studio. It bypasses restrictive API quotas and costs by using intelligent browser automation, giving you a truly **free and unlimited** way to integrate state-of-the-art AI into your applications.

## 🌟 Why Femini?

- **Unlimited Access**: No more API credits or quota limits. If you can type it in Gemini Studio, Femini can automate it.
- **High-Speed Automation**: Built on modern Playwright (async/await) for lightning-fast prompts and image generation.
- **Multi-Account Scaling**: Support for multiple Google accounts with automatic load balancing.
- **Developer First**: Clean REST API with real-time SSE streaming and comprehensive curl examples.
- **Privacy Focused**: All data and cookies are stored locally in your project root.

## � Key Features

### 💎 Gemini Automation
- **Unrestricted Access**: Bypasses official API quotas and costs entirely.
- **Image Intelligence**: Supports image generation, reference images, and multi-modal prompts.
- **Watermark Removal**: Automatically cleans watermarks from generated images for professional use.
- **Adaptive Parsing**: Intelligent Markdown-to-Text conversion and auto-repairing JSON parser.

### 🏗️ Architecture & Scale
- **Multi-Account Load Balancing**: Spread requests across unlimited Google accounts (Random, Round-Robin, Least-Busy).
- **Native Concurrency**: Async queue system processes multiple tasks in parallel (one per credential).
- **FastAPI Core**: Modern REST API with Server-Sent Events (SSE) for real-time progress.
- **Persistence**: SQLite database tracks every request, response, and processing time.

### 🛠️ Control & Flexibility
- **Conditional Downloads**: Opt-in file saving for both text and images with full granularity.
- **Smart Pathing**: Custom `save_dir` and `filename_suffix` support for all responses.
- **Project-Root Centric**: Zero-config path resolution ensures all data stays inside your project.
- **Docker Ready**: Production-hardened containers with non-root security and health checks.

## �📂 Project Structure

- `femini-api/`: FastAPI server for RESTful access.
- `femini-playwright/`: Core automation engine and queue manager.
- `run_local.sh`: Helper script for running the system locally without Docker.
- `docker-compose.yml`: Ready-to-use container orchestration.

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- [Optional] Docker & Docker Compose
- One or more Google accounts with Gemini access

### 2. Configuration
Copy the template and add your credentials:
```bash
cp .env.example .env
# Edit .env and add your GEMINI_CREDENTIALS
```

### 3. Run with Script (Local)
```bash
chmod +x run_local.sh
./run_local.sh
```

### 4. Run with Docker
```bash
docker-compose up --build
```

## 🎯 Basic Usage

Submit a request via the API:
```bash
curl -X POST http://localhost:12000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is quantum computing?",
    "download": true,
    "filename_suffix": "_quantum"
  }'
```

For more comprehensive examples, see [API_CURL_EXAMPLES.md](femini-api/API_CURL_EXAMPLES.md).

## 📄 Documentation

- [Femini API Details](femini-api/README.md)
- [Femini Playwright Library](femini-playwright/README.md)
- [API Examples](femini-api/API_CURL_EXAMPLES.md)

## � License

This project is for **educational and personal use only**. Commercial use is strictly prohibited. See the [LICENSE](LICENSE) file for the full terms and conditions.
