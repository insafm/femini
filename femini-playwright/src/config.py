import json
from typing import List
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings
from pathlib import Path

class Credential(BaseModel):
    """Represents a single Google credential"""
    email: str
    password: str
    key: str

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Credentials (JSON string)
    gemini_credentials: str

    # Credential selection mode
    credential_mode: str = "random"  # random, round_robin, default, least_busy

    # Default credential index
    default_credential_index: int = 0

    # Concurrency settings
    max_concurrent_per_credential: int = 1
    max_total_concurrent: int = 3

    # Browser settings
    headless: bool = True
    request_timeout: int = 180
    browser_context_timeout: int = 300
    max_requests_per_context: int = 100
    max_requests_per_page: int = 20

    # Logging
    log_level: str = "INFO"

    # Paths
    database_path: str = "/app/data/femini_api.db"
    user_data_base_dir: str = "/app/user_data"
    save_responses: bool = False  # Save responses to text files in download_dir
    cookies_base_dir: str = "/app/cookies"
    download_dir: str = "/app/downloads"
    log_dir: str = "/app/logs"

    # Gemini settings
    base_url: str = "https://gemini.google.com/app?hl=en-IN"
    max_timeout: int = 180
    timeout: int = 60
    max_retries: int = 5
    
    # Image data settings
    return_image_data: bool = False  # Return base64-encoded image data in response
    remove_watermark: bool = True    # Automatically remove watermark from generated images

    # Optional API server settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }

    @field_validator('gemini_credentials')
    @classmethod
    def parse_credentials(cls, v: str) -> List[Credential]:
        """Parse JSON string into list of Credential objects"""
        try:
            creds_data = json.loads(v)
            return [Credential(**cred) for cred in creds_data]
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Invalid GEMINI_CREDENTIALS format: {e}")

    @property
    def credentials(self) -> List[Credential]:
        """Get parsed credentials list"""
        return self.gemini_credentials

    def _get_project_root(self) -> Path:
        """Find the project root by looking for .env file upward from CWD"""
        current = Path.cwd().resolve()
        # Look up to 3 levels up for .env
        for _ in range(4):
            if (current / ".env").exists():
                return current
            if current.parent == current: # Reached filesystem root
                break
            current = current.parent
        return Path.cwd().resolve() # Fallback to CWD

    def resolve_path(self, path_str: str) -> Path:
        """Resolve a path string, making it relative to project root if it's not absolute"""
        path = Path(path_str)
        if path.is_absolute():
            return path
        
        # Relative path: join with project root
        resolved = self._get_project_root() / path
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved.resolve()

    @property
    def user_data_base_path(self) -> Path:
        """Get absolute path for user data directory"""
        return self.resolve_path(self.user_data_base_dir)

    @property
    def cookies_base_path(self) -> Path:
        """Get absolute path for cookies directory"""
        return self.resolve_path(self.cookies_base_dir)

    @property
    def download_path(self) -> Path:
        """Get absolute path for downloads directory"""
        return self.resolve_path(self.download_dir)

    @property
    def log_path(self) -> Path:
        """Get absolute path for logs directory"""
        return self.resolve_path(self.log_dir)

    def get_user_data_path(self, credential_key: str) -> Path:
        """Get user data path for specific credential"""
        return self.user_data_base_path / f"google_{credential_key}"

    def get_cookies_path(self, credential_key: str) -> Path:
        """Get cookies file path for specific credential"""
        return self.cookies_base_path / f"google_cookies_{credential_key}.pkl"

    def ensure_directories(self):
        """Ensure all required directories exist"""
        directories = [
            self.user_data_base_path,
            self.cookies_base_path,
            self.download_path,
            self.log_path
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

# Lazy settings initialization
from typing import Optional

_settings: Optional[Settings] = None

def get_settings() -> Settings:
    """Get or create global settings instance (lazy initialization)"""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_directories()
    return _settings
