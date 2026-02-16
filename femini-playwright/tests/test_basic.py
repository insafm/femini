#!/usr/bin/env python3
"""
Basic test suite to verify core functionality after retry logic changes
Simple tests covering text, chat persistence, and image generation
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src import FeminiApp, Request, setup_logging

# Setup logging once
setup_logging()

@pytest.fixture
async def app():
    """Fixture to initialize and cleanup app for each test"""
    app_instance = FeminiApp()
    await app_instance.initialize()
    yield app_instance
    await app_instance.shutdown()


class TestBasicFunctionality:
    """Basic tests for core functionality"""

    @pytest.mark.asyncio
    async def test_basic_text_request(self, app):
        """
        Test: Basic text request works
        Verifies retry logic doesn't break normal flow
        """
        print("\n" + "="*60)
        print("TEST: Basic Text Request")
        print("="*60)
        
        request = Request(
            prompt="Say hello",
            is_image=False,
            force_text=True
        )
        
        task_id = await app.submit_request(request)
        result = await app.wait_for_result(task_id, timeout=90.0)
        
        # Assertions
        assert result is not None, "Should return a result"
        assert result.success is True, "Request should succeed"
        assert result.result.get('text') is not None, "Should have text response"
        assert result.result.get('chat_id') is not None, "Should have chat_id"
        
        print(f"✓ Text response: {result.result.get('text', '')[:50]}...")
        print(f"✓ Chat ID: {result.result.get('chat_id')}")
        print(f"✓ Time: {result.processing_time:.2f}s")
        print("="*60 + "\n")

    @pytest.mark.asyncio
    async def test_chat_id_persistence(self, app):
        """
        Test: Chat ID persists across multiple requests
        Verifies chat context is maintained
        """
        print("\n" + "="*60)
        print("TEST: Chat ID Persistence")
        print("="*60)
        
        # First request
        request1 = Request(
            prompt="Test 1",
            is_image=False,
            force_text=True
        )
        
        task_id1 = await app.submit_request(request1)
        result1 = await app.wait_for_result(task_id1, timeout=90.0)
        
        assert result1.success is True
        chat_id = result1.result.get('chat_id')
        account_id = result1.result.get('account_id')
        
        print(f"✓ First request - Chat ID: {chat_id}")
        
        # Second request to same chat
        request2 = Request(
            prompt="Test 2",
            is_image=False,
            force_text=True,
            chat_id=chat_id,
            account_id=account_id
        )
        
        task_id2 = await app.submit_request(request2)
        result2 = await app.wait_for_result(task_id2, timeout=90.0)
        
        assert result2.success is True
        assert result2.result.get('chat_id') == chat_id, \
            f"Chat ID should persist. Expected {chat_id}, got {result2.result.get('chat_id')}"
        
        print(f"✓ Second request - Same chat ID verified: {result2.result.get('chat_id')}")
        print("="*60 + "\n")

    @pytest.mark.asyncio
    async def test_new_vs_existing_chat(self, app):
        """
        Test: New chats get unique chat IDs
        Verifies chat isolation works
        """
        print("\n" + "="*60)
        print("TEST: New vs Existing Chat")
        print("="*60)
        
        # Create first chat
        request_a = Request(
            prompt="Chat A",
            is_image=False,
            force_text=True
        )
        
        task_a = await app.submit_request(request_a)
        result_a = await app.wait_for_result(task_a, timeout=90.0)
        
        assert result_a.success is True
        chat_id_a = result_a.result.get('chat_id')
        print(f"✓ Chat A created: {chat_id_a}")
        
        # Create second chat (no chat_id = new chat)
        request_b = Request(
            prompt="Chat B",
            is_image=False,
            force_text=True
        )
        
        task_b = await app.submit_request(request_b)
        result_b = await app.wait_for_result(task_b, timeout=90.0)
        
        assert result_b.success is True
        chat_id_b = result_b.result.get('chat_id')
        print(f"✓ Chat B created: {chat_id_b}")
        
        # Verify different chat IDs
        assert chat_id_a != chat_id_b, \
            f"New chats should have different IDs. Got A={chat_id_a}, B={chat_id_b}"
        
        print(f"✓ Chat IDs are different - isolation confirmed")
        print("="*60 + "\n")

    @pytest.mark.asyncio
    async def test_basic_image_generation(self, app):
        """
        Test: Basic image generation works
        Verifies image mode and download functionality
        """
        print("\n" + "="*60)
        print("TEST: Basic Image Generation")
        print("="*60)
        
        request = Request(
            prompt="Generate a simple landscape with mountains",
            is_image=True,
            force_text=False
        )
        
        task_id = await app.submit_request(request)
        result = await app.wait_for_result(task_id, timeout=300.0)  # 5 min for image
        
        # Assertions
        assert result is not None, "Should return a result"
        assert result.success is True, f"Image generation should succeed. Error: {result.result.get('error', 'None')}"
        assert result.result.get('url') is not None, "Should have image URL"
        assert result.result.get('chat_id') is not None, "Should have chat_id"
        
        print(f"✓ Image URL: {result.result.get('url', '')[:60]}...")
        print(f"✓ Downloaded path: {result.result.get('path', 'N/A')}")
        print(f"✓ Chat ID: {result.result.get('chat_id')}")
        print(f"✓ Time: {result.processing_time:.2f}s")
        
        # Optional: Check if file exists
        image_path = result.result.get('path')
        if image_path:
            from pathlib import Path
            assert Path(image_path).exists(), f"Downloaded image should exist at {image_path}"
            print(f"✓ Image file verified at: {image_path}")
        
        print("="*60 + "\n")


if __name__ == "__main__":
    # Run with: pytest tests/test_basic.py -v -s
    pytest.main([__file__, "-v", "-s"])