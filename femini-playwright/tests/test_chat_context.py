#!/usr/bin/env python3
"""
Pytest test suite for chat context management
Tests chat_id persistence, uniqueness, and switching with assertions
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

class TestChatIDManagement:
    """Test suite for chat ID management"""

    @pytest.mark.asyncio
    async def test_same_chat_id_consistency(self, app):
        """
        Test: Multiple prompts to same chat return consistent chat_id
        
        Scenario:
        1. Send first prompt (creates new chat)
        2. Send 2nd prompt with same chat_id
        3. Send 3rd prompt with same chat_id
        4. Verify all return the SAME chat_id
        """
        print("\n" + "="*60)
        print("TEST: Same Chat ID Consistency")
        print("="*60)
        
        # First prompt - creates new chat
        request1 = Request(
            prompt="Hello",
            is_image=False,
            force_text=True
        )
        
        task_id1 = await app.submit_request(request1)
        result1 = await app.wait_for_result(task_id1, timeout=60.0)
        
        assert result1 is not None, "First request should return a result"
        assert result1.success is True, "First request should succeed"
        assert result1.result.get('chat_id') is not None, "Should have chat_id"
        
        chat_id = result1.result.get('chat_id')
        account_id = result1.result.get('account_id')
        
        print(f"✓ Chat created: {chat_id}")
        print(f"  Time: {result1.processing_time:.2f}s")
        
        # Second prompt - same chat
        request2 = Request(
            prompt="Hi",
            is_image=False,
            force_text=True,
            chat_id=chat_id,
            account_id=account_id
        )
        
        task_id2 = await app.submit_request(request2)
        result2 = await app.wait_for_result(task_id2, timeout=60.0)
        
        assert result2 is not None, "Second request should return a result"
        assert result2.success is True, "Second request should succeed"
        assert result2.result.get('chat_id') == chat_id, \
            f"Should return same chat_id. Expected {chat_id}, got {result2.result.get('chat_id')}"
        
        print(f"✓ Second prompt: Same chat_id verified")
        print(f"  Time: {result2.processing_time:.2f}s")
        
        # Third prompt - same chat
        request3 = Request(
            prompt="Hey",
            is_image=False,
            force_text=True,
            chat_id=chat_id,
            account_id=account_id
        )
        
        task_id3 = await app.submit_request(request3)
        result3 = await app.wait_for_result(task_id3, timeout=60.0)
        
        assert result3 is not None, "Third request should return a result"
        assert result3.success is True, "Third request should succeed"
        assert result3.result.get('chat_id') == chat_id, \
            f"Should still return same chat_id. Expected {chat_id}, got {result3.result.get('chat_id')}"
        
        print(f"✓ Third prompt: Same chat_id verified")
        print(f"  Time: {result3.processing_time:.2f}s")
        print("="*60 + "\n")

    @pytest.mark.asyncio
    async def test_multiple_chat_ids_unique(self, app):
        """
        Test: Multiple separate chats have unique chat_ids
        
        Scenario:
        1. Create 3 separate chats (no chat_id specified)
        2. Verify each returns a different chat_id
        """
        print("\n" + "="*60)
        print("TEST: Multiple Chat IDs Are Unique")
        print("="*60)
        
        chats = {}
        
        # Create Chat A
        print("\n→ Creating Chat A...")
        request_a = Request(
            prompt="Test A",
            is_image=False,
            force_text=True
        )
        task_a = await app.submit_request(request_a)
        result_a = await app.wait_for_result(task_a, timeout=60.0)
        
        assert result_a.success is True, "Chat A creation should succeed"
        assert result_a.result.get('chat_id') is not None, "Chat A should have chat_id"
        chats['A'] = result_a.result.get('chat_id')
        print(f"✓ Chat A: {chats['A']}")
        
        # Create Chat B
        print("\n→ Creating Chat B...")
        request_b = Request(
            prompt="Test B",
            is_image=False,
            force_text=True
        )
        task_b = await app.submit_request(request_b)
        result_b = await app.wait_for_result(task_b, timeout=60.0)
        
        assert result_b.success is True, "Chat B creation should succeed"
        assert result_b.result.get('chat_id') is not None, "Chat B should have chat_id"
        chats['B'] = result_b.result.get('chat_id')
        print(f"✓ Chat B: {chats['B']}")
        
        # Create Chat C
        print("\n→ Creating Chat C...")
        request_c = Request(
            prompt="Test C",
            is_image=False,
            force_text=True
        )
        task_c = await app.submit_request(request_c)
        result_c = await app.wait_for_result(task_c, timeout=60.0)
        
        assert result_c.success is True, "Chat C creation should succeed"
        assert result_c.result.get('chat_id') is not None, "Chat C should have chat_id"
        chats['C'] = result_c.result.get('chat_id')
        print(f"✓ Chat C: {chats['C']}")
        
        # Verify all chat IDs are unique
        chat_ids = list(chats.values())
        assert len(set(chat_ids)) == 3, \
            f"All chat IDs should be unique. Got: {chat_ids}"
        
        print(f"\n✓ All 3 chat IDs are unique")
        print("="*60 + "\n")

    @pytest.mark.asyncio
    async def test_chat_id_switching(self, app):
        """
        Test: Switching between chats returns correct chat_id
        
        Scenario:
        1. Create 3 chats (A, B, C)
        2. Switch randomly: A → C → B → A → C → B
        3. Verify correct chat_id is returned on each switch
        """
        print("\n" + "="*60)
        print("TEST: Chat ID Switching")
        print("="*60)
        
        # Step 1: Create 3 chats
        chats = {}
        
        print("\n→ Creating 3 chats...")
        for chat_name in ['A', 'B', 'C']:
            request = Request(
                prompt=f"Chat {chat_name}",
                is_image=False,
                force_text=True
            )
            task_id = await app.submit_request(request)
            result = await app.wait_for_result(task_id, timeout=60.0)
            
            assert result.success is True, f"Chat {chat_name} creation should succeed"
            assert result.result.get('chat_id') is not None, f"Chat {chat_name} should have chat_id"
            
            chats[chat_name] = {
                'chat_id': result.result.get('chat_id'),
                'account_id': result.result.get('account_id'),
                'visits': 0
            }
            print(f"  ✓ Chat {chat_name}: {chats[chat_name]['chat_id'][:16]}...")
        
        # Step 2: Random switching sequence
        switch_sequence = ['A', 'C', 'B', 'A', 'C', 'B']
        
        print(f"\n→ Testing switch sequence: {' → '.join(switch_sequence)}")
        
        for i, chat_name in enumerate(switch_sequence, 1):
            chat_info = chats[chat_name]
            chat_info['visits'] += 1
            
            print(f"\n  [{i}/{len(switch_sequence)}] Switching to Chat {chat_name}...")
            
            request = Request(
                prompt=f"Message {i}",
                is_image=False,
                force_text=True,
                chat_id=chat_info['chat_id'],
                account_id=chat_info['account_id']
            )
            
            task_id = await app.submit_request(request)
            result = await app.wait_for_result(task_id, timeout=60.0)
            
            # Assertions
            assert result is not None, f"Request {i} should return a result"
            assert result.success is True, f"Request {i} should succeed"
            assert result.result.get('chat_id') == chat_info['chat_id'], \
                f"Should be in Chat {chat_name}. Expected {chat_info['chat_id']}, got {result.result.get('chat_id')}"
            
            print(f"    ✓ Correct chat_id: {result.result.get('chat_id')[:16]}...")
            print(f"    ✓ Time: {result.processing_time:.2f}s")
        
        # Verify visit counts
        print(f"\n→ Visit statistics:")
        for chat_name, chat_info in chats.items():
            expected_visits = switch_sequence.count(chat_name)
            assert chat_info['visits'] == expected_visits, \
                f"Chat {chat_name} should have {expected_visits} visits, got {chat_info['visits']}"
            print(f"  Chat {chat_name}: {chat_info['visits']} visits ✓")
        
        print("="*60 + "\n")

class TestChatPerformance:
    """Test suite for chat performance metrics"""

    @pytest.mark.asyncio
    async def test_subsequent_requests_faster(self, app):
        """
        Test: Subsequent requests in same chat should be faster than first
        
        Due to client reuse and no navigation overhead
        """
        print("\n" + "="*60)
        print("TEST: Performance - Subsequent Requests Faster")
        print("="*60)
        
        # First request (includes setup)
        request1 = Request(
            prompt="Hello",
            is_image=False,
            force_text=True
        )
        task_id1 = await app.submit_request(request1)
        result1 = await app.wait_for_result(task_id1, timeout=60.0)
        
        assert result1.success is True
        time1 = result1.processing_time
        chat_id = result1.result.get('chat_id')
        account_id = result1.result.get('account_id')
        
        print(f"  First request: {time1:.2f}s")
        
        # Second request (reuses client, stays in chat)
        request2 = Request(
            prompt="Hi again",
            is_image=False,
            force_text=True,
            chat_id=chat_id,
            account_id=account_id
        )
        task_id2 = await app.submit_request(request2)
        result2 = await app.wait_for_result(task_id2, timeout=60.0)
        
        assert result2.success is True
        time2 = result2.processing_time
        
        print(f"  Second request: {time2:.2f}s")
        
        # Second should be significantly faster
        speedup = ((time1 - time2) / time1) * 100
        print(f"  Speedup: {speedup:.1f}%")
        
        assert time2 < time1, \
            f"Second request should be faster. First: {time1:.2f}s, Second: {time2:.2f}s"
        
        # Allow some variance, but expect at least 20% improvement
        assert speedup > 20, \
            f"Expected at least 20% speedup, got {speedup:.1f}%"
        
        print(f"  ✓ Performance improvement confirmed!")
        print("="*60 + "\n")

if __name__ == "__main__":
    # Run with: pytest tests/test_chat_context.py -v
    pytest.main([__file__, "-v", "-s"])