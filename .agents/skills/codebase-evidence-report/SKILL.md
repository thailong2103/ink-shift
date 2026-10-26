---
name: codebase-evidence-report
description: Generates accurate technical reports matching user-provided templates directly from source code AST and runtime call graphs, bypassing high-level ADR/doc bias and enforcing strict line-number evidence locking.
version: 1.0.0
author: Antigravity Engineer
triggers:
  - "viết báo cáo theo template"
  - "generate technical report from code"
  - "audit architecture against spec"
  - "phân tích codebase viết báo cáo"
---

# Codebase Evidence Report Skill

## 1. Context & Purpose
Large Language Models exhibit a strong "Premature Satisficing" bias: when asked to document or report on a codebase, they gravitate toward high-level documentation (`README.md`, `docs/`, `ADR/`, `.spec`) because natural language matches query semantics faster than raw syntax. This produces vague, outdated ("doc-rot") reports.

This skill enforces a **Two-Pass Hybrid Workflow**:
1. **Pass 1 (Code-First Tracing):** Lock out documentation. Construct the system architecture strictly from the AOT AST skeleton and live implementation files.
2. **Pass 2 (Drift Reconciliation):** Unlock documentation exclusively to detect divergence (Architectural Drift) and extract historical trade-off rationales.

---

## 2. Strict Constraints (Guardrails)

1. **Phase 1 Quarantine:** TUYỆT ĐỐI KHÔNG mở, đọc hoặc tham chiếu các file `*.md`, `docs/**`, `adr/**`, `*.txt`, `spec/**` trong suốt quá trình phân tích luồng code ở Pha 1.
2. **Hard Evidence Citation:** Mọi khẳng định về kiến trúc, luồng dữ liệu, thuật toán hoặc xử lý ngoại lệ trong báo cáo BẮT BUỘC phải đính kèm tọa độ nguồn theo định dạng chuẩn:
   `[đường_dẫn_file:dòng_bắt_đầu-dòng_kết_thúc] (hàm/class: tên_thực_thể)`
3. **Anti-Vagueness Rule:** Bị cấm sử dụng các tính từ và mô tả định tính (ví dụ: *"xử lý linh hoạt"*, *"giao tiếp mượt mà"*, *"hiệu năng cao"*). Phải thay thế bằng:
   - Tên giao thức / cơ chế IPC / API endpoint cụ thể.
   - Cấu trúc dữ liệu (Struct, DTO, Class, Schema, Tensor shape).
   - Cơ chế đồng bộ (Mutex, Channel, async/await, Blocking Queue).
4. **Polyglot Boundary Bridging:** Khi luồng thực thi đi qua ranh giới ngôn ngữ hoặc tiến trình (ví dụ: Web UI -> Electron IPC -> FastAPI -> Native C++/DirectML):
   - Không được dừng phân tích tại điểm gọi hàm trung gian.
   - Bắt buộc dùng `grep_search` quét chuỗi định danh kênh (IPC channel name, HTTP route path, socket event name) ở codebase đích để nối liền mạch dữ liệu.

---

## 3. Quy trình Thực thi 4 Pha (Execution Protocol)

### Pha 1: Kiểm tra Bộ khung AOT (Ahead-of-Time Skeleton Check)
1. Kiểm tra sự tồn tại của file `codebase_skeleton.xml` tại thư mục gốc workspace.
2. Nếu file **CHƯA TỒN TẠI**:
   - Sử dụng tool terminal/execute_command để sinh file:
     `npx repomix --config repomix.config.json`
3. Đọc `codebase_skeleton.xml` để nắm toàn bộ sơ đồ thư mục, các interface, kiểu dữ liệu và chữ ký hàm (function signatures). Tuyệt đối không đọc toàn bộ source code vào context cùng lúc.

### Pha 2: Định vị Entry Point & Truy vết Luồng (Call-Graph JIT)
Dựa trên các mục yêu cầu trong `[TEMPLATE]` của người dùng:
1. Xác định file cấu hình hệ thống (`package.json`, `pyproject.toml`, `Cargo.toml`, `pom.xml`, `CMakeLists.txt`) để nắm các dependencies cốt lõi.
2. Tìm điểm nhập thực thi (Entry Points: `main`, `app`, router declarations, CLI commands, IPC handlers).
3. Sử dụng `grep_search` và `read_file` (chỉ đọc dải dòng liên quan, tối đa 100 dòng mỗi lần) để truy vết tối thiểu **3 tầng gọi hàm**:
   - Tầng 1: Entry Handler (Nhận request / Event trigger).
   - Tầng 2: Core Processing / Business Logic / State Mutation.
   - Tầng 3: Engine / Storage / Native Driver / Network IO.

### Pha 3: Điền Template & Khóa Bằng Chứng (Evidence-Locked Drafting)
1. Đọc nội dung file Template mà người dùng chỉ định.
2. Điền từng mục theo đúng định dạng Markdown của Template.
3. Mỗi mục kỹ thuật phải có tối thiểu 2 trích dẫn tọa độ dòng code thực tế chứng minh cho cơ chế đang mô tả.

### Pha 4: Đối chiếu Sai lệch Tài liệu (ADR / Doc Drift Reconciliation)
1. Sau khi đã viết xong bản nháp kỹ thuật từ code thực tế, mở các file tài liệu có sẵn (`docs/`, `ADR/`, `README.md`).
2. Thực hiện phép so sánh vi phân (Diffing) giữa **Ý định thiết kế ban đầu ($State_{doc}$)** và **Hiện trạng triển khai ($State_{code}$)**.
3. Bổ sung một mục chuyên biệt trong báo cáo:
   - **Lý do thiết kế (Design Rationale):** Bổ sung các đánh đổi (trade-offs) mà tài liệu ghi nhận.
   - **Độ lệch kiến trúc (Architectural Drift):** Chỉ rõ các điểm mã nguồn thực tế đã thay đổi so với tài liệu, giải thích nguyên nhân dựa trên logic code (ví dụ: tối ưu bộ nhớ, xử lý race-condition, workaround driver phần cứng).
