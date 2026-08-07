#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Add femini-playwright to sys.path so we can import src.gemini_client
sys.path.append(str(Path(__file__).parent / "femini-playwright"))
from src.femini_watermark_remover import process_image_custom
from gemini_watermark_remover.watermark_remover import WatermarkSize

def main():
    parser = argparse.ArgumentParser(description="Manually remove Gemini watermark using robust OpenCV inpainting.")
    parser.add_argument("input_image", help="Path to the input image")
    parser.add_argument("--output", "-o", help="Path to save the output image. If not provided, saves as <original_name>_cleaned.png")
    parser.add_argument("--size", "-s", choices=["small", "large", "auto"], default="auto", help="Force watermark size (small, large, or auto). Default is auto.")
    parser.add_argument("--margin", "-m", type=int, default=None, help="Force a specific margin (e.g., 64). Overrides auto-detection if size is also set.")
    
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

    force_size = None
    if args.size == "small":
        force_size = WatermarkSize.SMALL
    elif args.size == "large":
        force_size = WatermarkSize.LARGE

    success = process_image_custom(
        input_path=str(input_path),
        output_path=str(output_path),
        remove=True,
        force_size=force_size,
        force_margin=args.margin,
        auto_detect=True
    )
    
    if success:
        print(f"\nSuccess! Watermark removed and saved to:\n{output_path}")
    else:
        print("\nFailed to process the image.")

if __name__ == "__main__":
    main()
