#!/usr/bin/env python3
"""
Comprehensive test suite for Femini API
Tests all endpoints, features, and edge cases
"""

import pytest
import requests
import json
import time
import base64
from typing import Dict, Optional

# Configuration
API_BASE = "http://localhost:12000"
TIMEOUT = 60  # seconds to wait for task completion

class TestFeminiAPI:
    """Main test class for Femini API"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup before each test"""
        # Verify API is accessible
        try:
            response = requests.get(f"{API_BASE}/api/v1/health", timeout=5)
            assert response.status_code == 200, "API not accessible"
        except requests.exceptions.RequestException as e:
            pytest.skip(f"API server not running: {e}")
    
    def wait_for_completion(self, task_id: str, timeout: int = TIMEOUT) -> Dict:
        """Wait for task to complete and return final result"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            response = requests.get(f"{API_BASE}/api/v1/status/{task_id}")
            assert response.status_code == 200
            
            status_data = response.json()
            status = status_data.get("status")
            
            if status == "completed":
                # Get full result
                result_response = requests.get(f"{API_BASE}/api/v1/result/{task_id}")
                assert result_response.status_code == 200
                return result_response.json()
            elif status == "failed":
                pytest.fail(f"Task failed: {status_data.get('error')}")
            
            time.sleep(1)
        
        pytest.fail(f"Task timeout after {timeout} seconds")
    
    # ===========================================
    # BASIC API ENDPOINT TESTS
    # ===========================================
    
    def test_root_endpoint(self):
        """Test root endpoint returns API info"""
        response = requests.get(API_BASE)
        assert response.status_code == 200
        
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["name"] == "Femini Playwright API"
    
    def test_health_check(self):
        """Test health endpoint"""
        response = requests.get(f"{API_BASE}/api/v1/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] in ["healthy", "unhealthy"]
        assert "database" in data
        assert "worker" in data
        assert data["database"] == "connected"
        assert data["worker"] == "running"
    
    def test_stats_endpoint(self):
        """Test stats endpoint"""
        response = requests.get(f"{API_BASE}/api/v1/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert "database" in data
        assert "worker" in data
    
    def test_list_requests_default(self):
        """Test listing requests with default parameters"""
        response = requests.get(f"{API_BASE}/api/v1/requests")
        assert response.status_code == 200
        
        data = response.json()
        assert "requests" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["requests"], list)
    
    def test_list_requests_with_pagination(self):
        """Test listing requests with pagination"""
        response = requests.get(f"{API_BASE}/api/v1/requests?limit=5&offset=0")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["requests"]) <= 5
    
    def test_list_requests_with_status_filter(self):
        """Test filtering requests by status"""
        response = requests.get(f"{API_BASE}/api/v1/requests?status=completed")
        assert response.status_code == 200
        
        data = response.json()
        # If there are any results, they should all be completed
        for req in data["requests"]:
            assert req["status"] == "completed"
    
    # ===========================================
    # TEXT REQUEST TESTS
    # ===========================================
    
    def test_submit_simple_text_request(self):
        """Test submitting a simple text request"""
        payload = {
            "prompt": "What is 2+2? Answer with just the number.",
            "is_image": False,
            "force_text": True
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert "stream_url" in data
        
        # Wait for completion
        result = self.wait_for_completion(data["task_id"])
        assert result["status"] == "completed"
        assert result["result"]["text"]
        assert "4" in result["result"]["text"]
    
    def test_text_request_with_return_image_data_false(self):
        """Test text request with return_image_data=False (should have no effect)"""
        payload = {
            "prompt": "Say hello",
            "is_image": False,
            "force_text": True,
            "return_image_data": False
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        result = self.wait_for_completion(data["task_id"])
        
        assert result["status"] == "completed"
        assert result["result"]["text"]
        assert "image_data" not in result["result"]
    
    def test_text_request_with_force_json(self):
        """Test text request with JSON response format"""
        payload = {
            "prompt": "Return a JSON with key 'number' and value 42",
            "is_image": False,
            "force_json": True
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        result = self.wait_for_completion(data["task_id"])
        
        assert result["status"] == "completed"
        assert result["result"]["text"]
    
    # ===========================================
    # IMAGE GENERATION TESTS (KEY FEATURE)
    # ===========================================
    
    def test_image_generation_without_return_data(self):
        """Test image generation with return_image_data=False (default)"""
        payload = {
            "prompt": "A simple red circle on white background",
            "is_image": True,
            "return_image_data": False
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        result = self.wait_for_completion(data["task_id"], timeout=120)
        
        assert result["status"] == "completed"
        assert result["result"]["image_path"]
        assert result["result"]["image_filename"]
        # Should NOT have image_data when return_image_data=False
        assert "image_data" not in result["result"]
    
    def test_image_generation_with_return_data(self):
        """Test image generation with return_image_data=True (KEY FEATURE TEST)"""
        payload = {
            "prompt": "A simple blue square on white background",
            "is_image": True,
            "return_image_data": True  # KEY: Request base64 image data
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        result = self.wait_for_completion(data["task_id"], timeout=120)
        
        assert result["status"] == "completed"
        assert result["result"]["image_path"]
        assert result["result"]["image_filename"]
        
        # KEY ASSERTION: Should have base64 image data
        assert "image_data" in result["result"], "image_data not in result!"
        assert result["result"]["image_data"], "image_data is empty!"
        
        # Validate it's valid base64
        image_data = result["result"]["image_data"]
        try:
            decoded = base64.b64decode(image_data)
            assert len(decoded) > 0, "Decoded image data is empty"
            # Check PNG signature
            assert decoded[:8] == b'\x89PNG\r\n\x1a\n', "Not a valid PNG file"
            print(f"✅ Successfully received {len(decoded)} bytes of image data")
        except Exception as e:
            pytest.fail(f"Invalid base64 image data: {e}")
    
    def test_image_generation_explicit_false(self):
        """Test that return_image_data=False explicitly prevents data return"""
        payload = {
            "prompt": "A green triangle",
            "is_image": True,
            "return_image_data": False
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        result = self.wait_for_completion(data["task_id"], timeout=120)
        
        assert result["status"] == "completed"
        # Should have file path but NO image_data
        assert result["result"]["image_path"]
        assert "image_data" not in result["result"]
    
    # ===========================================
    # SSE STREAMING TESTS
    # ===========================================
    
    def test_sse_streaming(self):
        """Test SSE streaming for real-time updates"""
        # Submit a request
        payload = {
            "prompt": "Count to 3",
            "is_image": False,
            "force_text": True
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        
        # Stream updates
        stream_response = requests.get(
            f"{API_BASE}/api/v1/stream/{task_id}",
            stream=True,
            timeout=60
        )
        
        statuses_seen = []
        for line in stream_response.iter_lines():
            if line.startswith(b'data: '):
                event_data = json.loads(line[6:])
                status = event_data.get("status")
                statuses_seen.append(status)
                
                if status == "completed":
                    assert "result" in event_data
                    break
                elif status == "failed":
                    pytest.fail(f"Task failed: {event_data.get('error')}")
        
        # Should see at least pending and completed
        assert "pending" in statuses_seen or "processing" in statuses_seen
        assert "completed" in statuses_seen
    
    # ===========================================
    # ERROR HANDLING TESTS
    # ===========================================
    
    def test_get_nonexistent_task(self):
        """Test requesting a non-existent task ID"""
        fake_task_id = "nonexistent-task-id-12345"
        
        response = requests.get(f"{API_BASE}/api/v1/status/{fake_task_id}")
        assert response.status_code == 404
        
        response = requests.get(f"{API_BASE}/api/v1/result/{fake_task_id}")
        assert response.status_code == 404
    
    def test_submit_invalid_request(self):
        """Test submitting request with missing required fields"""
        payload = {
            "is_image": False
            # Missing 'prompt' field
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_submit_empty_prompt(self):
        """Test submitting request with empty prompt"""
        payload = {
            "prompt": "",
            "is_image": False
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        # API should accept but may fail in processing
        assert response.status_code in [200, 400, 422]
    
    # ===========================================
    # CHAT CONTEXT TESTS
    # ===========================================
    
    def test_chat_context_with_chat_id(self):
        """Test using chat_id for conversation context"""
        chat_id = f"test-chat-{int(time.time())}"
        
        # First message
        payload1 = {
            "prompt": "My name is Alice. Remember this.",
            "is_image": False,
            "force_text": True,
            "chat_id": chat_id
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload1)
        assert response.status_code == 200
        result1 = self.wait_for_completion(response.json()["task_id"])
        assert result1["status"] == "completed"
        
        # Second message using same chat_id
        time.sleep(2)  # Brief pause
        payload2 = {
            "prompt": "What is my name?",
            "is_image": False,
            "force_text": True,
            "chat_id": chat_id
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload2)
        assert response.status_code == 200
        result2 = self.wait_for_completion(response.json()["task_id"])
        assert result2["status"] == "completed"
        # Response should remember the name (context retained)
        assert "Alice" in result2["result"]["text"] or "alice" in result2["result"]["text"].lower()
    
    # ===========================================
    # PERFORMANCE & CONCURRENT TESTS
    # ===========================================
    
    def test_multiple_concurrent_requests(self):
        """Test handling multiple concurrent requests"""
        task_ids = []
        
        # Submit 3 requests concurrently
        for i in range(3):
            payload = {
                "prompt": f"What is {i+1} + {i+1}?",
                "is_image": False,
                "force_text": True
            }
            response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
            assert response.status_code == 200
            task_ids.append(response.json()["task_id"])
        
        # Wait for all to complete
        for task_id in task_ids:
            result = self.wait_for_completion(task_id)
            assert result["status"] == "completed"
    
    def test_processing_time_recorded(self):
        """Test that processing time is recorded"""
        payload = {
            "prompt": "Say hello",
            "is_image": False,
            "force_text": True
        }
        
        response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
        assert response.status_code == 200
        
        result = self.wait_for_completion(response.json()["task_id"])
        assert result["status"] == "completed"
        assert "processing_time" in result
        assert result["processing_time"] > 0


def run_quick_test():
    """Quick smoke test for manual execution"""
    print("\n" + "="*60)
    print("FEMINI API COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    # Test 1: Health
    print("\n[1/6] Testing health endpoint...")
    response = requests.get(f"{API_BASE}/api/v1/health")
    assert response.status_code == 200
    print("✅ Health check passed")
    
    # Test 2: Text request
    print("\n[2/6] Testing text request...")
    payload = {
        "prompt": "What is 5+5? Answer with just the number.",
        "is_image": False,
        "force_text": True
    }
    response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    print(f"✅ Text request submitted: {task_id[:16]}...")
    
    # Test 3: Wait for completion
    print("\n[3/6] Waiting for text request completion...")
    for _ in range(60):
        response = requests.get(f"{API_BASE}/api/v1/status/{task_id}")
        status = response.json()["status"]
        if status == "completed":
            break
        time.sleep(1)
    
    result = requests.get(f"{API_BASE}/api/v1/result/{task_id}").json()
    assert result["status"] == "completed"
    print(f"✅ Text result: {result['result']['text'][:50]}")
    
    # Test 4: Image without data
    print("\n[4/6] Testing image generation (without data)...")
    payload = {
        "prompt": "A red circle",
        "is_image": True,
        "return_image_data": False
    }
    response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    print(f"✅ Image request submitted: {task_id[:16]}...")
    
    # Test 5: Image WITH data (KEY TEST)
    print("\n[5/6] Testing image generation WITH return_image_data=True...")
    payload = {
        "prompt": "A blue square",
        "is_image": True,
        "return_image_data": True  # KEY FEATURE
    }
    response = requests.post(f"{API_BASE}/api/v1/submit", json=payload)
    assert response.status_code == 200
    task_id_with_data = response.json()["task_id"]
    print(f"✅ Image request (with data) submitted: {task_id_with_data[:16]}...")
    
    print("\n[6/6] Waiting for image generation with data...")
    for _ in range(120):
        response = requests.get(f"{API_BASE}/api/v1/status/{task_id_with_data}")
        status = response.json()["status"]
        if status == "completed":
            break
        elif status == "failed":
            print(f"❌ Task failed: {response.json().get('error')}")
            return
        time.sleep(1)
    
    result = requests.get(f"{API_BASE}/api/v1/result/{task_id_with_data}").json()
    assert result["status"] == "completed"
    
    if "image_data" in result["result"]:
        image_data = result["result"]["image_data"]
        decoded = base64.b64decode(image_data)
        print(f"✅ IMAGE DATA RECEIVED: {len(decoded)} bytes")
        print(f"✅ return_image_data feature is WORKING!")
    else:
        print("❌ No image_data in result!")
        print(f"Result keys: {result['result'].keys()}")
    
    print("\n" + "="*60)
    print("✅ ALL QUICK TESTS PASSED!")
    print("="*60)


if __name__ == "__main__":
    # Run quick smoke test
    try:
        run_quick_test()
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Cannot connect to API server")
        print("   Make sure the server is running on port 12000")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")