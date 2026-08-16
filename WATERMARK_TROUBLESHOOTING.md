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

---

## 🛑 Warning for Future Coding Agents: Failed Experiments to Avoid

In August 2026, a new "small translucent watermark" appeared in Gemini images, causing the standard template matching to fail. Below is a log of **failed approaches** taken to solve this. **Do not repeat these.**

### The "Frosted Oval" Rabbit Hole
The agent incorrectly identified a natural, star-shaped rock sitting inside a blurry patch of dirt as a "new dual-component watermark" consisting of a star and a frosted glass oval. The actual new watermark was a tiny translucent star hiding in the far bottom-right corner.

Because of this misidentification, several complex and destructive methods were attempted and eventually reverted:

1. **Attempted Deblurring (Unsharp Masking)**
   - **Hypothesis:** The "frosted oval" was an artificial Gaussian blur that could be reversed using Laplacian variance detection and an unsharp mask.
   - **Result:** Failed. Sharpness thresholding (`relative_sharpness < 0.40`) was too strict. Lowering it caused massive false positives on natural blurry backgrounds (like the sky or out-of-focus elements).
2. **Star-Anchored Oval Detection**
   - **Hypothesis:** Since general blur detection hit false positives, the agent assumed the frosted oval was always exactly ~112 pixels below the star logo, restricting the search.
   - **Result:** Failed. The template matcher was triggering on a false-positive rock (`corr=0.49`), so the anchor was in completely the wrong place.
3. **Wide-Context Inpainting**
   - **Hypothesis:** Abandon detection entirely and use a hardcoded elliptical mask at an offset from the star, then use `cv2.inpaint` with a huge context window to avoid propagating blur.
   - **Result:** Failed. Inpainting a large 80x70 region creates massive, ugly smudged artifacts, completely destroying the natural rock texture underneath.

### The Real Problem
- The rock/blur was just part of the natural photo.
- The **actual** new watermark is a small, translucent white star shape in the bottom-right corner.
- **Why it failed standard removal:** The new star has slightly different pixel thickness and points compared to the original `bg_48.png` template, resulting in a very low template matching correlation score (`~0.190`).
- **The Takeaway:** The current `cv2.matchTemplate` approach is brittle if the exact pixel layout of the watermark changes. If you are trying to fix detection for a new watermark, **extract the exact pixel shape of the new watermark from the image to use as a new template or mask**, rather than trying to build complex heuristic detectors for "blurry areas".


1408x768 : 1348 - 709
720x1456 : 660 - 1396
896x1200 : 836 - 1140
848x1264 : 787 - 1203
768x1376 : 707 - 1315


### 🎯 The Successful Resolution (August 2026 V2 Watermark)

The issue was successfully resolved by following the exact takeaway above: **extracting the mask from a pure black image.** Here are the key findings about the new V2 watermark and how it was fixed:

1. **Exact Size and Universal Placement:**
   Unlike the old watermarks which varied based on resolution (48px or 96px), the new Gemini watermark is a universal **24x24 pixel star**. Gemini now places this star exactly **48 pixels** from the bottom and right edges of the image (`margin = 48`), regardless of whether the image is a massive 16:9 desktop wallpaper or a tall 9:16 portrait.

2. **The "High-Contrast Boundary" Issue:**
   The new V2 watermark is extremely translucent. If the watermark happens to be placed on top of a highly contrasting background (e.g., half on bright skin, half on dark shadow), the `cv2.matchTemplate` correlation score will completely crash (dropping to ~0.19). This happens because the massive background variance mathematically drowns out the subtle star shape.
   - **The Fix:** We updated the `femini_watermark_remover.py` "Smart Fallback" logic. Since 99% of new images use the exact `margin=48` placement, if standard detection completely fails, the script now blindly assumes a V2 watermark is at `margin=48` and applies the perfect mathematical removal there.

3. **The "Black Watermark" Bug (Alpha Mask Normalization):**
   When extracting an alpha mask from a pure black image, **do not normalize the pixel values to 255.** The original mask extraction script incorrectly scaled the mask so the brightest pixel was 1.0 (100% opacity). However, the true maximum opacity of the V2 star is only **~30.6%**.
   - Because the mask was artificially made 3x too strong, the mathematical reversal formula over-subtracted white from the image. On bright backgrounds (like skin tones), this over-subtraction caused the pixels to turn black, leaving a dark shadow in the shape of a star.
   - **The Fix:** Re-extracted the `new_gemini_mask.png` from a black image and saved the exact, unscaled pixel values. The formula now uses the correct 30.6% opacity and perfectly restores the underlying image without leaving dark shadows.
