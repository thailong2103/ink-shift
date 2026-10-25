/**
 * Responsive Coordinate Mapping & Letterbox Geometry Math.
 *
 * Implements W3C-compliant geometry calculations to translate AI bounding
 * boxes normalized in range [0, 1000] to precise physical CSS pixels,
 * accounting for object-fit: contain/cover letterboxing and pillarboxing.
 */

import type { BoundingBox } from '../../types/contract';

export interface RenderedRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface BoundingBoxPixels {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Computes the exact inner rendered bounding rectangle of an HTMLImageElement,
 * isolating true artwork boundaries from CSS container letterboxes / pillarboxes.
 */
export function computeRenderedImageRect(img: HTMLImageElement): RenderedRect {
  const rect = img.getBoundingClientRect();
  const { clientWidth, clientHeight, naturalWidth, naturalHeight } = img;

  // Guard against unrendered elements or images with zero dimensions
  if (
    !naturalWidth ||
    !naturalHeight ||
    naturalWidth <= 0 ||
    naturalHeight <= 0 ||
    !clientWidth ||
    !clientHeight ||
    clientWidth <= 0 ||
    clientHeight <= 0
  ) {
    return {
      left: rect.left,
      top: rect.top,
      width: rect.width || clientWidth || 0,
      height: rect.height || clientHeight || 0,
    };
  }

  const imageAspect = naturalWidth / naturalHeight;
  const containerAspect = clientWidth / clientHeight;

  let renderedWidth: number;
  let renderedHeight: number;

  if (imageAspect > containerAspect) {
    // Artwork fits to container width, letterboxed vertically (black bars top & bottom)
    renderedWidth = clientWidth;
    renderedHeight = clientWidth / imageAspect;
  } else {
    // Artwork fits to container height, pillarboxed horizontally (black bars left & right)
    renderedHeight = clientHeight;
    renderedWidth = clientHeight * imageAspect;
  }

  const left = rect.left + (clientWidth - renderedWidth) / 2;
  const top = rect.top + (clientHeight - renderedHeight) / 2;

  return {
    left,
    top,
    width: renderedWidth,
    height: renderedHeight,
  };
}

/**
 * Maps a normalized [ymin, xmin, ymax, xmax] box from [0, 1000] into physical
 * CSS pixel dimensions relative to the inner rendered image rectangle.
 */
export function scaleBoxToPixels(
  box: BoundingBox,
  renderedRect: RenderedRect
): BoundingBoxPixels {
  const [ymin, xmin, ymax, xmax] = box;

  // Clamp normalized values to ensure speech bubbles do not escape rendered bounds
  const clampedYmin = Math.max(0, Math.min(1000, ymin));
  const clampedXmin = Math.max(0, Math.min(1000, xmin));
  const clampedYmax = Math.max(clampedYmin, Math.min(1000, ymax));
  const clampedXmax = Math.max(clampedXmin, Math.min(1000, xmax));

  const top = (clampedYmin / 1000) * renderedRect.height;
  const left = (clampedXmin / 1000) * renderedRect.width;
  const height = ((clampedYmax - clampedYmin) / 1000) * renderedRect.height;
  const width = ((clampedXmax - clampedXmin) / 1000) * renderedRect.width;

  return {
    top,
    left,
    width,
    height,
  };
}
