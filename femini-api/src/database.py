"""
Database module for Femini API
Stores API request/response logs in SQLite
"""

import aiosqlite
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from .logging_config import get_logger

logger = get_logger(__name__)

class APIDatabase:
    """Async SQLite database for API request/response logging"""

    def __init__(self, db_path: str = "/app/data/femini_api.db"):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None
        
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """Initialize database connection and create tables"""
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        
        await self._create_tables()
        logger.info("api_database_initialized", db_path=self.db_path)

    async def _create_tables(self):
        """Create database tables if they don't exist and add missing columns"""
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS api_requests (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                is_image BOOLEAN NOT NULL DEFAULT 0,
                force_json BOOLEAN NOT NULL DEFAULT 0,
                force_text BOOLEAN NOT NULL DEFAULT 0,
                return_image_data BOOLEAN NOT NULL DEFAULT 0,
                chat_id TEXT,
                account_id TEXT,
                reference_image_name TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                credential_key TEXT,
                processing_time REAL,
                result_json TEXT,
                error TEXT,
                filename_suffix TEXT,
                save_dir TEXT,
                download BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        
        # Self-healing migration for missing columns
        existing_columns = []
        async with self.db.execute("PRAGMA table_info(api_requests)") as cursor:
            async for row in cursor:
                existing_columns.append(row[1])
        
        # Add filename_suffix if missing
        if 'filename_suffix' not in existing_columns:
            logger.info("adding_column_filename_suffix")
            await self.db.execute("ALTER TABLE api_requests ADD COLUMN filename_suffix TEXT")
            
        # Add save_dir if missing
        if 'save_dir' not in existing_columns:
            logger.info("adding_column_save_dir")
            await self.db.execute("ALTER TABLE api_requests ADD COLUMN save_dir TEXT")
            
        # Add download if missing
        if 'download' not in existing_columns:
            logger.info("adding_column_download")
            await self.db.execute("ALTER TABLE api_requests ADD COLUMN download BOOLEAN NOT NULL DEFAULT 0")
            
        # Create indexes for better query performance
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_requests_status 
            ON api_requests(status)
        """)
        
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_requests_created 
            ON api_requests(created_at DESC)
        """)
        
        await self.db.commit()

    async def create_request(
        self,
        task_id: str,
        prompt: str,
        is_image: bool = False,
        force_json: bool = False,
        force_text: bool = False,
        return_image_data: bool = False,
        chat_id: Optional[str] = None,
        account_id: Optional[str] = None,
        reference_image_name: Optional[str] = None,
        filename_suffix: str = "",
        save_dir: Optional[str] = None,
        download: bool = False
    ) -> Dict[str, Any]:
        """Create a new request record"""
        now = datetime.utcnow().isoformat()
        
        await self.db.execute("""
            INSERT INTO api_requests (
                task_id, prompt, is_image, force_json, force_text, 
                return_image_data, chat_id, account_id, 
                reference_image_name, created_at, updated_at, status,
                filename_suffix, save_dir, download
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, prompt, is_image, force_json, force_text,
            return_image_data, chat_id, account_id,
            reference_image_name, now, now, 'pending',
            filename_suffix, save_dir, download
        ))
        
        await self.db.commit()
        
        logger.info("api_request_created", task_id=task_id, is_image=is_image)
        
        return {
            "task_id": task_id,
            "status": "pending",
            "created_at": now
        }

    async def update_request_status(
        self,
        task_id: str,
        status: str,
        credential_key: Optional[str] = None,
        processing_time: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """Update request status and result"""
        now = datetime.utcnow().isoformat()
        result_json = json.dumps(result) if result else None
        
        await self.db.execute("""
            UPDATE api_requests
            SET status = ?,
                updated_at = ?,
                credential_key = ?,
                processing_time = ?,
                result_json = ?,
                error = ?
            WHERE task_id = ?
        """, (
            status, now, credential_key, processing_time,
            result_json, error, task_id
        ))
        
        await self.db.commit()
        
        logger.info("api_request_updated", 
                   task_id=task_id, 
                   status=status,
                   processing_time=processing_time)

    async def get_request(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a request by task_id"""
        async with self.db.execute(
            "SELECT * FROM api_requests WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            
            if row:
                return dict(row)
            return None

    async def list_requests(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List requests with pagination and optional status filter"""
        query = "SELECT * FROM api_requests"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        stats = {}
        
        # Total requests
        async with self.db.execute(
            "SELECT COUNT(*) as count FROM api_requests"
        ) as cursor:
            row = await cursor.fetchone()
            stats["total_requests"] = row["count"]
        
        # By status
        async with self.db.execute("""
            SELECT status, COUNT(*) as count 
            FROM api_requests 
            GROUP BY status
        """) as cursor:
            rows = await cursor.fetchall()
            stats["by_status"] = {row["status"]: row["count"] for row in rows}
        
        # Average processing time
        async with self.db.execute("""
            SELECT AVG(processing_time) as avg_time
            FROM api_requests
            WHERE processing_time IS NOT NULL
        """) as cursor:
            row = await cursor.fetchone()
            stats["avg_processing_time"] = row["avg_time"]
        
        return stats

    async def close(self):
        """Close database connection"""
        if self.db:
            await self.db.close()
            logger.info("api_database_closed")