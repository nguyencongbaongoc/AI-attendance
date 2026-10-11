with open('C:/Users/Nguyen Cong Thong/Documents/AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE/app/streaming/annotated_publisher.py', 'r') as f:
    content = f.read()

# Find and replace the pattern
old = 'return False\n\n\n\n\n    # -------------------------------------------------------------- internals'
new = '''return False


    def submit(
        self,
        frame_data: GPUFrameContract,
        detections: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Submit a GPUFrameContract with overlay items for GPU annotation + NVENC encoding.
        
        This is the GPU-native path: GPUFrameContract -> GPU annotation -> Native NVENC -> H.264 -> Publisher -> MediaMTX
        No CPU raw-frame staging occurs.
        """
        if not self._metrics.started or self._stop_event.is_set():
            return False
        if frame_data is None:
            logger.error("AnnotatedFramePublisher(%s): submit requires GPUFrameContract; got None", self.camera_id)
            return False

        self._metrics.frames_submitted += 1

        try:
            # Initialize GPU annotation renderer if enabled and not yet created
            if self._gpu_annotation_enabled and self._gpu_annotation_renderer is None:
                gpu_config = GPUAnnotationPyAVConfig(
                    enabled=True,
                    gpu_device=0,
                    text_enabled=True,
                    text_font_path=self.config.gpu_annotation_font_path,
                    text_font_size=self.config.gpu_annotation_font_size,
                )
                self._gpu_annotation_renderer = get_gpu_annotation_pyav_renderer(self.camera_id, gpu_config)
                logger.info("AnnotatedFramePublisher(%s): GPU annotation renderer initialized", self.camera_id)

            # Initialize native NVENC encoder if not yet created
            if self._encoder is None and not self._encoder_initialized:
                import torch
                torch_stream = torch.cuda.Stream()
                self._encoder = EncoderAdapter(
                    codec=self.config.encoder_codec,
                    preset=self.config.encoder_preset,
                    fps=self.config.fps,
                    bitrate_kbps=self.config.encoder_bitrate_kbps,
                    max_bitrate_kbps=self.config.encoder_max_bitrate_kbps,
                    gop_length=self.config.encoder_gop_length,
                    idr_period=self.config.encoder_idr_period,
                    cuda_stream=torch_stream.cuda_stream,
                )
                self._encoder.open(width=frame_data.width, height=frame_data.height)
                self._encoder_initialized = True
                logger.info("AnnotatedFramePublisher(%s): Native NVENC encoder initialized (%dx%d)", 
                           self.camera_id, frame_data.width, frame_data.height)

            # Initialize packet bridge if not yet created
            if self._packet_bridge is None:
                self._packet_bridge = EncoderPacketToPublisherBridge(
                    rtsp_url=self.config.rtsp_url,
                    width=frame_data.width,
                    height=frame_data.height,
                    fps=self.config.fps,
                )
                self._packet_bridge.start(bitrate_kbps=self.config.encoder_bitrate_kbps, gop_seconds=self.config.gop_seconds)
                logger.info("AnnotatedFramePublisher(%s): Packet bridge started", self.camera_id)

            # Get NV12 planes from GPUFrameContract
            y_tensor, uv_tensor = frame_data.get_tensors()

            # Apply GPU annotation if enabled
            if self._gpu_annotation_enabled and self._gpu_annotation_renderer is not None:
                try:
                    annotated_y, annotated_uv = self._gpu_annotation_renderer.annotate_nv12(
                        y_plane=y_tensor,
                        uv_plane=uv_tensor,
                        detections=detections,
                        lines=lines,
                        regions=regions,
                        camera_id=self.camera_id,
                    )
                    # Use annotated planes
                    y_tensor, uv_tensor = annotated_y, annotated_uv
                except Exception as e:
                    logger.error("AnnotatedFramePublisher(%s): GPU annotation failed: %s", self.camera_id, e)
                    # Continue without annotation (use original planes)

            # Encode using native NVENC
            packets = self._encoder.encode_frame(
                gpu_frame_ref=frame_data,
                pts=frame_data.pts,
                frame_id=frame_data.frame_id,
                camera_id=frame_data.camera_id,
            )

            # Submit packets to publisher bridge
            if packets and self._packet_bridge:
                for pkt in packets:
                    data = pkt.get('data', b'')
                    if data:
                        self._packet_bridge.submit_packet_bytes(data)
                        self._metrics.frames_encoded += 1
                        self._metrics.last_encode_time = self._time()

            return True

        except Exception as e:
            logger.error("AnnotatedFramePublisher(%s): submit failed: %s", self.camera_id, e)
            self._metrics.last_error = str(e)
            return False


    # -------------------------------------------------------------- internals'''

if old in content:
    content = content.replace(old, new)
    with open('C:/Users/Nguyen Cong Thong/Documents/AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE/app/streaming/annotated_publisher.py', 'w') as f:
        f.write(content)
    print('Replaced successfully')
else:
    print('Pattern not found')
    # Debug: show what we have
    idx = content.find('return False')
    positions = []
    while idx >= 0:
        positions.append(idx)
        idx = content.find('return False', idx+1)
    for pos in positions:
        context = content[pos:pos+80]
        print(f'Position {pos}: {repr(context[:60])}')