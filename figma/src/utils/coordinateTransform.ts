// Coordinate Transform Utility
// Canonical transform from ORIGINAL_FRAME (3840x2160) to display coordinates
// Handles object-fit: cover behavior with letterboxing/pillarboxing

import React from 'react';

export interface TransformResult {
  x: number;
  y: number;
  scale: number;
  offsetX: number;
  offsetY: number;
}

export interface BBoxTransformResult {
  x: number;
  y: number;
  width: number;
  height: number;
  scale: number;
}

export interface DisplayDimensions {
  width: number;
  height: number;
}

export interface SourceDimensions {
  width: number;
  height: number;
}

/**
 * Calculate the transform from source (ORIGINAL_FRAME) to display coordinates
 * Accounts for object-fit: cover behavior (letterboxing/pillarboxing)
 * 
 * @param sourceW - Source frame width (e.g., 3840)
 * @param sourceH - Source frame height (e.g., 2160)
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Transform parameters
 */
export function calculateTransform(
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): TransformResult {
  const sourceAspect = sourceW / sourceH;
  const displayAspect = displayW / displayH;

  let scale: number;
  let offsetX = 0;
  let offsetY = 0;

  if (sourceAspect > displayAspect) {
    // Source is wider than display - pillarboxed (black bars on left/right)
    scale = displayH / sourceH;
    offsetX = (displayW - sourceW * scale) / 2;
  } else {
    // Source is taller than display - letterboxed (black bars on top/bottom)
    scale = displayW / sourceW;
    offsetY = (displayH - sourceH * scale) / 2;
  }

  return { x: 0, y: 0, scale, offsetX, offsetY };
}

/**
 * Transform a single point from source (ORIGINAL_FRAME) to display coordinates
 * 
 * @param x - Source X coordinate
 * @param y - Source Y coordinate
 * @param sourceW - Source frame width
 * @param sourceH - Source frame height
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Display coordinates
 */
export function sourceToDisplay(
  x: number,
  y: number,
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): { x: number; y: number } {
  const { scale, offsetX, offsetY } = calculateTransform(sourceW, sourceH, displayW, displayH);
  return {
    x: x * scale + offsetX,
    y: y * scale + offsetY,
  };
}

/**
 * Transform a bounding box from source (ORIGINAL_FRAME) to display coordinates
 * 
 * @param bbox - Source bbox [x1, y1, x2, y2]
 * @param sourceW - Source frame width
 * @param sourceH - Source frame height
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Display bbox { x, y, width, height }
 */
export function sourceBBoxToDisplay(
  bbox: [number, number, number, number],
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): BBoxTransformResult {
  const { scale, offsetX, offsetY } = calculateTransform(sourceW, sourceH, displayW, displayH);
  
  const [x1, y1, x2, y2] = bbox;
  const displayX1 = x1 * scale + offsetX;
  const displayY1 = y1 * scale + offsetY;
  const displayX2 = x2 * scale + offsetX;
  const displayY2 = y2 * scale + offsetY;

  return {
    x: displayX1,
    y: displayY1,
    width: displayX2 - displayX1,
    height: displayY2 - displayY1,
    scale,
  };
}

/**
 * Transform a line from source (ORIGINAL_FRAME) to display coordinates
 * 
 * @param x1 - Source start X
 * @param y1 - Source start Y
 * @param x2 - Source end X
 * @param y2 - Source end Y
 * @param sourceW - Source frame width
 * @param sourceH - Source frame height
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Display line coordinates
 */
export function sourceLineToDisplay(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): { x1: number; y1: number; x2: number; y2: number } {
  const { scale, offsetX, offsetY } = calculateTransform(sourceW, sourceH, displayW, displayH);
  return {
    x1: x1 * scale + offsetX,
    y1: y1 * scale + offsetY,
    x2: x2 * scale + offsetX,
    y2: y2 * scale + offsetY,
  };
}

/**
 * Transform polygon points from source (ORIGINAL_FRAME) to display coordinates
 * 
 * @param points - Array of [x, y] points in source coordinates
 * @param sourceW - Source frame width
 * @param sourceH - Source frame height
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Array of display points
 */
export function sourcePolygonToDisplay(
  points: [number, number][],
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): [number, number][] {
  const { scale, offsetX, offsetY } = calculateTransform(sourceW, sourceH, displayW, displayH);
  return points.map(([x, y]) => [
    x * scale + offsetX,
    y * scale + offsetY,
  ]) as [number, number][];
}

/**
 * Transform from display coordinates back to source (ORIGINAL_FRAME) coordinates
 * 
 * @param x - Display X coordinate
 * @param y - Display Y coordinate
 * @param sourceW - Source frame width
 * @param sourceH - Source frame height
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Source coordinates
 */
export function displayToSource(
  x: number,
  y: number,
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): { x: number; y: number } {
  const { scale, offsetX, offsetY } = calculateTransform(sourceW, sourceH, displayW, displayH);
  return {
    x: (x - offsetX) / scale,
    y: (y - offsetY) / scale,
  };
}

/**
 * Transform display bbox back to source coordinates
 * 
 * @param bbox - Display bbox { x, y, width, height }
 * @param sourceW - Source frame width
 * @param sourceH - Source frame height
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Source bbox [x1, y1, x2, y2]
 */
export function displayBBoxToSource(
  bbox: { x: number; y: number; width: number; height: number },
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number
): [number, number, number, number] {
  const { scale, offsetX, offsetY } = calculateTransform(sourceW, sourceH, displayW, displayH);
  const x1 = (bbox.x - offsetX) / scale;
  const y1 = (bbox.y - offsetY) / scale;
  const x2 = (bbox.x + bbox.width - offsetX) / scale;
  const y2 = (bbox.y + bbox.height - offsetY) / scale;
  return [x1, y1, x2, y2];
}

/**
 * Get the video element's actual rendered dimensions
 * Accounts for object-fit: cover and aspect-ratio
 * 
 * @param videoElement - HTMLVideoElement
 * @returns Actual rendered dimensions
 */
export function getVideoRenderedDimensions(videoElement: HTMLVideoElement): DisplayDimensions {
  // The video element fills its container with object-fit: cover
  // The container has aspect-ratio: 16/9
  const container = videoElement.parentElement;
  if (!container) {
    return { width: videoElement.clientWidth, height: videoElement.clientHeight };
  }
  
  const rect = container.getBoundingClientRect();
  return { width: rect.width, height: rect.height };
}

/**
 * Canonical source dimensions for project cameras
 */
export const CANONICAL_SOURCE_DIMENSIONS: SourceDimensions = {
  width: 3840,
  height: 2160,
};

/**
 * Create a transform function bound to canonical source dimensions
 * 
 * @param displayW - Display container width
 * @param displayH - Display container height
 * @returns Transform functions
 */
export function createCanonicalTransform(displayW: number, displayH: number) {
  const { width: sourceW, height: sourceH } = CANONICAL_SOURCE_DIMENSIONS;
  
  return {
    sourceToDisplay: (x: number, y: number) => sourceToDisplay(x, y, sourceW, sourceH, displayW, displayH),
    sourceBBoxToDisplay: (bbox: [number, number, number, number]) => sourceBBoxToDisplay(bbox, sourceW, sourceH, displayW, displayH),
    sourceLineToDisplay: (x1: number, y1: number, x2: number, y2: number) => sourceLineToDisplay(x1, y1, x2, y2, sourceW, sourceH, displayW, displayH),
    sourcePolygonToDisplay: (points: [number, number][]) => sourcePolygonToDisplay(points, sourceW, sourceH, displayW, displayH),
    displayToSource: (x: number, y: number) => displayToSource(x, y, sourceW, sourceH, displayW, displayH),
    displayBBoxToSource: (bbox: { x: number; y: number; width: number; height: number }) => displayBBoxToSource(bbox, sourceW, sourceH, displayW, displayH),
    getTransformParams: () => calculateTransform(sourceW, sourceH, displayW, displayH),
  };
}

/**
 * Hook to get video dimensions and create transform
 * 
 * @param videoRef - Ref to video element
 * @returns Transform functions and video dimensions
 */
export function useVideoTransform(videoRef: React.RefObject<HTMLVideoElement | null>) {
  const [dimensions, setDimensions] = React.useState<DisplayDimensions>({ width: 0, height: 0 });
  
  React.useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    
    const updateDimensions = () => {
      const dims = getVideoRenderedDimensions(video);
      setDimensions(dims);
    };
    
    // Initial measurement
    updateDimensions();
    
    // Observe resize
    const resizeObserver = new ResizeObserver(updateDimensions);
    const container = video.parentElement;
    if (container) {
      resizeObserver.observe(container);
    }
    
    return () => {
      resizeObserver.disconnect();
    };
  }, [videoRef]);
  
  const transform = dimensions.width > 0 && dimensions.height > 0
    ? createCanonicalTransform(dimensions.width, dimensions.height)
    : null;
  
  return { transform, dimensions };
}
