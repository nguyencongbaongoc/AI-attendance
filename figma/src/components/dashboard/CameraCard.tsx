// Camera Card Component - Live Camera Visualization with Real HLS Streams
// Displays real camera feed with detection overlays

import { useState, useEffect, useRef } from 'react';
import type { Camera } from '@/types/backend';
import { StatusDot } from '@/components/ui/DesignSystem';
import { useDetectionSnapshot } from '@/hooks/useHealth';
import { useVideoTransform, sourceBBoxToDisplay, sourceLineToDisplay, sourcePolygonToDisplay } from '@/utils/coordinateTransform';
import type { DetectionOverlayItem, LineOverlayItem, RegionOverlayItem } from '@/types/backend';

interface CameraCardProps {
  cam: Camera;
  onClick?: () => void;
}

// Map camera_id to HLS stream URL
const getHLSUrl = (cameraId: string): string => {
  const baseUrl = import.meta.env.VITE_HLS_BASE_URL || 'http://localhost:8888';
  return `${baseUrl}/live/${cameraId.toLowerCase()}/stream.m3u8`;
};

export default function CameraCard({ cam, onClick }: CameraCardProps) {
  const [hovered, setHovered] = useState(false);
  const [streamError, setStreamError] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<any>(null);

  // Get detection snapshot from WebSocket
  const { snapshot: detectionSnapshot } = useDetectionSnapshot(cam.id);

  // Get video transform for coordinate conversion
  const { transform, dimensions } = useVideoTransform(videoRef);

  // Initialize HLS.js for video playback
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const hlsUrl = getHLSUrl(cam.id);
    let hls: any = null;
    let cleanup: (() => void) | null = null;
    
    // Check if HLS.js is available (for browsers that don't support HLS natively)
    if (typeof window !== 'undefined' && (window as any).Hls) {
      const Hls = (window as any).Hls;
      if (Hls.isSupported()) {
        hls = new Hls({
          enableWorker: true,
          lowLatencyMode: true,
          liveSyncDurationCount: 3,
          liveMaxLatencyDuration: 5,
          liveBackBufferLength: 30,
        });
        
        hls.loadSource(hlsUrl);
        hls.attachMedia(video);
        hlsRef.current = hls;

        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          video.play().catch(() => {
            // Autoplay may be blocked, user interaction needed
            setIsPlaying(false);
          });
          setIsPlaying(true);
        });

        hls.on(Hls.Events.ERROR, (event: any, data: any) => {
          if (data.fatal) {
            setStreamError(true);
            console.error('HLS error:', data);
          }
        });

        cleanup = () => {
          hls.destroy();
        };
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        // Native HLS support (Safari)
        video.src = hlsUrl;
        const onLoadedMetadata = () => {
          video.play().catch(() => setIsPlaying(false));
        };
        const onError = () => setStreamError(true);
        video.addEventListener('loadedmetadata', onLoadedMetadata);
        video.addEventListener('error', onError);
        
        cleanup = () => {
          video.removeEventListener('loadedmetadata', onLoadedMetadata);
          video.removeEventListener('error', onError);
        };
      } else {
        setStreamError(true);
        cleanup = () => {};
      }
    } // Close the if (typeof window !== 'undefined' && (window as any).Hls) block

    return () => {
      if (cleanup) {
        cleanup();
      }
    };
  }, [cam.id]);

  // Determine status display
  const statusDisplay = cam.status;

  // Render detection bounding boxes
  const renderDetections = () => {
    if (!detectionSnapshot || !transform || !dimensions || dimensions.width === 0) {
      return null;
    }

    return detectionSnapshot.detections.map((detection: DetectionOverlayItem) => {
      const bbox = sourceBBoxToDisplay(
        detection.bbox,
        3840, 2160,
        dimensions.width, dimensions.height
      );

      const label = detection.identity_certainty === 'known' && detection.person_id
        ? detection.person_id
        : `Person ${detection.track_id}`;

      return (
        <div
          key={detection.track_id}
          className="absolute pointer-events-none"
          style={{
            left: `${bbox.x}px`,
            top: `${bbox.y}px`,
            width: `${bbox.width}px`,
            height: `${bbox.height}px`,
          }}
        >
          <div className="absolute inset-0 border border-cyan-400/60 rounded-sm" />
          <div className="absolute -top-5 left-0 flex items-center gap-1 whitespace-nowrap">
            <div className="h-px w-3 bg-cyan-400" />
            <span className="font-mono text-[9px] text-cyan-400">{label}</span>
          </div>
          <div className="absolute -bottom-5 left-0">
            <span className="font-mono text-[9px] text-cyan-400">
              {Math.round(detection.confidence * 100)}%
            </span>
          </div>
          {detection.identity_certainty !== 'known' && (
            <div className="absolute -top-10 left-0">
              <span className="font-mono text-[8px] text-amber-400 bg-black/50 px-1 rounded">
                {detection.identity_certainty.toUpperCase()}
              </span>
            </div>
          )}
        </div>
      );
    });
  };

  // Render lines (entry/exit)
  const renderLines = () => {
    if (!detectionSnapshot || !transform || !dimensions || dimensions.width === 0) {
      return null;
    }

    return detectionSnapshot.lines
      .filter((line: LineOverlayItem) => line.enabled)
      .map((line: LineOverlayItem) => {
        const displayLine = sourceLineToDisplay(
          line.x1, line.y1, line.x2, line.y2,
          3840, 2160,
          dimensions.width, dimensions.height
        );

        const isEntry = line.type === 'entry';
        const color = isEntry ? 'emerald-400' : 'amber-400';
        const arrowOffset = isEntry ? 10 : -10;

        return (
          <svg
            key={line.id}
            className="absolute inset-0 pointer-events-none"
            style={{ left: 0, top: 0, width: '100%', height: '100%' }}
          >
            <line
              x1={displayLine.x1}
              y1={displayLine.y1}
              x2={displayLine.x2}
              y2={displayLine.y2}
              stroke={color}
              strokeWidth="2"
              strokeDasharray="8,4"
              strokeLinecap="round"
            />
            {/* Arrow marker */}
            <polygon
              points={`${displayLine.x2},${displayLine.y2 - arrowOffset} ${displayLine.x2 - 8},${displayLine.y2} ${displayLine.x2 + 8},${displayLine.y2}`}
              fill={color}
            />
            <text
              x={(displayLine.x1 + displayLine.x2) / 2}
              y={(displayLine.y1 + displayLine.y2) / 2 - 10}
              fill={color}
              fontSize="10"
              fontFamily="monospace"
              textAnchor="middle"
            >
              {isEntry ? 'ENTRY' : 'EXIT'}
            </text>
          </svg>
        );
      });
  };

  // Render regions (ROI polygons)
  const renderRegions = () => {
    if (!detectionSnapshot || !transform || !dimensions || dimensions.width === 0) {
      return null;
    }

    return detectionSnapshot.regions
      .filter((region: RegionOverlayItem) => region.enabled)
      .map((region: RegionOverlayItem) => {
        const displayPoints = sourcePolygonToDisplay(
          region.points,
          3840, 2160,
          dimensions.width, dimensions.height
        );

        const pointsStr = displayPoints.map(([x, y]) => `${x},${y}`).join(' ');

        return (
          <svg
            key={region.id}
            className="absolute inset-0 pointer-events-none"
            style={{ left: 0, top: 0, width: '100%', height: '100%' }}
          >
            <polygon
              points={pointsStr}
              fill="rgba(0, 212, 255, 0.1)"
              stroke="cyan"
              strokeWidth="2"
              strokeDasharray="6,3"
            />
          </svg>
        );
      });
  };

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
      className={`relative rounded-xl overflow-hidden cursor-pointer transition-all duration-300 ${hovered ? "ring-1 ring-cyan-400/30 shadow-[0_0_24px_rgba(0,212,255,0.1)]" : "ring-1 ring-white/6"}`}
      style={{ aspectRatio: "16/9" }}
    >
      {/* Video feed */}
      <div className="absolute inset-0 bg-black">
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover"
          playsInline
          muted
          autoPlay
        />
        
        {/* Stream error overlay */}
        {streamError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/80">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
            </svg>
            <span className="text-[10px] font-mono text-white/40 uppercase tracking-wider">Stream Unavailable</span>
            <span className="text-[9px] text-white/30">HLS: {getHLSUrl(cam.id)}</span>
          </div>
        )}

        {/* Offline overlay */}
        {statusDisplay === 'offline' && !streamError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
            </svg>
            <span className="text-[10px] font-mono text-white/20 uppercase tracking-wider">Camera Offline</span>
          </div>
        )}

        {/* Overlay Layer */}
        <div className="absolute inset-0 pointer-events-none">
          {/* Detection bounding boxes */}
          {renderDetections()}
          
          {/* Lines (entry/exit) */}
          {renderLines()}
          
          {/* Regions (ROI polygons) */}
          {renderRegions()}
        </div>

        {/* Corner crosshairs for live cameras */}
        {statusDisplay === 'live' && (
          <>
            <div className="absolute top-1.5 left-1.5 w-3 h-3 border-t border-l border-cyan-400/30" />
            <div className="absolute top-1.5 right-1.5 w-3 h-3 border-t border-r border-cyan-400/30" />
            <div className="absolute bottom-7 left-1.5 w-3 h-3 border-b border-l border-cyan-400/30" />
            <div className="absolute bottom-7 right-1.5 w-3 h-3 border-b border-r border-cyan-400/30" />
          </>
        )}
      </div>

      {/* Top bar */}
      <div className="absolute top-0 left-0 right-0 flex items-center justify-between px-2.5 py-1.5 bg-gradient-to-b from-black/60 to-transparent">
        <div className="flex items-center gap-1.5">
          <StatusDot status={statusDisplay} />
          <span className="font-mono text-[10px] text-white/70">{cam.id}</span>
        </div>
        <span className="font-mono text-[10px] text-white/50">
          {cam.resolution} · {cam.fps > 0 ? `${cam.fps}fps` : '—'}
        </span>
      </div>

      {/* Bottom bar */}
      <div className="absolute bottom-0 left-0 right-0 px-2.5 py-1.5 bg-gradient-to-t from-black/80 to-transparent">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-white/75 font-medium truncate">{cam.name}</span>
          <span className="font-mono text-[10px] text-white/40">{cam.lastEvent}</span>
        </div>
        <div className="text-[10px] text-white/35 truncate">{cam.location}</div>
      </div>

      {/* Status badges */}
      <div className="absolute top-1.5 right-1.5 flex flex-col gap-1">
        {statusDisplay === 'live' && (
          <span className="font-mono text-[9px] bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 rounded px-1.5 py-0.5">
            LIVE
          </span>
        )}
        {statusDisplay === 'degraded' && (
          <span className="font-mono text-[9px] bg-amber-500/20 border border-amber-500/30 text-amber-400 rounded px-1.5 py-0.5">
            DEGRADED
          </span>
        )}
        {statusDisplay === 'stale' && (
          <span className="font-mono text-[9px] bg-amber-500/20 border border-amber-500/30 text-amber-400 rounded px-1.5 py-0.5">
            STALE
          </span>
        )}
        {cam.fps > 0 && (
          <span className="font-mono text-[9px] bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 rounded px-1.5 py-0.5">
            {cam.fps}fps
          </span>
        )}
      </div>
    </div>
  );
}
