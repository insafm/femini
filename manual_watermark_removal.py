#!/usr/bin/env python3
import argparse
import sys
import asyncio
from pathlib import Path

# Add femini-playwright to sys.path so we can import src.gemini_client
sys.path.append(str(Path(__file__).parent / "femini-playwright"))
from src.gemini_client import GeminiClient

def main():
    parser = argparse.ArgumentParser(description="Manually remove Gemini watermark using robust OpenCV inpainting.")
    parser.add_argument("input_image", help="Path to the input image")
    parser.add_argument("--output", "-o", help="Path to save the output image. If not provided, saves as <original_name>_cleaned.png")
    parser.add_argument("--size", "-s", choices=["small", "large", "auto"], default="auto", help="Force watermark size (small, large, or auto). Default is auto.")
    
    args = parser.parse_args()

    input_path = Path(args.input_image)
    if not input_path.exists():
        print(f"Error: File not found at {input_path}")
        return

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_cleaned{input_path.suffix}"

    print(f"Processing image: {input_path}")

    success = asyncio.run(GeminiClient.remove_watermark(str(input_path), str(output_path)))
    
    if success:
        print(f"\nSuccess! Watermark removed and saved to:\n{output_path}")
    else:
        print("\nFailed to process the image.")

if __name__ == "__main__":
    main()
