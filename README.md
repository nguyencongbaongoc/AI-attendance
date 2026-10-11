# AI Attendance System (Architecture A)

Hệ thống điểm danh AI thời gian thực hai luồng camera độ phân giải cao trên phần cứng tối ưu hóa (NVIDIA GeForce GTX 1660 Ti 6GB VRAM, Windows 11).

---

## 📋 Yêu cầu Môi trường & Phần cứng
- **Hệ điều hành:** Windows 11 (64-bit)
- **GPU:** NVIDIA GeForce GTX 1660 Ti 6GB VRAM (Compute Capability 7.5 - Turing)
- **NVIDIA Driver:** >= 550.xx
- **CUDA Toolkit:** 12.x hoặc 11.8
- **cuDNN:** >= 8.9.x
- **TensorRT:** 11.x (biên dịch engine FP16/TF32 cục bộ)
- **Python:** 3.10 hoặc 3.11 (khuyến nghị Python 3.10)
- **Công cụ phụ trợ:** MediaMTX (RTSP/WebRTC Relay), FFmpeg (trong PATH hệ thống)

---

## 🚀 Hướng dẫn Cài đặt & Khởi tạo Môi trường (.venv)

Chạy các lệnh terminal sau trong PowerShell để thiết lập môi trường từ file ghim sẵn:

### Bước 1: Khởi tạo Virtual Environment
```powershell
# 1. Tạo môi trường ảo Python
python -m venv .venv

# 2. Cho phép chạy script (nếu bị chặn ExecutionPolicy)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force

# 3. Kích hoạt môi trường ảo
.\.venv\Scripts\Activate.ps1
```

### Bước 2: Cài đặt PyTorch hỗ trợ GPU CUDA
```powershell
# Cài đặt PyTorch tương thích CUDA (ví dụ CUDA 12.1)
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### Bước 3: Cài đặt các thư viện từ requirements.txt
```powershell
pip install -r requirements.txt
```

### Bước 4: Cài đặt gói giải mã phần cứng NVIDIA (tùy chọn theo phần cứng)
```powershell
# Cài đặt PyNvVideoCodec nếu sử dụng NVDEC backend
pip install pynvvideocodec
```

### Bước 2.5: Cài đặt & Khởi động Giao diện Web (Frontend / Web UI)

Nếu giao diện Web UI sử dụng môi trường Node.js / NPM (chạy trên cổng `3000`):

```powershell
# 1. Điều hướng vào thư mục UI (nếu mã nguồn UI tách riêng)
cd ui   # Bỏ qua nếu package.json nằm ngay thư mục gốc

# 2. Cài đặt toàn bộ thư viện Frontend
npm install

# 3. Khởi chạy giao diện chế độ Development (Port 3000)
npm run dev

# (Tùy chọn) Đóng gói bản chạy Production tĩnh
npm run build
```

**Trường hợp UI là HTML/JS tĩnh (UI/index.html thuần Canvas):**
Không cần `npm install`. Giao diện được phục vụ trực tiếp qua FastAPI StaticFiles hoặc mở trực tiếp trên trình duyệt tại `http://localhost:8000` / `http://localhost:3000`.

---

## 📦 Danh mục Công cụ Ngoại vi & Link tải Trực tiếp

Hệ thống yêu cầu các thành phần runtime ngoại vi sau trên Windows 11. Bạn có thể cài đặt tự động bằng một dòng lệnh `winget` hoặc tải thủ công từ link chính thức:

### 1. Cài đặt tự động bằng Winget (Khuyến nghị - Nhanh nhất)

Mở PowerShell (Run as Administrator) và chạy:

```powershell
# Cài đặt Node.js LTS, Git và FFmpeg tự động
winget install OpenJS.NodeJS.LTS --silent
winget install Gyan.FFmpeg --silent
winget install Git.Git --silent
```

### 2. Bảng Link tải Thủ công Chính thức

| Thành phần | Phiên bản khuyến nghị | Link tải chính thức | Ghi chú cấu hình |
|---|---|---|---|
| **Node.js & npm** | v20.x hoặc v22.x LTS | [Node.js Official Download](https://nodejs.org/en/download/) | Kiểm tra bằng: `node -v` và `npm -v` |
| **MediaMTX** | v1.9.x+ (Windows amd64) | [MediaMTX GitHub Releases](https://github.com/bluenviron/mediamtx/releases) | Giải nén `mediamtx.exe` vào thư mục `mediamtx/` (đã có trong .gitignore) |
| **FFmpeg** | Latest Release Essentials | [Gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) hoặc [FFmpeg.org](https://ffmpeg.org/download.html) | Giải nén và thêm thư mục `bin/` vào biến môi trường PATH |
| **NVIDIA Driver** | >= 550.xx Game Ready / Studio | [NVIDIA Driver Downloads](https://www.nvidia.com/Download/index.aspx) | Cần thiết để hỗ trợ CUDA 12.x và NVDEC trên GTX 1660 Ti |
| **CUDA Toolkit** | CUDA 12.1 hoặc 12.4 | [NVIDIA CUDA Toolkit Archive](https://developer.nvidia.com/cuda-toolkit-archive) | Cài đặt bản network/local installer |
| **cuDNN** | cuDNN 9.x for CUDA 12 | [NVIDIA cuDNN Downloads](https://developer.nvidia.com/cudnn-downloads) | Copy các file `bin/`, `include/`, `lib/` vào thư mục CUDA Toolkit |
| **TensorRT** | TensorRT 10.x hoặc 11.x ZIP | [NVIDIA TensorRT Download](https://developer.nvidia.com/tensorrt) | Giải nén vào thư mục gốc hoặc cấu hình biến môi trường PATH tới `TensorRT/lib` |

---

## 🔍 Kiểm tra Toàn bộ Môi trường trước khi Chạy

Mở một cửa sổ PowerShell mới và kiểm tra nhanh:

```powershell
node -v          # Phải trả về v20.x hoặc v22.x
npm -v           # Phải trả về >= 10.x
ffmpeg -version  # Phải nhận diện FFmpeg build
nvidia-smi       # Phải hiển thị GTX 1660 Ti và phiên bản Driver/CUDA
python -V        # Phải trả về Python 3.10.x hoặc 3.11.x
```

Sau khi hoàn tất, chạy lệnh duy nhất để khởi động toàn bộ hệ sinh thái:

```powershell
.\bootstrap.bat
```

## ⚙️ Cấu hình Biến Môi trường (.env)
Tạo file `.env` tại thư mục gốc từ mẫu:

```
# MediaMTX & Streaming
MEDIAMTX_API_URL=http://127.0.0.1:9997
CAMERA_1_RTSP=rtsp://127.0.0.1:8554/live/cam1
CAMERA_2_RTSP=rtsp://127.0.0.1:8554/live/cam2

# Notification Providers (Sandbox Mode)
NOTIFICATION_SANDBOX=true
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
ZALO_ZNS_APP_ID=your_app_id
ZALO_ZNS_SECRET=your_secret
ESMS_API_KEY=your_esms_key
ESMS_SECRET_KEY=your_esms_secret
```

## 🎬 Khởi động Toàn bộ Hệ thống (One-Click Bootstrap)
Hệ thống tích hợp giám sát tự động MediaMTX, Uvicorn Backend, AI Worker, Storage Watchdog và Web UI qua một lệnh duy nhất:

```powershell
.\bootstrap.bat
```

- **Web UI:** http://localhost:3000 (Canvas Overlay hiển thị thời gian thực)
- **API Docs:** http://localhost:8000/docs
- **MediaMTX Console:** http://localhost:9997

## 🏗️ Kiến trúc Hệ thống (Architecture A)
- **Zero Re-encoding:** MediaMTX relay video gốc không transcode; AI Worker phát metadata qua WebSocket để vẽ Canvas Overlay trên trình duyệt.
- **Shared Singleton TensorRT:** Một instance động dùng chung cho 2 camera (YOLO11n, SCRFD, ArcFace, ReID), VRAM tiêu thụ < 2.0 GB.
- **Evidence Lifecycle:** fMP4 NVR recording liên tục, crop ảnh bằng chứng GPU bất đồng bộ, cắt clip ngắn bằng ffmpeg -c copy.
- **Thông báo Đa tầng:** Zalo ZNS -> SMS Brandname -> Telegram kèm bộ lọc chống spam cooldown.

---

## 🧠 Quản lý Mô hình AI & Biên dịch TensorRT Engine

Do các tệp mô hình biên dịch (`.engine`) phụ thuộc chặt chẽ vào kiến trúc GPU cục bộ (GTX 1660 Ti Turing `SM 7.5`), hệ thống cung cấp script để tải và tự động biên dịch lại trên máy của bạn.

### Danh mục 4 Mô hình Cốt lõi:
| Mô hình | Nhiệm vụ | Đầu vào | Định dạng đích |
|---|---|---|---|
| **YOLO11n** | Phát hiện người & hộp bounding box | 640x640 RGB | `yolo11n_fp16.engine` |
| **SCRFD (1k3d68)** | Phát hiện khuôn mặt & 5 điểm mốc landmarks | Dynamic / 640x640 | `1k3d68_fp16.engine` |
| **ArcFace (GlintR100)** | Trích xuất vector đặc trưng 512 chiều | 112x112 Aligned RGB | `glintr100_fp16.engine` |
| **ResNet-50 ReID** | Định danh ngoại hình người (Re-Identification) | 256x128 RGB | `resnet50_reid_fp16.engine` |

### Các bước chuẩn bị mô hình:

```powershell
# 1. Khởi tạo cấu trúc thư mục mô hình
python tools/download_models.py

# 2. Đặt các tệp ONNX tương ứng vào thư mục models/:
#    - models/yolo/yolo11n.onnx
#    - models/landmark/1k3d68.onnx
#    - models/arcface/glintr100.onnx
#    - models/reid/resnet50_reid.onnx

# 3. Chạy script tự động biên dịch FP16 TensorRT Engines cho GPU của bạn:
python tools/build_engines.py
```
*(Yêu cầu biến môi trường PATH đã bao gồm thư mục bin của TensorRT chứa trtexec.exe)*