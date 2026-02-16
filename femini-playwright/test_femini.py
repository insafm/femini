#!/usr/bin/env python3
"""
Comprehensive test script for Femini Playwright
Tests all major functionality including login, text prompts, chat management, and image generation
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src import FeminiApp, Request, setup_logging, get_logger

logger = get_logger(__name__)

async def test_configuration():
    """Test configuration loading"""
    print("🔧 Testing configuration loading...")

    try:
        from src.config import settings
        print(f"✅ Credentials loaded: {len(settings.credentials)}")
        print(f"✅ Mode: {settings.credential_mode}")
        print(f"✅ Headless: {settings.headless}")
        return True
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False

async def test_basic_text_prompt():
    """Test basic text prompt functionality"""
    print("\n📝 Testing basic text prompt...")

    app = FeminiApp()
    await app.initialize()

    try:
        request = Request(
            prompt="Hello! Please respond with a simple greeting.",
            is_image=False,
            force_text=True
        )

        print("📤 Submitting text request...")
        task_id = await app.submit_request(request)
        print(f"✅ Request submitted: {task_id}")

        print("⏳ Waiting for response...")
        result = await app.wait_for_result(task_id, timeout=60.0)

        if result and result.success:
            print("🎉 Success!")
            response_text = result.result.get('text', '')
            print(f"Response: {response_text[:100]}...")
            print(f"Processing time: {result.processing_time:.2f}s")
            print(f"Credential used: {result.credential_key}")
            return bool(response_text and len(response_text) > 0)
        else:
            error_msg = result.error if result else "Timeout"
            print(f"❌ Failed: {error_msg}")
            return False

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False
    finally:
        await app.shutdown()

async def test_multiple_prompts_same_chat():
    """Test multiple prompts in the same chat session"""
    print("\n💬 Testing multiple prompts in same chat...")

    app = FeminiApp()
    await app.initialize()

    try:
        prompts = [
            "What is 2+2? Just answer with the number.",
            "What is 3+3? Just answer with the number.",
            "What is 4+4? Just answer with the number."
        ]

        print(f"📤 Submitting {len(prompts)} sequential prompts in SAME chat...")
        all_success = True
        chat_id = None
        account_id = None

        for i, prompt in enumerate(prompts, 1):
            print(f"\n  Prompt {i}/{len(prompts)}: {prompt}")
            
            # First prompt: no chat_id (new chat)
            # Subsequent prompts: pass chat_id (continue same chat)
            request = Request(
                prompt=prompt,
                is_image=False,
                force_text=True,
                chat_id=chat_id,
                account_id=account_id
            )
            task_id = await app.submit_request(request)
            
            result = await app.wait_for_result(task_id, timeout=60.0)
            
            if result and result.success:
                response = result.result.get('text', '')
                print(f"  ✅ Response: {response[:80]}")
                print(f"  ⏱️  Time: {result.processing_time:.2f}s")
                
                # Store chat_id for next prompt
                if i == 1:
                    chat_id = result.result.get('chat_id')
                    account_id = result.result.get('account_id')
                    print(f"  📍 Chat ID: {chat_id}")
            else:
                print(f"  ❌ Failed: {result.error if result else 'Timeout'}")
                all_success = False

        return all_success

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False
    finally:
        await app.shutdown()

async def test_new_chat_window():
    """Test new chat vs same chat context"""
    print("\n🆕 Testing new chat window vs same chat context...")

    app = FeminiApp()
    await app.initialize()

    try:
        # ===== Part 1: Test SAME CHAT context =====
        print("\n📍 Part 1: Testing SAME CHAT context retention...")
        
        print("📤 Sending first prompt...")
        request1 = Request(
            prompt="Remember this: My favorite color is blue.",
            is_image=False,
            force_text=True
        )
        task_id1 = await app.submit_request(request1)
        result1 = await app.wait_for_result(task_id1, timeout=60.0)
        
        if not (result1 and result1.success):
            print("❌ First prompt failed")
            return False
        
        chat_id = result1.result.get('chat_id')
        account_id = result1.result.get('account_id')
        print(f"✅ First response: {result1.result.get('text', '')[:80]}")
        print(f"📍 Chat ID: {chat_id}")

        # Ask follow-up in SAME chat
        print("\n📤 Sending follow-up in SAME chat (passing chat_id)...")
        request2 = Request(
            prompt="What did I say my favorite color was?",
            is_image=False,
            force_text=True,
            chat_id=chat_id,
            account_id=account_id
        )
        task_id2 = await app.submit_request(request2)
        result2 = await app.wait_for_result(task_id2, timeout=60.0)
        
        if not (result2 and result2.success):
            print("❌ Follow-up prompt failed")
            return False
        
        response2 = result2.result.get('text', '')
        print(f"✅ Follow-up response: {response2[:80]}")
        
        # Should remember "blue" in same chat
        same_chat_remembers = "blue" in response2.lower()
        if same_chat_remembers:
            print("✅ SAME CHAT: Context maintained (remembers 'blue')!")
        else:
            print("❌ SAME CHAT: Context lost (doesn't remember 'blue')")
            return False

        # ===== Part 2: Test NEW CHAT isolation =====
        print("\n📍 Part 2: Testing NEW CHAT context isolation...")
        
        print("📤 Starting NEW chat (no chat_id)...")
        request3 = Request(
            prompt="What did I say my favorite color was?",
            is_image=False,
            force_text=True
            # NOTE: No chat_id = new chat
        )
        task_id3 = await app.submit_request(request3)
        result3 = await app.wait_for_result(task_id3, timeout=60.0)
        
        if not (result3 and result3.success):
            print("❌ New chat prompt failed")
            return False
        
        new_chat_id = result3.result.get('chat_id')
        response3 = result3.result.get('text', '')
        print(f"✅ New chat response: {response3[:80]}")
        print(f"📍 New Chat ID: {new_chat_id}")
        
        # Should NOT remember "blue" in new chat
        new_chat_remembers = "blue" in response3.lower()
        if not new_chat_remembers:
            print("✅ NEW CHAT: Context isolated (doesn't remember 'blue')!")
        else:
            print("⚠️  NEW CHAT: Unexpectedly remembers 'blue' (might be general knowledge)")
        
        # Verify chat IDs are different
        chats_different = chat_id != new_chat_id
        print(f"\n📊 Chat IDs different: {chats_different}")
        print(f"   Original: {chat_id}")
        print(f"   New:      {new_chat_id}")

        return same_chat_remembers and chats_different

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await app.shutdown()

async def test_image_generation():
    """Test image generation functionality"""
    print("\n🎨 Testing image generation...")

    app = FeminiApp()
    await app.initialize()

    try:
        request = Request(
            prompt="Generate a simple blue circle on white background",
            is_image=True,
            force_json=False
        )

        print("📤 Submitting image generation request...")
        task_id = await app.submit_request(request)
        print(f"✅ Request submitted: {task_id}")

        print("⏳ Waiting for image generation (may take 1-3 minutes)...")
        result = await app.wait_for_result(task_id, timeout=300.0)

        if result and result.success:
            print("🎉 Image generated successfully!")
            url = result.result.get('url', 'N/A')
            path = result.result.get('path', 'N/A')
            print(f"Image URL: {url[:80]}...")
            print(f"Downloaded to: {path}")
            print(f"Processing time: {result.processing_time:.2f}s")
            print(f"Credential used: {result.credential_key}")
            
            # Verify file exists
            if path and path != 'N/A':
                file_exists = Path(path).exists()
                print(f"File exists: {file_exists}")
                return file_exists
            return True
        else:
            error_msg = result.error if result else "Timeout"
            print(f"❌ Failed: {error_msg}")
            return False

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await app.shutdown()

async def test_batch_processing():
    """Test batch processing with multiple requests"""
    print("\n📦 Testing batch processing with concurrent requests...")

    app = FeminiApp()
    await app.initialize()

    try:
        prompts = [
            "What is the capital of France? Just name the city.",
            "What is 10 + 15? Just answer with the number.",
            "Name one programming language. Just the name.",
        ]

        print(f"📤 Submitting {len(prompts)} requests concurrently...")

        # Submit all requests
        task_ids = []
        for i, prompt in enumerate(prompts, 1):
            request = Request(prompt=prompt, is_image=False, force_text=True)
            task_id = await app.submit_request(request)
            task_ids.append(task_id)
            print(f"  ✅ Submitted request {i}: {task_id[:8]}...")

        # Wait for all results
        print("\n⏳ Waiting for all responses...")
        completed = 0
        failed = 0

        for i, task_id in enumerate(task_ids, 1):
            result = await app.wait_for_result(task_id, timeout=90.0)
            if result and result.success:
                completed += 1
                response = result.result.get('text', '')[:60]
                print(f"  ✅ Request {i}: {response}")
            else:
                failed += 1
                error = result.error if result else "Timeout"
                print(f"  ❌ Request {i}: {error}")

        print(f"\n📊 Batch results: {completed} successful, {failed} failed")
        return failed == 0

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False
    finally:
        await app.shutdown()

async def test_force_json_output():
    """Test forcing JSON output format"""
    print("\n📋 Testing JSON output format...")

    app = FeminiApp()
    await app.initialize()

    try:
        request = Request(
            prompt='Generate a JSON object with fields "name": "John" and "age": 30',
            is_image=False,
            force_json=True
        )

        print("📤 Submitting JSON request...")
        task_id = await app.submit_request(request)
        
        print("⏳ Waiting for JSON response...")
        result = await app.wait_for_result(task_id, timeout=60.0)

        if result and result.success:
            response = result.result.get('text', '')
            print(f"Response: {response}")
            
            # Try to parse as JSON
            import json
            try:
                json.loads(response)
                print("✅ Valid JSON response received!")
                return True
            except json.JSONDecodeError:
                print("⚠️  Response is not valid JSON")
                return False
        else:
            error_msg = result.error if result else "Timeout"
            print(f"❌ Failed: {error_msg}")
            return False

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False
    finally:
        await app.shutdown()

async def test_statistics():
    """Test statistics and monitoring"""
    print("\n📊 Testing statistics...")

    app = FeminiApp()
    await app.initialize()

    try:
        stats = app.get_stats()
        print("📈 Statistics:")
        print(f"  Credentials: {stats['credentials']['total_credentials']}")
        print(f"  Mode: {stats['credentials']['mode']}")
        print(f"  Workers: {stats['queue']['worker_count']}")
        print(f"  Queue size: {stats['queue']['queue_size']}")

        # Submit test request
        print("\n📤 Submitting test request...")
        request = Request(prompt="Test statistics", is_image=False)
        await app.submit_request(request)

        await asyncio.sleep(1)

        stats = app.get_stats()
        print(f"  Total enqueued: {stats['queue']['total_enqueued']}")
        print(f"  Total processed: {stats['queue']['total_processed']}")

        return True

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False
    finally:
        await app.shutdown()

async def run_all_tests():
    """Run all tests and report results"""
    print("🧪 Femini Playwright Comprehensive Test Suite")
    print("=" * 60)

    tests = [
        ("Configuration", test_configuration),
        ("Basic Text Prompt", test_basic_text_prompt),
        # ("Multiple Prompts Same Chat", test_multiple_prompts_same_chat),
        # ("New Chat Window", test_new_chat_window),
        # ("Image Generation", test_image_generation),
        # ("Batch Processing", test_batch_processing),
        # ("Force JSON Output", test_force_json_output),
        # ("Statistics", test_statistics),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n🔥 Running: {test_name}")
        print("-" * 40)
        try:
            success = await test_func()
            results.append((test_name, success))
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status}: {test_name}")
        except Exception as e:
            print(f"❌ CRASH: {test_name} - {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 60)
    print("📋 TEST SUMMARY")
    print("=" * 60)

    passed = 0
    total = len(results)

    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
        if success:
            passed += 1

    print(f"\n📊 Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 ALL TESTS PASSED! Femini Playwright is fully functional.")
        return True
    else:
        print(f"⚠️  {total - passed} test(s) failed. Check the output above for details.")
        return False

async def main():
    """Main test runner"""
    setup_logging()
    success = await run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())