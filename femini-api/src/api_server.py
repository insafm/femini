"""
FastAPI server for Femini Playwright API
Imports and uses femini-playwright package as a dependency
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

# Import from femini-playwright package
from femini_playwright import FeminiApp, Request, get_settings

# Import local API modules
from .database import APIDatabase
from .models import (
    SubmitRequest, SubmitResponse, StatusResponse,
    ResultResponse, RequestListResponse, RequestListItem,
    StatsResponse, HealthResponse
)
from .logging_config import setup_logging, get_logger

logger = get_logger(__name__)

# Global instances
settings = get_settings()
api_db = APIDatabase(db_path=settings.database_path)
femini_app: FeminiApp = None

# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    global femini_app
    
    # Startup
    logger.info("api_server_starting")
    
    # Initialize API database
    await api_db.initialize()
    
    # Initialize femini-playwright worker
    femini_app = FeminiApp()
    await femini_app.initialize()
    
    # Start background task to sync status from worker to API DB
    sync_task = asyncio.create_task(sync_worker_results())
    
    api_port = os.getenv("API_PORT", "8000")
    logger.info("api_server_started", port=api_port)
    
    yield
    
    # Shutdown
    logger.info("api_server_stopping")
    sync_task.cancel()
    
    if femini_app:
        await femini_app.shutdown()
    
    await api_db.close()
    logger.info("api_server_stopped")

# Background task to sync results from worker to API database
async def sync_worker_results():
    """
    Background task that polls femini worker for completed tasks
    and updates API database accordingly
    """
    logger.info("SYNC_TASK_STARTED")
    pending_tasks = {}  # task_id -> creation_time
    iteration = 0
    
    try:
        while True:
            iteration += 1
            
            # Get all pending or processing requests from API DB
            pending = await api_db.list_requests(limit=1000, status='pending')
            processing_db = await api_db.list_requests(limit=1000, status='processing')
            all_to_check = pending + processing_db
            
            if iteration % 10 == 0:  # Log every 10 iterations
                logger.info("SYNC_ITERATION", 
                           iteration=iteration,
                           pending_count=len(pending),
                           processing_count=len(processing_db))
            
            now = datetime.utcnow()
            for req in all_to_check:
                task_id = req['task_id']
                
                # Check if this task has a result from worker
                try:
                    # Try to get result with 0 timeout (non-blocking check)
                    result = femini_app.get_completed_result(task_id)
                    logger.debug("SYNC_CHECKED_TASK", task_id=task_id, has_result=result is not None)
                    
                    if result:
                        logger.info("WORKER_RESULT_FOUND",
                                   task_id=task_id,
                                   success=result.success,
                                   has_result=result.result is not None)
                        
                        # Update API database with result
                        if result.success:
                            await api_db.update_request_status(
                                task_id=task_id,
                                status='completed',
                                credential_key=result.credential_key,
                                processing_time=result.processing_time,
                                result=result.result
                            )
                            logger.info("DB_UPDATED_COMPLETED", task_id=task_id)
                        else:
                            await api_db.update_request_status(
                                task_id=task_id,
                                status='failed',
                                error=result.error or "Unknown worker error",
                                processing_time=result.processing_time
                            )
                            logger.error("DB_UPDATED_FAILED", task_id=task_id, error=result.error)
                        
                        # Remove from local tracking if present
                        if task_id in pending_tasks:
                            del pending_tasks[task_id]

                    else:
                        # No result yet, check if it's currently in worker
                        in_task_results = task_id in femini_app.queue_manager.task_results
                        
                        if in_task_results:
                            # Task is in worker (either waiting or processing)
                            if req['status'] != 'processing':
                                await api_db.update_request_status(
                                    task_id=task_id,
                                    status='processing'
                                )
                                logger.info("TASK_MARKED_PROCESSING", task_id=task_id)
                        else:
                            # Task not in worker results anymore but still pending/processing in DB
                            # Check for timeout (10 mins)
                            created_at = datetime.fromisoformat(req['created_at'])
                            if (now - created_at).total_seconds() > 600:
                                logger.warning("TASK_TIMEOUT_DETECTED", task_id=task_id, age_sec=(now-created_at).total_seconds())
                                await api_db.update_request_status(
                                    task_id=task_id,
                                    status='failed',
                                    error="Task timed out or worker lost track of it"
                                )
                            
                            # Track this task for local logging if not already tracked
                            if task_id not in pending_tasks:
                                pending_tasks[task_id] = created_at
                
                except Exception as e:
                    logger.error("SYNC_ERROR", task_id=task_id, error=str(e), error_type=type(e).__name__)
            
            # Sleep before next check
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logger.info("SYNC_TASK_CANCELLED")
        raise
    except Exception as e:
        logger.error("SYNC_TASK_ERROR", error=str(e), error_type=type(e).__name__)

# Create FastAPI app
app = FastAPI(
    title="Femini Playwright API",
    description="REST API for Gemini AI automation with Playwright",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["root"])
async def root():
    """Root endpoint"""
    return {
        "name": "Femini Playwright API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health"
    }

@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint"""
    try:
        # Check API database
        await api_db.get_stats()
        db_status = "connected"
    except Exception as e:
        logger.error("db_health_check_failed", error=str(e))
        db_status = "error"
    
    # Check worker status
    worker_status = "running" if femini_app and femini_app.running else "stopped"
    
    return HealthResponse(
        status="healthy" if db_status == "connected" and worker_status == "running" else "unhealthy",
        timestamp=datetime.utcnow().isoformat(),
        database=db_status,
        worker=worker_status
    )

@app.post("/api/v1/submit", response_model=SubmitResponse, tags=["requests"])
async def submit_request(request: SubmitRequest):
    """
    Submit a new request to the Gemini worker
    
    Returns immediately with task_id and stream URL for real-time updates
    """
    logger.info("SUBMIT_REQUEST_ENTRY", 
                prompt_length=len(request.prompt),
                is_image=request.is_image,
                return_image_data=request.return_image_data,
                force_json=request.force_json,
                force_text=request.force_text,
                chat_id=request.chat_id)
    
    try:
        # Generate a task_id first
        task_id = str(uuid.uuid4())

        # Save to database
        db_record = await api_db.create_request(
            task_id=task_id,
            prompt=request.prompt,
            is_image=request.is_image,
            force_json=request.force_json,
            force_text=request.force_text,
            return_image_data=request.return_image_data,
            chat_id=request.chat_id,
            account_id=request.account_id,
            reference_image_name=request.reference_image_name,
            filename_suffix=request.filename_suffix,
            save_dir=request.save_dir,
            download=request.download
        )
        
        logger.info("DB_RECORD_CREATED", 
                    task_id=task_id,
                    db_created_at=db_record["created_at"])

        # Add to worker queue
        worker_request = Request(
            task_id=task_id,
            prompt=request.prompt,
            is_image=request.is_image,
            force_json=request.force_json,
            force_text=request.force_text,
            return_image_data=request.return_image_data,
            chat_id=request.chat_id,
            account_id=request.account_id,
            credential_mode=request.credential_mode,
            reference_image_name=request.reference_image_name,
            filename_suffix=request.filename_suffix,
            save_dir=request.save_dir,
            download=request.download
        )
        
        logger.info("SUBMITTING_TO_WORKER", 
                    return_image_data=request.return_image_data)
        
        # Submit to femini worker
        await femini_app.submit_request(worker_request)
        
        logger.info("WORKER_ACCEPTED", task_id=task_id)
        
        response = SubmitResponse(
            task_id=task_id,
            status=db_record["status"],
            created_at=db_record["created_at"],
            stream_url=f"/api/v1/stream/{task_id}"
        )
        
        logger.info("SUBMIT_RESPONSE", 
                    task_id=task_id,
                    status=response.status,
                    stream_url=response.stream_url)
        
        return response
        
    except Exception as e:
        logger.error("SUBMIT_FAILED", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/stream/{task_id}", tags=["requests"])
async def stream_request(task_id: str):
    """
    Stream real-time updates for a request using Server-Sent Events (SSE)
    
    Connection stays open and streams status updates until completion
    """
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for task updates"""
        
        # Check if task exists
        request_data = await api_db.get_request(task_id)
        if not request_data:
            yield json.dumps({
                "status": "error",
                "task_id": task_id,
                "error": "Task not found"
            })
            return
        
        last_status = None
        last_updated = None
        max_polls = 600  # 10 minutes max
        poll_count = 0
        
        try:
            while poll_count < max_polls:
                if poll_count % 30 == 0:
                    logger.debug("stream_poll", task_id=task_id, poll=poll_count)
                
                # Get current request status from API DB
                request_data = await api_db.get_request(task_id)
                
                if not request_data:
                    yield json.dumps({
                        "status": "error",
                        "task_id": task_id,
                        "error": "Task disappeared"
                    })
                    break
                
                current_status = request_data["status"]
                current_updated = request_data["updated_at"]
                
                # Send update only if status changed
                if current_status != last_status or current_updated != last_updated:
                    message_data = {
                        "status": current_status,
                        "task_id": task_id
                    }
                    
                    if current_status == "pending":
                        message_data["message"] = "Request queued, waiting for worker"
                    
                    elif current_status == "processing":
                        message_data["message"] = "Processing request"
                        if request_data.get("credential_key"):
                            message_data["credential_key"] = request_data["credential_key"]
                    
                    elif current_status == "completed":
                        message_data["message"] = "Request completed successfully"
                        if request_data.get("processing_time"):
                            message_data["processing_time"] = request_data["processing_time"]
                        if request_data.get("result_json"):
                            message_data["result"] = json.loads(request_data["result_json"])
                        message_data["credential_key"] = request_data.get("credential_key")
                        
                        yield json.dumps(message_data)
                        break  # End stream on completion
                    
                    elif current_status == "failed":
                        message_data["message"] = "Request failed"
                        message_data["error"] = request_data.get("error", "Unknown error")
                        
                        yield json.dumps(message_data)
                        break  # End stream on failure
                    
                    logger.info("stream_yield_update", task_id=task_id, status=current_status)
                    yield json.dumps(message_data)
                    
                    last_status = current_status
                    last_updated = current_updated
                
                # Poll every second
                await asyncio.sleep(1)
                poll_count += 1
            
            # Timeout
            if poll_count >= max_polls:
                yield json.dumps({
                    "status": "timeout",
                    "task_id": task_id,
                    "error": "Stream timeout after 10 minutes"
                })
                
        except Exception as e:
            logger.error("stream_error", task_id=task_id, error=str(e))
            yield json.dumps({
                "status": "error",
                "task_id": task_id,
                "error": str(e)
            })
    
    return EventSourceResponse(event_generator())

@app.get("/api/v1/status/{task_id}", response_model=StatusResponse, tags=["requests"])
async def get_status(task_id: str):
    """Get current status of a request"""
    logger.info("STATUS_REQUEST", task_id=task_id)
    
    request_data = await api_db.get_request(task_id)
    
    if not request_data:
        logger.warning("STATUS_NOT_FOUND", task_id=task_id)
        raise HTTPException(status_code=404, detail="Task not found")
    
    logger.info("STATUS_RESPONSE", 
                task_id=task_id,
                status=request_data["status"],
                has_credential=bool(request_data.get("credential_key")))
    
    return StatusResponse(
        task_id=task_id,
        status=request_data["status"],
        created_at=request_data["created_at"],
        updated_at=request_data["updated_at"],
        credential_key=request_data.get("credential_key"),
        processing_time=request_data.get("processing_time"),
        error=request_data.get("error")
    )

@app.get("/api/v1/result/{task_id}", response_model=ResultResponse, tags=["requests"])
async def get_result(task_id: str):
    """Get full result of a completed request"""
    logger.info("RESULT_REQUEST", task_id=task_id)
    
    request_data = await api_db.get_request(task_id)
    
    if not request_data:
        logger.warning("RESULT_NOT_FOUND", task_id=task_id)
        raise HTTPException(status_code=404, detail="Task not found")
    
    result = None
    if request_data.get("result_json"):
        result = json.loads(request_data["result_json"])
        logger.info("RESULT_PARSED", 
                    task_id=task_id,
                    has_image_data="image_data" in result if result else False,
                    result_keys=list(result.keys()) if result else [])
    
    response = ResultResponse(
        task_id=task_id,
        status=request_data["status"],
        prompt=request_data["prompt"],
        is_image=bool(request_data["is_image"]),
        created_at=request_data["created_at"],
        updated_at=request_data["updated_at"],
        credential_key=request_data.get("credential_key"),
        processing_time=request_data.get("processing_time"),
        result=result,
        error=request_data.get("error")
    )
    
    logger.info("RESULT_RESPONSE", 
                task_id=task_id,
                status=response.status,
                has_result=response.result is not None)
    
    return response

@app.get("/api/v1/requests", response_model=RequestListResponse, tags=["requests"])
async def list_requests(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str = Query(None, description="Filter by status")
):
    """List all requests with pagination"""
    
    requests = await api_db.list_requests(limit=limit, offset=offset, status=status)
    
    # Get total count
    stats = await api_db.get_stats()
    total = stats.get("total_requests", 0)
    
    items = [
        RequestListItem(
            task_id=req["task_id"],
            prompt=req["prompt"][:100] + "..." if len(req["prompt"]) > 100 else req["prompt"],
            status=req["status"],
            is_image=bool(req["is_image"]),
            created_at=req["created_at"],
            processing_time=req.get("processing_time")
        )
        for req in requests
    ]
    
    return RequestListResponse(
        requests=items,
        total=total,
        limit=limit,
        offset=offset
    )

@app.get("/api/v1/stats", response_model=StatsResponse, tags=["monitoring"])
async def get_stats():
    """Get system statistics"""
    
    db_stats = await api_db.get_stats()
    worker_stats = femini_app.get_stats() if femini_app else None
    
    return StatsResponse(
        database=db_stats,
        worker=worker_stats
    )

def main():
    """Run the API server"""
    import uvicorn
    
    setup_logging()
    
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", "8000"))
    
    uvicorn.run(
        "src.api_server:app",
        host=api_host,
        port=api_port,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()