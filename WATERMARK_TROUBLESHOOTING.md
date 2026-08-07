# Gemini Watermark Removal Troubleshooting

This guide explains how to troubleshoot and fix cases where the automated Gemini watermark removal fails.

## Why Automated Removal Fails
The `py-gemini-watermark-remover` library is generally robust, but it can fail due to two main reasons:

1. **High-Contrast Boundaries:** The library verifies a watermark's presence by analyzing the background color underneath it. If the watermark sits across a sharp boundary (e.g., half on a black shirt, half on a white wall), the library sees the massive color difference, assumes it isn't a watermark, and skips it.
2. **Padding / Cropping:** If an image is downloaded from a platform like Instagram that adds padding (e.g., fitting a 9:16 image into a 3:4 canvas), the watermark is shifted away from the standard corners.

---

## 🛠️ How to Fix a Failing Image

If the `manual_watermark_removal.py` script fails to remove a watermark automatically, follow these steps:

### 1. Identify the Size and Margin Manually
You can bypass the automatic detection completely by providing the `--size` and `--margin` arguments to the script.

- **Size:** Gemini uses `large` (96x96 px) if the longest dimension of the image is > 1024. Otherwise, it uses `small` (48x48 px). For a standard 768x1376 image, the size is **large**.
- **Margin:** The margin is the distance (in pixels) from the watermark to the edge of the image. Standard margins are typically:
  - `32` (for SMALL)
  - `64` (for LARGE)
  - `80` or `96` (often seen in padded/cropped images)

### 2. Run with Overrides
Test common configurations using the manual script:

```bash
# Try standard Large (64 margin)
python manual_watermark_removal.py path/to/image.png --size large --margin 64

# Try standard Small (32 margin)
python manual_watermark_removal.py path/to/image.png --size small --margin 32

# Try Padded Fallbacks
python manual_watermark_removal.py path/to/image.png --size large --margin 80
python manual_watermark_removal.py path/to/image.png --size large --margin 96
```

### 3. Check the Output
The script will save the result as `[original_name]_cleaned.png`. Open the image and inspect the bottom right corner.
- If the watermark is cleanly removed, you found the right margin.
- If the watermark is untouched but a different part of the image is blurred, your margin is incorrect. Adjust the margin and try again.

---

## Technical Details

If you need to edit `femini_watermark_remover.py` in the future:
- The detection threshold is configured at `corr > 0.40`. If you lower this, you will increase the risk of false positives (blurring random parts of the image).
- The "Smart Fallback" logic at the end of the `remove_watermark` function automatically guesses `size=LARGE, margin=64` for 9:16 images if strict detection fails. If Gemini changes their default placement in the future, update the `fallback_margin` variable there.
