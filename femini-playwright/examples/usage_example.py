#!/usr/bin/env python3
"""
Usage examples for Femini Playwright
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path for examples
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src import FeminiApp, Request, setup_logging

async def basic_usage_example():
    """Basic usage example"""
    print("🚀 Starting Femini Playwright Basic Example")

    # Initialize app
    app = FeminiApp()
    await app.initialize()

    try:
        # Submit a text prompt
        text_request = Request(
            prompt="Hello! How are you today?",
            is_image=False,
            force_json=False,
            force_text=False
        )

        print("📤 Submitting text request...")
        task_id = await app.submit_request(text_request)
        print(f"✅ Request submitted with task ID: {task_id}")

        # Wait for result
        print("⏳ Waiting for response...")
        result = await app.wait_for_result(task_id, timeout=60.0)

        if result and result.success:
            print("🎉 Success!")
            print(f"Response: {result.result}")
            print(f"Processing time: {result.processing_time:.2f}s")
            print(f"Credential used: {result.credential_key}")
        elif result and result.error:
            print(f"❌ Error: {result.error}")
        else:
            print("⏰ Request timed out")

    finally:
        await app.shutdown()

async def image_generation_example():
    """Image generation example"""
    print("🎨 Starting Femini Playwright Image Generation Example")

    app = FeminiApp()
    await app.initialize()

    try:
        # Submit an image generation request
        image_request = Request(
            prompt="Generate a beautiful sunset over mountains",
            is_image=True,
            reference_image_name=None  # No reference image
        )

        print("📤 Submitting image generation request...")
        task_id = await app.submit_request(image_request)
        print(f"✅ Request submitted with task ID: {task_id}")

        # Wait for result (longer timeout for image generation)
        print("⏳ Waiting for image generation (this may take a while)...")
        result = await app.wait_for_result(task_id, timeout=300.0)  # 5 minutes

        if result and result.success:
            print("🎉 Image generated successfully!")
            print(f"Image URL: {result.result.get('url', 'N/A')}")
            print(f"Downloaded to: {result.result.get('path', 'N/A')}")
            print(f"Processing time: {result.processing_time:.2f}s")
            print(f"Credential used: {result.credential_key}")
        elif result and result.error:
            print(f"❌ Error: {result.error}")
        else:
            print("⏰ Image generation timed out")

    finally:
        await app.shutdown()

async def image_with_data_example():
    """Image generation with base64 data example"""
    print("🖼️ Starting Femini Playwright Image Generation with Data Example")

    app = FeminiApp()
    await app.initialize()

    try:
        # Submit an image generation request with data return enabled
        image_request = Request(
            prompt="Generate a minimalist tech logo",
            is_image=True,
            return_image_data=True  # Enable base64 data return
        )

        print("📤 Submitting image generation request with data return...")
        task_id = await app.submit_request(image_request)
        print(f"✅ Request submitted with task ID: {task_id}")

        # Wait for result
        print("⏳ Waiting for image generation...")
        result = await app.wait_for_result(task_id, timeout=300.0)

        if result and result.success:
            print("🎉 Image generated successfully!")
            print(f"Image URL: {result.result.get('url', 'N/A')}")
            print(f"Downloaded to: {result.result.get('path', 'N/A')}")
            
            # Check if base64 data is available
            if 'data' in result.result:
                print(f"📊 Image size: {result.result.get('size_bytes', 0)} bytes")
                print(f"📝 Base64 data length: {len(result.result['data'])} chars")
                print(f"🔤 Base64 preview: {result.result['data'][:50]}...")
                
                # You can now use the base64 data directly
                # For example, decode it back to bytes:
                import base64
                image_bytes = base64.b64decode(result.result['data'])
                print(f"✅ Successfully decoded {len(image_bytes)} bytes")
            else:
                print("ℹ️ No base64 data included in response")
            
            print(f"⏱️ Processing time: {result.processing_time:.2f}s")
        elif result and result.error:
            print(f"❌ Error: {result.error}")
        else:
            print("⏰ Image generation timed out")

    finally:
        await app.shutdown()

async def batch_processing_example():
    """Batch processing example"""
    print("📦 Starting Femini Playwright Batch Processing Example")

    app = FeminiApp()
    await app.initialize()

    try:
        # Create multiple requests
        prompts = [
            "What is the capital of France?",
            "Explain quantum computing in simple terms",
            "Write a haiku about artificial intelligence",
            "What are the benefits of renewable energy?",
            "Describe the water cycle"
        ]

        print(f"📤 Submitting {len(prompts)} requests...")

        # Submit all requests
        task_ids = []
        for prompt in prompts:
            request = Request(
                prompt=prompt,
                is_image=False,
                force_text=True  # Force plain text responses
            )
            task_id = await app.submit_request(request)
            task_ids.append(task_id)
            print(f"  ✅ Submitted: {task_id}")

        # Wait for all results
        print("⏳ Waiting for all responses...")
        completed = 0

        for task_id in task_ids:
            result = await app.wait_for_result(task_id, timeout=120.0)
            if result and result.success:
                completed += 1
                print(f"  ✅ {task_id}: {result.result.get('text', '')[:50]}...")
            elif result and result.error:
                print(f"  ❌ {task_id}: {result.error}")
            else:
                print(f"  ⏰ {task_id}: Timed out")

        print(f"📊 Completed {completed}/{len(prompts)} requests")

    finally:
        await app.shutdown()

async def stats_example():
    """Statistics and monitoring example"""
    print("📊 Starting Femini Playwright Stats Example")

    app = FeminiApp()
    await app.initialize()

    try:
        # Get initial stats
        stats = app.get_stats()
        print("📈 Initial Statistics:")
        print(f"  Credentials: {stats['credentials']['total_credentials']}")
        print(f"  Mode: {stats['credentials']['mode']}")
        print(f"  Workers: {stats['queue']['worker_count']}")
        print(f"  Queue size: {stats['queue']['queue_size']}")

        # Submit a few requests
        print("📤 Submitting test requests...")
        for i in range(3):
            request = Request(
                prompt=f"Test request {i+1}",
                is_image=False
            )
            await app.submit_request(request)

        await asyncio.sleep(2)  # Brief wait

        # Get updated stats
        stats = app.get_stats()
        print("📈 Updated Statistics:")
        print(f"  Queue size: {stats['queue']['queue_size']}")
        print(f"  Total enqueued: {stats['queue']['total_enqueued']}")
        print(f"  Total processed: {stats['queue']['total_processed']}")

    finally:
        await app.shutdown()

async def main():
    """Run examples"""
    print("🎯 Femini Playwright Examples")
    print("=" * 50)

    examples = [
        ("Basic Text Request", basic_usage_example),
        ("Image Generation", image_generation_example),
        ("Batch Processing", batch_processing_example),
        ("Statistics", stats_example),
    ]

    for name, example_func in examples:
        print(f"\n🔥 Running: {name}")
        print("-" * 30)
        try:
            await example_func()
        except Exception as e:
            print(f"❌ Example failed: {e}")
        print()

if __name__ == "__main__":
    # Setup logging
    setup_logging()

    # Run examples
    asyncio.run(main())