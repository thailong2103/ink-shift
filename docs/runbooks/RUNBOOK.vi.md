# Sổ Tay Vận Hành: Kiểm Thử Trực Tiếp Local Engine Với Tiện Ích Chrome

> **Mô-đun mục tiêu:** Mô-đun 5 (`local-engine`) & Mô-đun 4 (`extension-core`)  
> **Môi trường thử nghiệm:** Windows 10/11 (GPU DirectML hoặc CPU Fallback)  
> **Trạng thái:** Sẵn sàng kiểm thử và nghiệm thu  

---

## 1. Danh Sách Kiểm Tra Tiền Điều Kiện

Đảm bảo các thành phần nền tảng đã sẵn sàng trước khi chạy:

1. **Trọng số mô hình nhận diện (Model Weights):**
   - Vị trí tệp: `.cache/inkshift/models/yolo11s-seg.onnx` (~25 MB).
   - **Tự động tải:** Máy chủ backend tự động tải tệp từ Hugging Face khi khởi động nếu bật `INKSHIFT_AUTO_DOWNLOAD_MODELS=true`.
   - Hoặc tải thủ công trước qua lệnh:
     ```powershell
     python scripts/download_models.py
     ```
2. **Các gói thư viện Python:**
   - Đảm bảo các gói `onnxruntime-directml`, `rapidocr-onnxruntime`, `fastapi`, `httpx` đã được cài đặt trong môi trường ảo.
3. **Bản dựng tiện ích mở rộng (Extension Bundle):**
   - Thư mục `dist/` đã được biên dịch hoàn chỉnh qua lệnh:
     ```powershell
     npm run build:extension
     ```

---

## 2. Quy Trình Vận Hành & Kiểm Thử Chi Tiết

### Bước 1: Khởi Động Máy Chủ Backend

Bạn có thể khởi động theo 1 trong 2 cách:

**Cách A: Khởi động 1 click trên Windows (Khuyên dùng)**
Nhấp đúp chuột vào tệp `start.bat` tại thư mục gốc của dự án.

**Cách B: Khởi động thủ công bằng dòng lệnh**
Mở cửa sổ PowerShell hoặc Terminal tại thư mục dự án và chạy:

```powershell
python -m uvicorn src.backend.app:app --host 127.0.0.1 --port 8000 --reload
```

**Dấu hiệu khởi động thành công trong Terminal:**
```text
==================================================
InkShift Backend Gateway is ready
Default Engine: mock (hoặc local / cloud)
Database Path:  ./data/cache.db
==================================================
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

### Bước 2: Nạp Tiện Ích Vào Trình Duyệt Chromium

1. Mở trình duyệt Google Chrome, Microsoft Edge, hoặc Brave.
2. Truy cập thanh địa chỉ: `chrome://extensions/`.
3. Bật công tắc **Chế độ dành cho nhà phát triển (Developer mode)** ở góc trên bên phải.
4. Bấm nút **Tải tiện ích đã giải nén (Load unpacked)** ở góc trên bên trái.
5. Chọn thư mục bản dựng:
   ```text
   c:\Vide_coding\ink-shift\dist
   ```
6. **Lưu ý quan trọng khi thử nghiệm tệp cục bộ (`file:///`):**
   - Trên thẻ tiện ích **InkShift**, bấm vào **Chi tiết (Details)**.
   - Kéo xuống tìm mục **Cho phép truy cập vào các URL của tệp (Allow access to file URLs)** và **BẬT** công tắc này lên.

---

### Bước 3: Mở Trang Đọc Truyện Thử Nghiệm

Bạn có thể kiểm thử theo một trong hai cách:

#### Cách A: Thử nghiệm Offline (Không cần kết nối mạng)
Kéo thả tệp sau vào trình duyệt Chrome hoặc nhập đường dẫn:
```text
file:///c:/Vide_coding/ink-shift/tests/fixtures/manga_test_page.html
```

#### Cách B: Thử nghiệm trực tiếp trên web truyện (MangaDex, v.v.)
Mở bất kỳ chương truyện tranh nào trên các trang đọc manga trực tuyến (ví dụ: [MangaDex](https://mangadex.org)).

---

### Bước 4: Thao Tác Dịch Trên Giao Diện Tiện Ích & Linh Vật HUD

1. Bấm vào biểu tượng tiện ích **InkShift** trên thanh công cụ (nên ghim tiện ích để tiện sử dụng).
2. Kiểm tra huy hiệu trạng thái:
   - Phải hiển thị màu xanh lá: **Online**.
3. Tại ô **Translation Engine**, bạn có thể chọn:
   - `Auto (Default)`: Tự động dùng engine theo cấu hình máy chủ.
   - `Local DirectML (On-Device)`: Chạy hoàn toàn trên máy bằng GPU. Menu **Text Translator** sẽ cho phép bạn chọn:
     - `Google Translate (Free $0)` (Mặc định)
     - `LLM Text (OpenAI / DeepSeek / Ollama)`
   - `Cloud AI (Multi-Provider)`: Dùng LLM Vision với cơ chế Set-of-Marks. Cho phép chọn nhà cung cấp:
     - `Google Gemini (Default)`
     - `OpenAI / Tương thích OpenAI`
4. Bấm nút **Quét và dịch lại trang này (Re-scan Current Page)**.

---

### Bước 4.1: Bảng Phím Tắt Khi Đọc Truyện

Khi đang đọc truyện trên tab trình duyệt:
- **`Alt + Z`**: Bật / tắt nhanh hiển thị lớp phủ dịch thời gian thực. Khi tắt, linh vật chuyển sang trạng thái ngủ (`sleeping`).
- **`Alt + M`**: Ẩn / hiện linh vật đồng hành Mascot HUD.
- **Cơ chế chống gõ nhầm (Typing Guard)**: Phím tắt tự động vô hiệu hóa khi con trỏ chuột nằm trong các ô `<input>`, `<textarea>`, `contenteditable` hoặc khi bộ gõ tiếng Việt đang soạn dấu.
- **Thứ tự hiển thị lớp (Z-Index Layering)**: Linh vật HUD được ghim ở `z-index: 2147483647` (cao nhất), các bóng thoại dịch ở `z-index: 2147483640` để đảm bảo giao diện luôn hiển thị rõ ràng, không bị che khuất.

---

### Bước 5: Kiểm Tra Xác Thực Hoạt Động

Quan sát terminal backend và giao diện trang đọc để nghiệm thu:

1. **Terminal Backend & Tệp Nhật Ký (`data/logs/inkshift.log`):**
   - Hệ thống ghi nhận thời gian từng giai đoạn với độ chính xác mili-giây:
     ```text
     RequestReceived: engine=local, target=vi, size_kb=2463.3
     StageStarted: stage=1/4, action="DecodeImageAndValidate"
     StageCompleted: stage=1/4, elapsed_ms=63.6
     StageStarted: stage=3/4, action="OCRRecognition (mode=en)"
     RapidOCR full-page completed: 29 text elements mapped to 7 bubbles in 1354.41ms (valid=6/7)
     StageStarted: stage=4/4, action="BatchTranslate (6 blocks -> vi via google-free)"
     StageCompleted: stage=4/4, elapsed_ms=3905.0
     PipelineCompleted: engine=local, elapsed_ms=5348, blocks=6
     ```
   - Chế độ `local` (Non-JA): RapidOCR tự động quét một lượt toàn trang mà không cần cắt từng ô nhỏ.
   - Chế độ `cloud`: Cơ chế trực quan vẽ Set-of-Marks và tự động thử lại khi gặp lỗi HTTP 429/503.

2. **Nhật Ký Tiện Ích Trình Duyệt (`data/logs/extension.log`):**
   - Mở tệp nhật ký để theo dõi tiến trình tải trước ngầm:
     ```text
     [INFO] [inkshift.extension.prefetch] Starting prefetch for page #18 (P1, provider: google-free)
     [INFO] [inkshift.extension.prefetch] Page #18 ready in prefetch cache (6 blocks, cache)
     [INFO] [inkshift.extension.cs] Mounted overlay from prefetch cache (page_number) for image #2 (page #18, 6 blocks)
     ```
   - Khi lật sang trang tiếp theo, lớp phủ **Shadow DOM** gắn tức thì (0ms) từ bộ nhớ đệm tải trước.
   - Cỡ chữ tự động co giãn vừa khít bóng thoại trong vùng an toàn (Safe-zone).

---

## 3. Bảng Khắc Phục Sự Cố Thường Gặp

| Tình trạng | Nguyên nhân có thể | Cách giải quyết |
|---|---|---|
| Huy hiệu hiển thị **Offline** | Máy chủ backend chưa chạy hoặc bị chặn cổng 8000 | Chạy lại lệnh uvicorn hoặc `start.bat`. Đảm bảo địa chỉ `http://127.0.0.1:8000/api/v1/cache/stats` mở được trên trình duyệt. |
| Không quét được ảnh trên `file:///` | Chưa bật quyền truy cập tệp cục bộ | Vào `chrome://extensions/` -> Chi tiết InkShift -> Bật **Cho phép truy cập vào các URL của tệp**. |
| Lỗi thiếu trọng số mô hình | Tệp `yolo11s-seg.onnx` chưa được tải đủ | Chạy lệnh `python scripts/download_models.py --force`. |
| Giao diện tiện ích không cập nhật | Trình duyệt đang lưu đệm bản dựng cũ | Bấm nút mũi tên xoay tròn **Tải lại (Reload)** trên thẻ InkShift trong `chrome://extensions/`. |
