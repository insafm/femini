#!/usr/bin/env python3
"""
Simple test script for Femini API
"""

import requests
import json
import time

API_BASE = "http://localhost:12000"

def test_health():
    """Test health endpoint"""
    print("\n🏥 Testing health endpoint...")
    response = requests.get(f"{API_BASE}/api/v1/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def test_submit_text():
    """Test text request submission"""
    print("\n📝 Testing text request submission...")
    
    data = {
        "prompt": "What is 2+2? Just answer with the number.",
        "is_image": False,
        "force_text": True
    }
    
    response = requests.post(f"{API_BASE}/api/v1/submit", json=data)
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Response: {json.dumps(result, indent=2)}")
    
    return result.get("task_id")

def test_stream(task_id):
    """Test SSE streaming"""
    print(f"\n🌊 Testing SSE stream for task {task_id[:8]}...")
    
    response = requests.get(f"{API_BASE}/api/v1/stream/{task_id}", stream=True)
    
    for line in response.iter_lines():
        if line.startswith(b'data: '):
            event_data = json.loads(line[6:])
            print(f"  Event: {event_data.get('status')} - {event_data.get('message', '')}")
            
            if event_data.get('status') == 'completed':
                print(f"  ✅ Result: {event_data.get('result', {}).get('text', '')[:100]}")
                return True
            elif event_data.get('status') == 'failed':
                print(f"  ❌ Error: {event_data.get('error')}")
                return False
    
    return False

def test_get_result(task_id):
    """Test getting result"""
    print(f"\n📊 Testing get result for task {task_id[:8]}...")
    
    # Wait a bit for processing
    time.sleep(2)
    
    response = requests.get(f"{API_BASE}/api/v1/result/{task_id}")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Task Status: {result.get('status')}")
        if result.get('result'):
            print(f"Result: {result['result'].get('text', '')[:100]}")

def test_stats():
    """Test stats endpoint"""
    print("\n📈 Testing stats endpoint...")
    response = requests.get(f"{API_BASE}/api/v1/stats")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_list_requests():
    """Test list requests endpoint"""
    print("\n📋 Testing list requests endpoint...")
    response = requests.get(f"{API_BASE}/api/v1/requests?limit=5")
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Total requests: {result.get('total')}")
    print(f"Showing {len(result.get('requests', []))} requests")

def main():
    """Run all tests"""
    print("🧪 Femini API Test Suite")
    print("=" * 50)
    
    try:
        # Test 1: Health check
        if not test_health():
            print("❌ Health check failed!")
            return
        
        # Test 2: Submit request
        task_id = test_submit_text()
        if not task_id:
            print("❌ Request submission failed!")
            return
        
        # Test 3: Stream updates
        test_stream(task_id)
        
        # Test 4: Get result
        test_get_result(task_id)
        
        # Test 5: Stats
        test_stats()
        
        # Test 6: List requests
        test_list_requests()
        
        print("\n" + "=" * 50)
        print("✅ All tests completed!")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Cannot connect to API server")
        print("   Make sure the server is running: docker-compose up femini-api")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()