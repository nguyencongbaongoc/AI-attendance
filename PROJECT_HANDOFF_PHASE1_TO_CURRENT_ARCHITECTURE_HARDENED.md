# PROJECT HANDOFF — PHASE 1 → CURRENT
## Nguồn sự thật để chuyển sang conversation mới

> Mục đích: nén toàn bộ các quyết định, kiến trúc, trạng thái phase và hướng triển khai đã chốt trong conversation cũ thành một tài liệu duy nhất.
>
> **NEXT ACTION hiện tại: Phase 16 — Adaptive Person/Face Crop.**
>
> Không quay lại các quyết định đã chốt trừ khi có bằng chứng kỹ thuật mới.

---

# 1. MỤC TIÊU DỰ ÁN

Hệ thống là hệ thống computer vision/attendance dùng:

- 2 camera iPhone
- camera chính 1×
- 4K
- RTMP từ iPhone
- máy nhận mở RTMP listening port
- MediaMTX làm media router
- AI đọc stream nội bộ, ưu tiên RTSP từ MediaMTX
- YOLO11n để phát hiện person
- dynamic crop từ frame 4K gốc
- face detector
- 1K3D68 cho hard-pose/alignment
- ArcFace 112×112 → 512D embedding
- database embedding `.npy`
- identity matching
- tracking
- cross-camera association
- IN/OUT
- timetable UI
- attendance
- immediate output
- daily Excel

Mục tiêu kiến trúc là:
- model-independent contracts
- provenance rõ ràng
- ORIGINAL_FRAME 4K là nguồn tọa độ/ảnh gốc
- camera có thể thay thế cho nhau
- một camera hỏng không làm toàn hệ thống dừng
- AI offline/replay phải hoàn thiện trước live
- debug theo từng phase, không tạo loop sửa lỗi vô hạn

---

# 2. KIẾN TRÚC TỔNG THỂ ĐÃ CHỐT

```text
              IPHONE CAM 1
                1× / 4K
                    │
                   RTMP
                    │
                    ├───────────────┐
                    │               │
              Receiver Machine      │
                    │               │
                 MediaMTX           │
                  /cam1              │
                    │               │
                   RTSP              │
                    │               │
                    ▼               │
                AI Ingest 1         │
                                    │
              IPHONE CAM 2          │
                1× / 4K             │
                    │               │
                   RTMP              │
                    │               │
              Receiver Machine       │
                    │               │
                 MediaMTX            │
                  /cam2              │
                    │               │
                   RTSP              │
                    │               │
                    ▼               │
                AI Ingest 2         │
                    │               │
                    └──────┬────────┘
                           ▼
                  CanonicalFrame
                    per camera
                           │
                           ▼
                       YOLO11n
                        640×640
                           │
                           ▼
                  Restore bbox → 4K
                           │
                           ▼
                 Dynamic Person Crop
                           │
                           ▼
                    Face Detector
                           │
                           ▼
                  Dynamic Face Crop
                           │
                           ▼
                    Quality + Pose
                      │         │
                    NORMAL   HARD_POSE
                      │         │
                      │      1K3D68
                      │      192×192
                      │         │
                      └────┬────┘
                           ▼
                       Alignment
                           │
                         112×112
                           │
                        ArcFace
                           │
                         512D
                           │
                   Phase 14 Matching
                           │
                  Temporal Evidence
                           │
             Cross-Camera Association
                           │
                  Global Observation
                           │
                 IN/OUT Geometry UI
                           │
                       IN / OUT
                           │
                      Attendance
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
            Live UI    Immediate     Daily Excel
                        Output
```

---

# 3. CÁC QUYẾT ĐỊNH KIẾN TRÚC QUAN TRỌNG

## 3.1 4K là nguồn sự thật

`ORIGINAL_FRAME` giữ nguyên 3840×2160.

Không được dùng tensor 640×640 của YOLO làm nguồn ảnh cuối cho face recognition.

Luồng:

```text
4K ORIGINAL_FRAME
    ↓
YOLO preprocessing 640×640
    ↓
person bbox
    ↓
restore bbox → ORIGINAL_FRAME
    ↓
dynamic person crop từ 4K
    ↓
face detection
    ↓
dynamic face crop từ ảnh gốc/crop có provenance rõ
```

## 3.2 Model resolution

- YOLO11n: `640×640`
- 1K3D68: `192×192`
- ArcFace: `112×112`

Chỉ resize khi model tương ứng yêu cầu.

Không resize toàn frame 4K trước rồi mới crop mặt.

## 3.3 Dynamic crop

Không dùng:

```text
small face → reject person
```

Mà:

```text
frame hiện tại xấu
→ bỏ frame khỏi identity evidence
→ giữ person track
→ chờ frame tốt hơn
```

Person crop có kích thước động theo bbox.

Face crop cũng động.

## 3.4 Hai camera đối xứng

Không cố định:

```text
CAM1 = identity
CAM2 = doorway
```

Cả hai đều có khả năng:

- detect person
- tracking
- face/identity evidence
- crossing evidence

Vai trò có thể ưu tiên theo chất lượng quan sát.

Camera 1 và Camera 2 có thể thay thế cho nhau.

## 3.5 Local track và global observation

Không giả định:

```text
CAM1 track_id == CAM2 track_id
```

Mỗi camera có local track ID.

Sau đó tạo:

```text
global_observation_id
```

qua cross-camera association dựa trên:

- timestamp proximity
- doorway geometry
- direction
- local track continuity
- identity evidence
- camera provenance

## 3.6 Identity khác Attendance

Tách:

```text
Detection
≠ Tracking
≠ Identity
≠ Attendance
```

Một người có thể:

```text
track = ACTIVE
identity = UNKNOWN
```

mà vẫn có raw IN/OUT observation.

## 3.7 Raw event bất biến

Raw IN/OUT events không bị xóa khi trạng thái về sau thay đổi.

Derived attendance state xử lý riêng.

## 3.8 IN/OUT vẽ trên UI

Geometry không hard-code.

UI phải cho phép:

- vẽ IN line
- vẽ OUT line
- hoặc IN/OUT zones
- kéo/chỉnh
- preview crossing
- lưu theo `camera_id`
- version geometry

Geometry lưu theo ORIGINAL_FRAME coordinates.

Mỗi camera có geometry riêng.

---

# 4. CÁC PHASE ĐÃ HOÀN THÀNH

## Phase 1 — Foundation
Đã hoàn thành.

Các nền tảng đã được kế thừa về sau:
- project structure
- centralized logging
- pathlib path system
- FFmpeg detection
- Python/venv foundation

---

## Phase 2–3 — Runtime / Environment Foundation
Đã hoàn thành theo tiến trình dự án.

Đã được các phase sau tái sử dụng:
- NVIDIA detection
- CUDA detection
- runtime/environment foundations

---

## Phase 4–6 — Vision/Data Foundation
Đã hoàn thành và được các phase sau kế thừa.

Các contract/data pipeline được tiếp tục sử dụng.

---

# 5. SCRFD / PHASE 7R

## Phase 7R.2 — SCRFD Deep Diagnostic

Kết luận:

**PARTIAL**

Các phát hiện chính:

- SCRFD CPU ổn định/deterministic.
- CUDA lỗi ở môi trường runtime.
- CUDA lỗi `LoadLibrary` / CUDA provider.
- CUDA/cuDNN mismatch với ONNX Runtime 1.17.0.
- CUDA 13.3 / cuDNN 9.2 không tương thích với runtime đang dùng.
- SCRFD native input là `640×640`.
- Contract đã được sửa từ `960×960` về `640×640`.
- Không được coi `960×960` là native SCRFD contract.

CPU path ổn định.

## Phase 7R.3

Đã có technical debt liên quan contract 640×640.

Full regression từng có 2 test fail vì test hard-code `960×960`; sau đó contract được sửa về 640×640.

Cuối cùng quyết định:
- không tiếp tục kéo dài 7R.3
- detector abstraction tách riêng
- detector selection để mở

---

# 6. PHASE 8 — FACE DETECTOR ABSTRACTION

**PASS**

Kết quả:
- 47/47 Phase 8 tests
- full regression: 503 passed, 5 skipped, 0 failed
- safety pass

Files chính:
- `app/vision/detector_contract.py`
- `app/vision/scrfd_adapter.py`
- `app/vision/retinaface_adapter.py`
- `app/vision/detector_factory.py`
- `tests/unit/test_detector_contract.py`

Quyết định:
- detector selection OPEN
- SCRFD vẫn giữ 640×640
- RetinaFace có adapter placeholder, không silent fallback
- downstream dùng generic detector contract
- không để SCRFD-specific logic leak xuống dưới

---

# 7. PHASE 9 — YOLO11n 4K PERSON DETECTION

**PASS**

Mục tiêu:
- input 4K `3840×2160`
- YOLO11n preprocessing `640×640`
- person class only
- coordinate restoration về 4K

Kết quả:
- restoration mathematically exact
- scale factor `0.166667`
- vertical padding `140`
- max restoration error `0.00 px`
- boundary error khoảng `6.1e-05 px`
- CPU benchmark khoảng 288.5 ms total trong test
- memory bounded
- full regression: 503 passed, 0 failed, 5 skipped

Công thức:

```text
bbox_original = (bbox_model - padding) / scale_factor
```

Quyết định:
- CanonicalFrame vẫn 4K
- không global resize frame toàn hệ thống
- YOLO chỉ dùng 640×640 preprocessing

---

# 8. PHASE 10 — PERSON/FACE ASSOCIATION

**PASS**

Kết quả cuối:
- 60/60 association tests
- full regression: 563 passed, 5 skipped, 0 failed
- safety pass

Files chính:
- `app/vision/association.py`
- `app/vision/association_contract.py`
- `app/vision/association_geometry.py`

Provenance được giữ qua association.

Không có:
- camera
- streaming
- identity database
- attendance
- Excel

Phase 10 sau đó đã hoàn thành Task 20 Safety và Task 21 Reports.

---

# 9. PHASE 11 — PERSON/FACE TRACKING

**PASS**

Kết quả:
- 44 Phase 11 tests
- full regression từng đạt 607 passed, 5 skipped
- safety pass

Files:
- `app/vision/track_contract.py`
- `app/vision/tracker.py`
- `tests/unit/test_tracking.py`

Tracking là geometry-only ở phase này.

Quyết định:
- track_id là local theo camera/stream
- cross-camera global identity không dùng chung track_id

---

# 10. PHASE 12 — ARCFACE NORMAL FACE RECOGNITION

**PASS**

Kết quả:
- 63/63 Phase 12 tests
- full regression: 670 passed, 5 skipped

ArcFace contract:
- BGR → RGB
- normalize `[-1,1]`
- `(1,3,112,112)`
- float32
- L2 normalized
- output 512D

Files:
- `app/vision/recognition_contract.py`
- `app/vision/arcface_inference.py`
- `tests/unit/test_arcface_recognition.py`

Không có identity database/matching ở Phase 12.

---

# 11. PHASE 13 — ARCFACE ENROLLMENT DATABASE

**PASS**

Kết quả:
- 67 passed, 3 skipped targeted
- full regression: 737 passed, 8 skipped, 0 failed

Enrollment:
- IMAGE
- VIDEO
- face detection
- crop
- alignment
- ArcFace
- 512D L2-normalized embedding

Database:

```text
embeddings.npy
(N, 512) float32

embeddings.npy.metadata.json
```

Quality filtering:
- face area
- crop size
- confidence
- embedding norm

Duplicate filtering:
- cosine similarity ≥ 0.98

Person grouping:
- multiple embeddings per person_id
- traceability preserved

---

# 12. PHASE 14 — ARCFACE IDENTITY MATCHING

**PASS**

Kết quả:
- 91 targeted tests
- full regression: 828 passed, 8 skipped
- 0 failed

Files:
- `app/vision/matching_contract.py`
- `app/vision/matching.py`
- `tests/unit/test_phase14_matching.py`

Baseline config:
- `match_threshold = 0.5`
- `ambiguity_margin = 0.05`
- `person_aggregation_policy = "best_sample"`

Quyết định:
- matching model-independent
- không inference mới trong Phase 14
- identity matching tách khỏi attendance

Threshold 0.5 là baseline kỹ thuật, **không được coi là production-calibrated** nếu chưa có dữ liệu thật.

---

# 13. PHASE 15 — 1K3D68 HARD-POSE ASSISTED ARCFACE

**PASS**

Kết quả cuối:
- 76 passed
- 0 failed
- 0 skipped
- safety pass

Files chính:
- `app/vision/hardpose_alignment.py`
- `app/vision/hardpose_contract.py`
- `tests/unit/test_phase15_hardpose.py`

Phase 15 đã xử lý:
- NORMAL pose
- HARD_POSE
- INVALID
- pose classification
- 1K3D68 integration
- geometric alignment
- ArcFace compatibility
- Phase 14 compatibility
- provenance
- determinism
- safety

Các lỗi trong quá trình debug đã được sửa đúng:
- similarity transform dùng công thức Umeyama đúng
- provenance propagation từ landmark result
- HardPoseConfig validation cho alignment indices
- safety test chuyển sang kiểm tra import thực tế thay vì keyword trong docstring

**Phase 15 LOCKED / COMPLETE.**

Không quay lại Phase 15 trừ khi phát hiện regression thật.

---

# 14. SCRFD / RETINAFACE QUYẾT ĐỊNH

SCRFD:
- CPU stable
- CUDA không đáng tin do environment
- native 640×640

Không chuyển detector chỉ vì CUDA environment lỗi.

Detector abstraction đã được tạo để sau này có thể A/B test SCRFD vs RetinaFace.

---

# 15. CROP STRATEGY ĐÃ CHỐT

Kiến trúc:

```text
4K ORIGINAL_FRAME
      ↓
YOLO11n 640×640
      ↓
Person bbox
      ↓
restore → 4K
      ↓
Dynamic Person Crop
      ↓
Face Detector
      ↓
Dynamic Face Crop
      ↓
Quality / Pose
      ↓
NORMAL / HARD_POSE
      ↓
1K3D68 nếu HARD_POSE
      ↓
Alignment
      ↓
112×112
      ↓
ArcFace
```

Không làm:

```text
4K → 640 → crop face → 112
```

vì làm mất chi tiết trước crop.

Dynamic crop phải lấy từ ORIGINAL_FRAME hoặc nguồn có phép biến đổi rõ ràng về ORIGINAL_FRAME.

---

# 16. FACE QUALITY ĐÃ CHỐT

Không:

```text
small face → reject person
```

Mà:

```text
GOOD
MARGINAL
UNUSABLE
```

Các metric dự kiến:
- face width/height
- inter-eye distance
- detection confidence
- sharpness
- brightness/exposure
- partial/boundary
- pose
- occlusion

`UNUSABLE` chỉ loại frame khỏi identity evidence.

Person track vẫn tồn tại.

---

# 17. TEMPORAL EVIDENCE ĐÃ CHỐT

Ví dụ:

```text
frame 1 → marginal
frame 2 → good
frame 3 → good
frame 4 → unusable
frame 5 → good
```

Không quyết định identity từ một frame đơn nếu có thể tận dụng track.

Evidence phải bounded:
- finite window
- quality-weighted evidence
- best-quality samples
- configurable K

Không lưu vô hạn embeddings theo track.

---

# 18. HAI CAMERA

## Camera 1

- iPhone main 1×
- 4K
- trong phòng / trên bàn
- hướng về cửa

## Camera 2

- iPhone main 1×
- 4K
- ngoài hành lang
- nhìn khu vực cửa

Hai camera:
- cùng contract
- có thể thay thế nhau
- không cố định role
- mất một camera không làm hệ thống dừng

---

# 19. LIVE MEDIA ARCHITECTURE

Đã chốt:

```text
iPhone
 ↓
RTMP
 ↓
receiver machine
 ↓
RTMP listening port
 ↓
MediaMTX
 ↓
RTSP
 ↓
AI ingest
```

MediaMTX paths:

```text
/cam1
/cam2
```

AI-side ưu tiên đọc RTSP từ MediaMTX.

Media layer phải độc lập với AI layer.

Không để thay camera/source làm thay đổi YOLO/ArcFace/1K3D68/tracking/matching/attendance contracts.

---

# 20. QUYẾT ĐỊNH QUAN TRỌNG: AI TRƯỚC, LIVE SAU

Không tích hợp live quá sớm.

Thứ tự:

```text
Phase 15–21
AI robustness + dual-camera offline reasoning
        ↓
Phase 22–29
IN/OUT + UI + timetable + attendance + output
        ↓
Phase 30
OFFLINE FULL E2E GATE
        ↓
Phase 31–33
LIVE RTMP + MediaMTX + dual-camera
        ↓
Phase 34–35
Realtime + soak
        ↓
Phase 36
Production acceptance
```

Lý do:
- offline replay deterministic
- dễ debug
- nếu live lỗi thì AI đã được khóa
- lúc đó phạm vi lỗi chủ yếu là RTMP/MediaMTX/RTSP/decode/timing
- không debug network + model + attendance cùng lúc

---

# 21. ROADMAP MỚI TỪ PHASE 16

## Phase 16 — Adaptive Person/Face Crop
**NEXT ACTION**

Mục tiêu:

```text
4K ORIGINAL_FRAME
 ↓
YOLO11n 640×640
 ↓
restore bbox → 4K
 ↓
dynamic person crop
 ↓
face detector
 ↓
dynamic face crop
```

Tasks:
1. Crop contract
2. Person bbox restoration
3. Dynamic person crop
4. Face detector input
5. Dynamic face crop
6. Padding policy
7. Small-face handling
8. Boundary cases
9. Multiple people
10. ORIGINAL_FRAME source preservation
11. Determinism
12. Memory safety
13. Phase 15 compatibility
14. Negative tests
15. Targeted tests
16. Safety
17. Final validation/report

Không làm:
- RTMP
- MediaMTX
- RTSP
- live camera
- attendance
- IN/OUT
- timetable
- Excel
- cross-camera association

---

## Phase 17 — Adaptive Face Quality

Quality:
- GOOD
- MARGINAL
- UNUSABLE

Đánh giá:
- face size
- inter-eye distance
- sharpness
- exposure
- confidence
- pose
- boundary/occlusion

Không reject person.

---

## Phase 18 — Temporal Identity Evidence

Dùng track_id.

Bounded evidence.

Quality-aware aggregation.

---

## Phase 19 — ArcFace Database / Matching Calibration

Dùng dữ liệu replay đại diện.

Đo:
- genuine similarity
- impostor similarity
- FAR
- FRR
- TPR
- EER
- UNKNOWN rate
- AMBIGUOUS rate

Calibrate:
- match threshold
- ambiguity margin

Không coi threshold 0.5 là production guarantee.

---

## Phase 20 — Dual-Camera Offline Replay

Dùng video ghi sẵn từ cả hai iPhone.

Test:
- CAM1 replay
- CAM2 replay
- CAM1 + CAM2
- timestamp
- provenance
- local tracks
- global observation
- cross-camera evidence

---

## Phase 21 — Cross-Camera Identity/Observation Fusion

Không đồng nhất local track IDs.

Tạo `global_observation_id`.

Association:
- timestamp
- geometry
- direction
- track continuity
- identity evidence
- provenance

---

## Phase 22 — IN/OUT Geometry UI

UI cho phép:
- vẽ IN line
- vẽ OUT line
- hoặc zones
- kéo/chỉnh
- preview crossing
- lưu theo camera_id
- version

Geometry ở ORIGINAL_FRAME 4K coordinates.

---

## Phase 23 — Raw IN/OUT Event Engine

```text
track
 ↓
crossing
 ↓
direction
 ↓
raw IN/OUT
```

Raw event immutable.

---

## Phase 24 — Repeated IN/OUT Resolution

Xử lý chuỗi:

```text
IN → OUT → IN
OUT → IN → OUT
```

Giữ raw history.

Derived state riêng.

---

## Phase 25 — Timetable / Schedule

UI editable:
- entry time
- exit time
- window
- tolerance
- day/session/class

---

## Phase 26 — Attendance Engine

Identity + global observation + IN/OUT + timetable.

---

## Phase 27 — Annotated Dual-Camera Replay

Hiển thị:
- camera
- person bbox
- track
- global observation
- face
- quality
- pose
- 1K3D68 usage
- identity
- similarity
- IN/OUT
- camera state

---

## Phase 28 — Live UI

Hai camera + health + tracks + identity + quality + pose + attendance.

---

## Phase 29 — Immediate Event Output

Event → identity → IN/OUT → attendance → immediate output.

---

## Phase 30 — Daily Excel

Xuất daily attendance/event report.

---

## Phase 31 — Offline Dual-Camera Full E2E

Gate trước live.

```text
CAM1 replay
CAM2 replay
 ↓
AI
 ↓
cross-camera
 ↓
IN/OUT
 ↓
attendance
 ↓
UI
 ↓
immediate
 ↓
Excel
```

Chỉ khi PASS mới bật live.

---

## Phase 32 — RTMP Receiver + MediaMTX

Live:

```text
iPhone 1 → RTMP → receiver → MediaMTX /cam1 → RTSP → AI
iPhone 2 → RTMP → receiver → MediaMTX /cam2 → RTSP → AI
```

---

## Phase 33 — Live Camera Health / Failover

Test:
- CAM1 loss
- CAM2 loss
- reconnect
- MediaMTX restart
- stream restart
- duplicate workers
- bounded queues

---

## Phase 34 — Live Dual-Camera E2E

Toàn bộ hệ thống live.

---

## Phase 35 — Dual-Camera Realtime Performance

Đo:
- ingest
- decode
- YOLO
- face
- 1K3D68
- ArcFace
- association
- attendance
- output latency
- CPU/GPU/VRAM/RAM
- bandwidth
- queue depth

---

## Phase 36 — Long-Duration Soak

Test:
- stable
- camera loss/recovery
- MediaMTX restart
- AI restart
- network interruption
- both camera restart

Acceptance:
- no memory leak
- no duplicate workers
- no duplicate events
- no track explosion
- no unbounded queue
- no deadlock

---

## Phase 37 — Production Acceptance

Camera:
- 2 iPhones
- 1×
- 4K
- RTMP
- receiver
- MediaMTX
- RTSP
- interchangeability

AI:
- YOLO11n
- dynamic crop
- face detector
- quality
- 1K3D68
- ArcFace
- database
- matching
- temporal evidence

Attendance:
- IN
- OUT
- repeated transitions
- timetable
- attendance
- immediate output
- Excel

Operations:
- reconnect
- restart
- soak
- bounded memory

---

# 22. DEBUG / CLINE RULES

Đã gặp nhiều loop do Cline:

- chạy lại cùng pytest command
- sửa file → test → sửa → test vô hạn
- dùng `python -c` rất dài
- dùng PowerShell/heredoc để rewrite file
- gây `spawn ENAMETOOLONG`

Quy tắc bắt buộc:

```text
ONE ROOT CAUSE
    ↓
ONE TARGETED EDIT
    ↓
ONE TARGETED TEST
    ↓
STOP
```

Không:
```text
PASS → rerun → rerun
```

Không dùng command terminal dài để sửa file.

Dùng editor/direct file operation.

Nếu có nhiều failure:
- gom theo root cause
- sửa từng nhóm
- không sửa hàng loạt

Full regression chỉ chạy một lần sau targeted phase tests sạch.

---

# 23. TEST/SAFETY RULES

Offline AI phases không được:
- mở camera
- MediaMTX
- RTMP
- RTSP
- live FFmpeg
- attendance
- Excel
- persistent worker
- unbounded queue

Live phases mới bật media thật.

Mỗi phase:
1. implement
2. targeted tests
3. safety
4. full regression một lần
5. report
6. lock phase

---

# 24. FILES/REPORTS QUAN TRỌNG ĐÃ TẠO

Các benchmark reports theo phase đã có trong:

```text
benchmark_results/
```

Tên tiêu biểu:

```text
PHASE_7R2_SCRFD_DEEP_DIAGNOSTIC.json
PHASE_7R2_SCRFD_DEEP_DIAGNOSTIC.md
PHASE_7R2_SCRFD_RUNTIME_MATRIX.json

PHASE_8_FACE_DETECTOR_ABSTRACTION.json
PHASE_8_FACE_DETECTOR_ABSTRACTION.md

PHASE_9_YOLO11N_4K_PERSON_DETECTION.json
PHASE_9_YOLO11N_4K_PERSON_DETECTION.md

PHASE_10_PERSON_FACE_ASSOCIATION.json
PHASE_10_PERSON_FACE_ASSOCIATION.md

PHASE_11_PERSON_FACE_TRACKING.json
PHASE_11_PERSON_FACE_TRACKING.md

PHASE_12_ARCFACE_NORMAL_RECOGNITION.json
PHASE_12_ARCFACE_NORMAL_RECOGNITION.md

PHASE_13_ARCFACE_ENROLLMENT_DATABASE.json
PHASE_13_ARCFACE_ENROLLMENT_DATABASE.md

PHASE_14_ARCFACE_IDENTITY_MATCHING.json
PHASE_14_ARCFACE_IDENTITY_MATCHING.md

PHASE_15_HARDPOSE_*.json/md
```

---

# 25. HIỆN TẠI

```text
Phase 1  → COMPLETE
Phase 2  → COMPLETE
Phase 3  → COMPLETE
Phase 4  → COMPLETE
Phase 5  → COMPLETE
Phase 6  → COMPLETE
Phase 7R  → PARTIAL / technical debt documented
Phase 8  → PASS
Phase 9  → PASS
Phase 10 → PASS
Phase 11 → PASS
Phase 12 → PASS
Phase 13 → PASS
Phase 14 → PASS
Phase 15 → PASS / LOCKED

NEXT:
Phase 16 — Adaptive Person/Face Crop
```

---

# 26. PHASE 16 FIRST COMMAND / OBJECTIVE

Phase 16 phải bắt đầu bằng:

```text
TASK 1 — CROP CONTRACT
```

Sau đó:
- person bbox restoration
- dynamic person crop
- face crop
- boundary
- provenance
- ORIGINAL_FRAME proof
- determinism
- memory
- Phase 15 compatibility

Không tự động chuyển Phase 17 sau khi Phase 16 PASS.

---

# 27. HANDOFF INSTRUCTION CHO CONVERSATION MỚI

Conversation mới phải coi file này là **nguồn sự thật chính**.

Prompt mở đầu:

```text
Đọc PROJECT_HANDOFF_PHASE1_TO_CURRENT.md.

Đây là nguồn sự thật của dự án.
Không suy diễn lại các quyết định đã chốt.
Không quay lại các phase đã PASS nếu không có regression evidence.

Trạng thái hiện tại:
Phase 15 = PASS / LOCKED.

NEXT ACTION:
Phase 16 — Adaptive Person/Face Crop.

Thực hiện từng task, chống loop:
one root cause → one edit → one targeted test → STOP.

Không dùng terminal command dài để sửa file.
```

---

# 28. NGUYÊN TẮC CUỐI

Mục tiêu không phải làm thật nhiều model.

Mục tiêu là:

```text
4K source
   ↓
good crop
   ↓
good face
   ↓
good alignment
   ↓
stable embedding
   ↓
temporal evidence
   ↓
cross-camera evidence
   ↓
correct crossing
   ↓
correct IN/OUT
   ↓
correct attendance
   ↓
reliable output
```

Một frame xấu không được biến thành:
- người UNKNOWN vĩnh viễn
- mất track
- mất attendance

Một camera hỏng không được biến thành:
- hệ thống dừng

Một lỗi network không được biến thành:
- lỗi AI không thể phân biệt

Một test pass không được tự động được coi là:
- production accuracy

Production chỉ được chốt sau:
- offline replay
- dual-camera E2E
- live integration
- realtime benchmark
- long-duration soak
- production acceptance


# 29. ARCHITECTURE HARDENING — ADDITIONS TO EXISTING PHASES

## 29.1 Purpose

This section adds architecture-hardening requirements to the existing roadmap without invalidating any phase already marked PASS/LOCKED.

The existing decisions remain authoritative. These additions are intended to make the system more deterministic, auditable, failure-isolated, replayable, and production-ready.

No new numbered phase is inserted. The additions are attached to the phases where they naturally belong.

---

## 29.2 Architecture principles added

The following concepts become first-class architecture contracts:

```text
TIME
+ OBSERVATION
+ PROVENANCE
+ TRANSFORM CHAIN
+ MODEL/CONFIG VERSIONING
+ FAILURE ISOLATION
+ BACKPRESSURE
+ EVIDENCE / DECISION SEPARATION
+ OBSERVABILITY
```

The system must preserve the distinction:

```text
RAW TRUTH
    ↓
OBSERVED TRUTH
    ↓
INFERRED TRUTH
    ↓
DERIVED STATE
```

Examples:

```text
RAW TRUTH
    frame / timestamp / camera / source coordinates

OBSERVED TRUTH
    detection / track / quality / landmarks / embedding evidence

INFERRED TRUTH
    identity hypothesis / global observation / crossing interpretation

DERIVED STATE
    IN / OUT / attendance / schedule result
```

Raw observations/events must not be silently rewritten by later decisions.

---

# 30. UPDATED PHASE DIAGRAM

The roadmap remains the same numbered roadmap, but the architecture contracts are now shown explicitly.

```text
PHASE 1–6
Foundation
    │
    ▼
PHASE 7R
SCRFD diagnostic / technical debt
    │
    ▼
PHASE 8
Detector abstraction
    │
    ▼
PHASE 9
YOLO11n 4K person detection
    │
    ▼
PHASE 10
Person/face association
    │
    ▼
PHASE 11
Local tracking
    │
    ▼
PHASE 12
ArcFace inference
    │
    ▼
PHASE 13
Enrollment database
    │
    ▼
PHASE 14
Identity matching
    │
    ▼
PHASE 15
1K3D68 hard-pose alignment
    │
    │  LOCKED / COMPLETE
    ▼
┌───────────────────────────────────────────────┐
│ PHASE 16 — ADAPTIVE PERSON/FACE CROP          │
│                                               │
│  Crop Contract                                │
│  Transform Chain / provenance foundation      │
│  Original-frame proof                         │
│  Dynamic person crop                          │
│  Dynamic face crop                            │
│  Boundary / padding / small-face handling     │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 17 — ADAPTIVE FACE QUALITY              │
│                                               │
│  GOOD / MARGINAL / UNUSABLE                   │
│  Quality Contract                             │
│  Quality evidence                             │
│  No person rejection because of one bad face  │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 18 — TEMPORAL IDENTITY EVIDENCE         │
│                                               │
│  Time Contract                                │
│  source/capture/monotonic/processing time     │
│  bounded evidence                             │
│  quality-aware aggregation                    │
│  IdentityEvidence → IdentityHypothesis        │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 19 — MATCHING CALIBRATION               │
│                                               │
│  FAR / FRR / TPR / EER                        │
│  UNKNOWN / AMBIGUOUS                          │
│  threshold / ambiguity calibration            │
│  model + config + enrollment version          │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 20 — DUAL-CAMERA OFFLINE REPLAY         │
│                                               │
│  ReplayClock                                  │
│  FramePacket / Observation contracts          │
│  timestamp correctness                        │
│  provenance                                   │
│  CAM1 / CAM2 / combined replay                │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 21 — CROSS-CAMERA FUSION                │
│                                               │
│  LocalTrack ≠ GlobalObservation               │
│  timestamp + geometry + direction             │
│  track continuity + identity evidence         │
│  provenance                                   │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 22 — IN/OUT GEOMETRY UI                │
│                                               │
│  ORIGINAL_FRAME coordinates                   │
│  versioned camera geometry                    │
│  line / zone / preview                        │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 23 — RAW IN/OUT EVENT ENGINE            │
│                                               │
│  crossing → direction → immutable raw event   │
│  Event contract                               │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 24 — REPEATED IN/OUT RESOLUTION         │
│                                               │
│  Attendance state machine                     │
│  raw history preserved                        │
│  derived state separate                       │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
PHASE 25 — TIMETABLE / SCHEDULE
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 26 — ATTENDANCE ENGINE                  │
│                                               │
│  Identity + GlobalObservation + Event         │
│  + timetable → derived attendance state       │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
PHASE 27 — ANNOTATED DUAL-CAMERA REPLAY
                        │
                        ▼
PHASE 28 — LIVE UI
                        │
                        ▼
PHASE 29 — IMMEDIATE EVENT OUTPUT
                        │
                        ▼
PHASE 30 — DAILY EXCEL
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 31 — OFFLINE FULL E2E GATE              │
│                                               │
│  final deterministic offline acceptance       │
│  evidence → decision → attendance → output   │
└───────────────────────┬───────────────────────┘
                        │ PASS ONLY
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 32 — RTMP + MEDIAMTX                   │
│                                               │
│  camera-independent media layer               │
│  no AI contract changes                       │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 33 — LIVE HEALTH / FAILOVER             │
│                                               │
│  per-camera state machine                     │
│  STARTING → HEALTHY → DEGRADED               │
│            → DISCONNECTED → RECONNECTING      │
│  bounded queues / worker isolation            │
│  explicit drop policy                         │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
PHASE 34 — LIVE DUAL-CAMERA E2E
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 35 — REALTIME PERFORMANCE               │
│                                               │
│  stage latency + queue depth + drop count     │
│  CPU/GPU/VRAM/RAM/bandwidth                   │
│  identity / event / output latency            │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 36 — LONG-DURATION SOAK                 │
│                                               │
│  memory leak / deadlock / duplicate workers   │
│  duplicate events / unbounded queues          │
│  restart / reconnect resilience               │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ PHASE 37 — PRODUCTION ACCEPTANCE              │
│                                               │
│  camera + AI + attendance + operations        │
│  provenance + versioning + observability      │
│  replay + realtime + soak                     │
└───────────────────────────────────────────────┘
```

---

# 31. PHASE 16 ADDITIONS — CROP + TRANSFORM CONTRACT

Phase 16 remains the current next action.

Add these requirements to Task 1–17:

## 31.1 Crop Contract

Every crop must explicitly identify:

```text
crop_id
source_frame_id
camera_id
source_coordinate_space
bbox_in_source
crop_width
crop_height
padding_policy
transform_chain
```

The contract must make it impossible to silently treat a model-space crop as an ORIGINAL_FRAME crop.

## 31.2 Transform Chain

Canonical chain:

```text
ORIGINAL_FRAME
    ↓
YOLO_LETTERBOX_640
    ↓
RESTORED_PERSON_BBOX
    ↓
PERSON_CROP
    ↓
FACE_CROP
    ↓
ALIGNMENT
    ↓
ARCFACE_112
```

Each transformation must be deterministic and traceable.

## 31.3 Mandatory proof

Tests must prove:

```text
person crop originates from ORIGINAL_FRAME
face crop originates from ORIGINAL_FRAME or a provenance-preserving derivative
no accidental 640×640 image becomes the final recognition source
```

## 31.4 No overengineering

Do not introduce a new distributed service or database for the crop contract.

A typed in-process contract plus metadata/provenance is sufficient.

---

# 32. PHASE 17 ADDITIONS — QUALITY CONTRACT

Formalize:

```text
GOOD
MARGINAL
UNUSABLE
```

Quality result should carry:

```text
face_size
inter_eye_distance
confidence
sharpness
brightness/exposure
boundary
occlusion
pose
quality_class
```

The rule remains:

```text
UNUSABLE
    ↓
exclude from identity evidence

NOT:
UNUSABLE
    ↓
delete/reject person track
```

Quality must be an evidence filter, not a tracking filter.

---

# 33. PHASE 18 ADDITIONS — TIME + TEMPORAL EVIDENCE CONTRACT

Introduce a canonical time model.

Every observation should distinguish:

```text
source_pts
capture_timestamp
monotonic_timestamp
processing_timestamp
decision_timestamp
```

Offline replay must use an injectable deterministic clock:

```text
ReplayClock
```

Live uses:

```text
LiveClock
```

Do not use processing completion time as the primary cross-camera temporal truth.

Identity flow:

```text
LocalTrack
    ↓
IdentityEvidence[]
    ↓
IdentityHypothesis
    ↓
IdentityDecision
```

Evidence must remain bounded:

```text
finite window
quality weighted
best K samples
configurable K
```

---

# 34. PHASE 19 ADDITIONS — VERSIONED CALIBRATION

Calibration must record:

```text
match_threshold
ambiguity_margin
matcher_version
ArcFace model version
model SHA256
enrollment database version
calibration dataset version
calibration date
```

The result must explicitly state:

```text
production-calibrated
```

only after representative replay data has been evaluated.

The existing `0.5` threshold remains a baseline until this phase produces evidence.

---

# 35. PHASE 20 ADDITIONS — OBSERVATION CONTRACT + REPLAY

Formalize these logical objects:

```text
FramePacket
PersonObservation
IdentityObservation
GlobalObservation
Event
AttendanceState
```

Phase 20 must prove that the same replay input produces deterministic results under the same:

```text
models
configs
enrollment version
clock
input data
```

Replay must never require live RTMP, RTSP, MediaMTX, or camera access.

---

# 36. PHASE 21 ADDITIONS — GLOBAL OBSERVATION

Do not create a global track by simply merging local track IDs.

Canonical relationship:

```text
CAM1 LocalTrack A17
        ├── Observation A17-001
        ├── Observation A17-002
        └── Observation A17-003

CAM2 LocalTrack B04
        ├── Observation B04-001
        └── Observation B04-002

              ↓

       GlobalObservation GO-102
```

Association inputs:

```text
timestamp
geometry
direction
track continuity
identity evidence
camera provenance
```

`GlobalObservation` represents an observed cross-camera occurrence; it is not required to be a permanent global track.

---

# 37. PHASE 22 ADDITIONS — GEOMETRY VERSIONING

Every geometry configuration must contain:

```text
camera_id
coordinate_space = ORIGINAL_FRAME
geometry_version
created_at
line/zone definition
```

Changing a line/zone creates a new version rather than silently rewriting historical interpretation.

---

# 38. PHASE 23 ADDITIONS — EVENT CONTRACT

Canonical flow:

```text
LocalTrack / GlobalObservation
          ↓
       Crossing
          ↓
       Direction
          ↓
   Immutable Raw Event
```

Raw event must contain sufficient provenance to trace back to:

```text
camera
frame/observation
timestamp
geometry version
global observation
identity evidence/decision
```

Raw events are never deleted or rewritten by attendance resolution.

---

# 39. PHASE 24 ADDITIONS — ATTENDANCE STATE MACHINE

Separate:

```text
RawEvent
```

from:

```text
AttendanceState
```

Canonical state:

```text
OUTSIDE
   │
   └── IN ──→ INSIDE
                 │
                 └── OUT ──→ OUTSIDE
```

Repeated/invalid transitions are resolved at the derived-state layer.

Raw history remains immutable.

---

# 40. PHASE 26 ADDITIONS — DECISION VS EVIDENCE

Introduce two logical layers:

```text
EVIDENCE
├── detection
├── crop metadata
├── quality
├── landmarks
├── embedding evidence
├── identity evidence
└── track observations

DECISION
├── identity decision
├── global observation
├── crossing interpretation
├── IN/OUT event
└── attendance state
```

They may live in the same storage system, but their semantics must remain separate.

This makes later forensic replay possible:

```text
Decision
   ↓
Evidence
   ↓
Original Frame
```

---

# 41. PHASE 27–30 ADDITIONS — AUDITABILITY

Annotated replay/UI/output should expose enough information to diagnose:

```text
camera
frame/time
track
global observation
face
quality
pose
1K3D68
identity
similarity
model version
enrollment version
geometry version
IN/OUT
attendance
```

Do not expose every internal tensor by default.

Expose references/metadata first; keep raw heavy artifacts optional.

---

# 42. PHASE 31 ADDITIONS — FINAL OFFLINE GATE

Before live integration, verify:

```text
determinism
provenance
timestamp semantics
identity evidence
cross-camera association
crossing
raw events
attendance
output
```

The gate must prove that a camera-independent offline pipeline is correct before network complexity is introduced.

---

# 43. PHASE 33 ADDITIONS — FAILURE ISOLATION + BACKPRESSURE

Each camera must have an independent lifecycle:

```text
STARTING
   ↓
HEALTHY
   ↓
DEGRADED
   ↓
DISCONNECTED
   ↓
RECONNECTING
   ↓
HEALTHY
```

A camera failure must not terminate the other camera or the global process.

Queues must be bounded.

Define explicit overload behavior.

Recommended priority:

```text
P0  immutable raw events       NEVER DROP
P1  identity evidence          PROTECTED
P2  tracking observations      DROP/DEGRADE when overloaded
P3  visualization frames       DROP FIRST
P4  debug artifacts            DROP FIRST
```

The exact implementation can be decided in Phase 33, but the contract must exist before live E2E.

---

# 44. PHASE 35 ADDITIONS — OBSERVABILITY CONTRACT

Measure at least:

```text
ingest_fps
decode_latency
YOLO_latency
face_latency
1K3D68_latency
ArcFace_latency
association_latency
attendance_latency
output_latency

queue_depth
drop_count
track_count
identity_rate
unknown_rate
ambiguous_rate
cross_camera_match_rate
event_rate

CPU
GPU
VRAM
RAM
bandwidth
```

Per-camera health:

```text
last_frame_time
actual_fps
resolution
reconnect_count
decode_error_count
```

This turns performance testing into repeatable engineering evidence rather than one-off timing.

---

# 45. PHASE 36 ADDITIONS — RESILIENCE

Soak must additionally verify:

```text
camera restart
MediaMTX restart
AI worker restart
network interruption
GPU/runtime error
queue saturation
reconnect storms
```

Acceptance must include:

```text
no duplicate workers
no duplicate raw events
no unbounded queue
no permanent camera degradation
no silent provenance break
no corrupted attendance state
```

---

# 46. PHASE 37 ADDITIONS — PRODUCTION PROVENANCE

Production acceptance must be able to answer:

```text
Which camera produced this observation?
Which original frame produced this crop?
Which model produced this embedding?
Which model/config version produced the identity decision?
Which enrollment version was used?
Which geometry version produced the crossing?
Which raw event produced the attendance state?
```

If these questions cannot be answered, production acceptance is not complete.

---

# 47. MODEL / CONFIG / ENROLLMENT VERSIONING

This is a cross-cutting contract.

Every production identity result must be traceable to:

```text
detector_model_version
pose_model_version
arcface_model_version
matcher_version
config_version
enrollment_version
geometry_version
```

For important model artifacts, retain a content hash such as SHA256.

This is metadata/provenance only; it does not require a microservice architecture.

---

# 48. FAILURE-DOMAIN ARCHITECTURE

The system should conceptually be split into:

```text
GLOBAL CONTROL DOMAIN
│
├── CONFIG
├── MODEL REGISTRY
├── CLOCK
├── OBSERVABILITY
└── OUTPUT

CAMERA DOMAIN 1
│
├── ingest
├── decode
├── YOLO
├── crop
├── face
├── tracking
└── identity evidence

CAMERA DOMAIN 2
│
├── ingest
├── decode
├── YOLO
├── crop
├── face
├── tracking
└── identity evidence

FUSION DOMAIN
│
├── temporal evidence
├── cross-camera association
├── global observation
└── identity decision

EVENT DOMAIN
│
├── geometry
├── crossing
├── raw event
└── attendance state
```

This is a logical architecture, not a requirement for separate processes or services.

---

# 49. WHAT MUST NOT CHANGE

These existing decisions remain LOCKED unless real regression evidence appears:

```text
4K ORIGINAL_FRAME as source of truth
YOLO11n 640×640 preprocessing
SCRFD native 640×640
dynamic crop from original/provenance-preserving source
ArcFace 112×112 → 512D
1K3D68 192×192 for hard pose
local track IDs per camera
global_observation_id for cross-camera reasoning
identity separate from attendance
immutable raw events
geometry in ORIGINAL_FRAME coordinates
offline before live
bounded evidence
bounded queues
camera interchangeability
```

---

# 50. UPDATED FINAL ARCHITECTURE

```text
                    ┌─────────────────────────┐
                    │ CONFIG / MODEL REGISTRY │
                    │ VERSION / CLOCK        │
                    └────────────┬────────────┘
                                 │
                                 ▼

 IPHONE 1 ──→ MEDIA/INGEST ──→ FramePacket ──→ CAMERA DOMAIN 1
 IPHONE 2 ──→ MEDIA/INGEST ──→ FramePacket ──→ CAMERA DOMAIN 2
                                      │
                                      ▼
                              ORIGINAL_FRAME
                                      │
                                      ▼
                                  YOLO11n
                                  640×640
                                      │
                                      ▼
                            RESTORE BBOX → 4K
                                      │
                                      ▼
                              PERSON CROP
                                      │
                                      ▼
                              FACE DETECTOR
                                      │
                                      ▼
                                FACE CROP
                                      │
                                      ▼
                              QUALITY / POSE
                                │         │
                             NORMAL    HARD_POSE
                                │         │
                                │      1K3D68
                                │         │
                                └────┬────┘
                                     ▼
                                  ALIGNMENT
                                     │
                                   112×112
                                     │
                                  ArcFace
                                     │
                                   512D
                                     │
                             IDENTITY EVIDENCE
                                     │
                         ┌───────────┴───────────┐
                         │                       │
                    CAM1 TRACK              CAM2 TRACK
                         │                       │
                         └───────────┬───────────┘
                                     ▼
                           TEMPORAL EVIDENCE
                                     │
                              CROSS-CAMERA
                              ASSOCIATION
                                     │
                           GLOBAL OBSERVATION
                                     │
                            IDENTITY DECISION
                                     │
                             CROSSING ENGINE
                                     │
                           IMMUTABLE RAW EVENT
                                     │
                           ATTENDANCE STATE
                         ┌───────────┼───────────┐
                         ▼           ▼           ▼
                       LIVE UI    IMMEDIATE    EXCEL


        ───────────────── CROSS-CUTTING ─────────────────

        PROVENANCE
        TIME
        MODEL/CONFIG VERSION
        ENROLLMENT VERSION
        GEOMETRY VERSION
        OBSERVABILITY
        HEALTH
        BACKPRESSURE
        FAILURE ISOLATION
        AUDIT / REPLAY
```

---

# 51. FINAL IMPLEMENTATION RULE

The project still follows:

```text
ONE ROOT CAUSE
      ↓
ONE TARGETED EDIT
      ↓
ONE TARGETED TEST
      ↓
STOP
```

Architecture hardening must not become a reason to reopen already locked phases.

The immediate next task remains:

```text
PHASE 16
TASK 1 — CROP CONTRACT
```

The architecture additions above are the baseline to carry forward while implementing the remaining phases.
