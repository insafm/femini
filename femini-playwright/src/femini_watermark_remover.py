import cv2
import urllib.request
import urllib.error
import numpy as np
from typing import Optional, Union
from pathlib import Path
from gemini_watermark_remover.watermark_remover import WatermarkRemover, WatermarkSize

class FeminiWatermarkRemover(WatermarkRemover):
    """
    Custom wrapper that overrides the watermark size detection logic.
    Gemini uses total area rather than independent width/height thresholds.
    This also adds support for fallback positions and sizes if the standard
    detection fails (e.g. 9:16 aspect ratios using SMALL size at 96px margin).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_margin: Optional[int] = None

    @staticmethod
    def get_watermark_size(image_width: int, image_height: int) -> WatermarkSize:
        # Gemini uses LARGE if the longest edge is > 1024
        if max(image_width, image_height) > 1024:
            return WatermarkSize.LARGE
        return WatermarkSize.SMALL

    def get_watermark_position(self, image_width: int, image_height: int,
                               size: WatermarkSize) -> tuple[int, int]:
        w, h, standard_margin = size.value
        margin = self.current_margin if self.current_margin is not None else standard_margin
        x = image_width - w - margin
        y = image_height - h - margin
        return (x, y)

    def get_correlation_score(self, image: np.ndarray, size: WatermarkSize, margin: int) -> float:
        height, width = image.shape[:2]
        w, h, _ = size.value
        x = width - w - margin
        y = height - h - margin
        if x < 0 or y < 0:
            return -1.0
            
        roi = image[y:y+h, x:x+w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
        
        if size == WatermarkSize.SMALL and getattr(self, 'alpha_map_small', None) is not None:
            alpha_map = self.alpha_map_small
        elif size == WatermarkSize.LARGE and getattr(self, 'alpha_map_large', None) is not None:
            alpha_map = self.alpha_map_large
        else:
            alpha_map = self.create_default_alpha_map(size)
            
        alpha_normalized = (alpha_map * 255).astype(np.float32)
        try:
            corr = np.corrcoef(gray.flatten(), alpha_normalized.flatten())[0, 1]
            return float(corr) if not np.isnan(corr) else -1.0
        except Exception:
            return -1.0

    def remove_watermark_from_region(self, image_region: np.ndarray, alpha_map: np.ndarray) -> np.ndarray:
        """
        Override the base class alpha blending with OpenCV inpainting
        to prevent color artifacts and seamlessly blend the watermark region.
        """
        # Create a binary mask from the alpha map
        mask = (alpha_map > 0.05).astype(np.uint8) * 255
        
        # Dilate mask slightly to cover the edges fully
        kernel = np.ones((3,3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
        
        # Use cv2.inpaint to fill the region based on surrounding pixels
        return cv2.inpaint(image_region, mask, 3, cv2.INPAINT_TELEA)

    def _load_v2_mask(self) -> Optional[np.ndarray]:
        if hasattr(self, '_v2_mask'):
            return self._v2_mask
        
        mask_path = Path(__file__).parent / 'gemini_watermark_v2_24px.png'
        if mask_path.exists():
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                self._v2_mask = (mask.astype(np.float32) / 255.0)
                return self._v2_mask
        return None

    def remove_watermark(self, image: np.ndarray,
                        force_size: Optional[WatermarkSize] = None,
                        force_margin: Optional[int] = None,
                        alpha_map: Optional[np.ndarray] = None,
                        auto_detect: bool = True) -> np.ndarray:
        if force_size and force_margin is not None:
            self.current_margin = force_margin
            return super().remove_watermark(image, force_size=force_size, alpha_map=alpha_map, auto_detect=False)

        if not auto_detect:
            return super().remove_watermark(image, force_size=force_size, alpha_map=alpha_map, auto_detect=False)

        height, width = image.shape[:2]
        
        # --- NEW V2 WATERMARK CHECK ---
        # The new Gemini watermark (August 2026) is exactly 24x24 
        # typically positioned exactly 48px from bottom-right corner.
        v2_mask = self._load_v2_mask()
        v2_w, v2_h = 24, 24
        if v2_mask is not None:
            # Check margins 48 and 49 (sometimes padded slightly differently)
            for test_margin in [48, 49]:
                x = width - v2_w - test_margin
                y = height - v2_h - test_margin
                
                if x >= 0 and y >= 0:
                    roi = image[y:y+v2_h, x:x+v2_w]
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
                    try:
                        corr = np.corrcoef(gray.flatten(), v2_mask.flatten())[0, 1]
                        if not np.isnan(corr) and corr > 0.40:
                            print(f"New V2 Watermark detected at ({x}, {y}) [margin {test_margin}] (correlation: {corr:.2f})")
                            alpha_3ch = np.stack([v2_mask]*3, axis=-1)
                            restored = (roi.astype(np.float32) - 255.0 * alpha_3ch) / np.clip(1.0 - alpha_3ch, 0.001, 1.0)
                            result = image.copy()
                            result[y:y+v2_h, x:x+v2_w] = np.clip(restored, 0, 255).astype(np.uint8)
                            return result
                    except Exception:
                        pass

        # --- OLD WATERMARK CHECK FALLBACK ---
        configs_to_try = []
        default_size = self.get_watermark_size(width, height)
        
        if force_size:
            configs_to_try.extend([
                (force_size, None), (force_size, 64), (force_size, 80), (force_size, 96),
            ])
        else:
            other_size = WatermarkSize.SMALL if default_size == WatermarkSize.LARGE else WatermarkSize.LARGE
            configs_to_try.extend([
                (default_size, None), (default_size, 64), (default_size, 80), (default_size, 96),
                (other_size, None), (other_size, 64), (other_size, 80), (other_size, 96)
            ])

        valid_configs = []
        for test_size, test_margin in configs_to_try:
            self.current_margin = test_margin
            actual_margin = test_margin if test_margin is not None else test_size.value[2]
            corr = self.get_correlation_score(image, test_size, actual_margin)
            is_detected = self.detect_watermark(image, force_size=test_size)
            
            if (is_detected and corr > 0.40) or corr > 0.60:
                valid_configs.append((corr, test_size, actual_margin))

        if valid_configs:
            valid_configs.sort(reverse=True, key=lambda x: x[0])
            best_corr, best_size, best_margin = valid_configs[0]
            self.current_margin = best_margin
            print(f"Legacy Watermark detected: size={best_size.name}, margin={best_margin} (correlation: {best_corr:.2f})")
            return super().remove_watermark(image, force_size=best_size, alpha_map=alpha_map, auto_detect=False)

        # Smart fallback if all detection completely fails (e.g., due to high-contrast boundary)
        print("Standard detection failed (possible high-contrast boundary). Applying V2 smart fallback at margin=48.")
        if v2_mask is not None:
            x = width - v2_w - 48
            y = height - v2_h - 48
            if x >= 0 and y >= 0:
                roi = image[y:y+v2_h, x:x+v2_w]
                alpha_3ch = np.stack([v2_mask]*3, axis=-1)
                restored = (roi.astype(np.float32) - 255.0 * alpha_3ch) / np.clip(1.0 - alpha_3ch, 0.001, 1.0)
                result = image.copy()
                result[y:y+v2_h, x:x+v2_w] = np.clip(restored, 0, 255).astype(np.uint8)
                return result

        # Ultimate fallback to old library logic
        self.current_margin = default_size.value[2]
        return super().remove_watermark(image, force_size=default_size, alpha_map=alpha_map, auto_detect=False)

def is_url(path: str) -> bool:
    """Check if the path is a URL."""
    return str(path).startswith(('http://', 'https://'))

def load_image_from_url(url: str) -> Optional[np.ndarray]:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = np.frombuffer(resp.read(), np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_COLOR)
            return image
    except Exception as e:
        print(f"Error: Failed to load image from URL: {e}")
        return None

def process_image_custom(input_path: Union[str, Path],
                         output_path: Union[str, Path],
                         remove: bool = True,
                         force_size: Optional[WatermarkSize] = None,
                         force_margin: Optional[int] = None,
                         logo_value: float = 255.0,
                         auto_detect: bool = True) -> bool:
    """
    Custom wrapper for processing images using FeminiWatermarkRemover.
    """
    try:
        input_str = str(input_path)
        output_path = Path(output_path)

        if is_url(input_str):
            image = load_image_from_url(input_str)
            if image is None:
                return False
        else:
            input_path = Path(input_str)
            image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
            if image is None:
                print(f"Error: Failed to load image: {input_path}")
                return False

        # Use our custom remover
        engine = FeminiWatermarkRemover(logo_value=logo_value)

        if remove:
            result = engine.remove_watermark(image, force_size=force_size, force_margin=force_margin, auto_detect=auto_detect)
        else:
            result = engine.add_watermark(image, force_size=force_size)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        ext = output_path.suffix.lower()
        if ext in ['.jpg', '.jpeg']:
            success = cv2.imwrite(str(output_path), result, [cv2.IMWRITE_JPEG_QUALITY, 100])
        elif ext == '.png':
            success = cv2.imwrite(str(output_path), result, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        elif ext == '.webp':
            success = cv2.imwrite(str(output_path), result, [cv2.IMWRITE_WEBP_QUALITY, 101])
        else:
            success = cv2.imwrite(str(output_path), result)

        if not success:
            print(f"Error: Failed to write image: {output_path}")
            return False

        return True

    except Exception as e:
        print(f"Error processing {input_path}: {e}")
        return False
