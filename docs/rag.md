# RAG: truy xuất tài liệu (kế hoạch)

Trạng thái: **chưa triển khai**. Trang này là kế hoạch; mỗi bước xong sẽ ghi kết quả đo vào đây.

## Vì sao cần, và vì sao bản cũ không phải RAG thật

Bản đầu (2026-10-21) có tool `search_runbooks`: BM25 trên năm file runbook. Khi runbook chuyển thành
[skills](agent_skills.md), danh sách skill nằm sẵn trong prompt nên không còn gì để tìm; code tìm kiếm đã xóa
(2026-10-24). RAG chỉ đáng làm khi tài liệu quá lớn để nằm trong prompt:

| Nguồn | Kích thước | Làm khi nào |
|---|---|---|
| Handbook này (`docs/*.md`, tiếng Việt) | 42 file, ~42 nghìn từ, ~400 chunk | Bước đầu: "forecast được train thế nào?", "mart parity là gì?" |
| Danh mục kho dữ liệu: bảng, cột, định nghĩa metric, lineage | Sinh từ Postgres | Bước 5; cần cho text-to-SQL |
| Các lần điều tra trước được đánh giá tốt (`meta.agent_run`) | Tăng theo thời gian | Sau |

## Thiết kế

```text
docs/*.md ──chia theo heading──► meta.rag_chunk (Postgres + pgvector)
                                  text, ngữ cảnh, nguồn#mục, ngôn ngữ, sha, embedding
                                          │
câu hỏi ─► search_docs(query, k) ─► từ khóa (Postgres full-text) ┐
                                    vector (pgvector)            ├► RRF ─► (rerank?) ─► 5 chunk
                                                                 ┘
agent trả lời ─► trích [doc:evaluation#...] ─► guard gỡ trích dẫn không có trong kết quả tìm
UI ─► chip nguồn giống skill, mở đúng mục trên trang docs
```

| Kỹ thuật | Làm gì | Lý do |
|---|---|---|
| Chunk theo cấu trúc | Chia theo heading; mỗi chunk mang đường dẫn mục (IV.1.2 › …) và URL tới mục đó | Khớp tốt hơn; trích dẫn mở đúng chỗ trên trang docs Cloudflare (slug heading tạo bằng `github-slugger` như trang docs) |
| Hybrid + RRF | Gộp kết quả từ khóa và vector | Bắt được tên chính xác (`mart_parity`, PSI) lẫn câu diễn đạt khác |
| Contextual retrieval | Trước khi index, một LLM viết 1–2 câu đặt chunk vào ngữ cảnh tài liệu; câu này được index cùng | Anthropic (2024) báo giảm 49% lần tìm trượt khi dùng với hybrid, 67% khi thêm rerank. ~400 chunk: dưới 1 USD trên Haiku hoặc miễn phí với model chạy trên Mac |
| Embedding đa ngôn ngữ | Ứng viên: Qwen3-Embedding-0.6B, bge-m3 (hoặc bản tinh chỉnh tiếng Việt), multilingual-e5 | Câu hỏi tiếng Anh, tài liệu tiếng Việt: khớp chéo ngôn ngữ là phần khó |
| Reranker cross-encoder | Ứng viên: Qwen3-Reranker-0.6B, bge-reranker-v2-m3; chấm lại 20 kết quả đầu | Thường tăng độ chính xác nhiều nhất; giữ lại nếu eval cho thấy đáng độ trễ |
| Agent tự tìm | Agent viết truy vấn, có thể tìm lại, có thể tìm bằng tiếng Việt | Rẻ, sửa lỗi lệch ngôn ngữ |
| Trích dẫn có kiểm tra | Chỉ trích chunk đã tìm thấy; điểm khớp thấp thì nói "không có trong tài liệu" | Không bịa tài liệu |

Không làm: GraphRAG, RAPTOR, index kiểu ColBERT. Chúng có lợi với kho tài liệu lớn, không phải 400 chunk.

## Chạy ở đâu

| Máy | Việc |
|---|---|
| MacBook (Apple M4, 16 GB) | Thử nghiệm, benchmark, tạo index và contextual text |
| Laptop ở nhà (Ryzen 5 3500U, không GPU) | Phục vụ: embed câu hỏi, tìm, có thể rerank. Model lúc truy vấn phải nhỏ (~0,6B) |

Không cần GPU. Index ~2 MB vector, nạp vào Postgres trên laptop; chỉ chunk có sha đổi mới được tính lại.

## Docs đổi thì index đổi theo

Handbook sửa thường xuyên, nên index phải tự cập nhật, và chỉ làm lại phần đổi:

```text
merge vào main ─► deploy.sh trên laptop kéo code mới
                 └─► docs/ có đổi? ─► rag-index
                        cắt lại thành chunk, id = <trang>#<slug heading>, sha = hash nội dung
                        sha không đổi  → bỏ qua (không gọi LLM, không embed lại)
                        sha mới / đổi  → viết lại câu ngữ cảnh, embed, upsert
                        id không còn   → xóa khỏi meta.rag_chunk
```

- Sửa một đoạn chỉ tốn vài lượt gọi model, không phải 400.
- Câu ngữ cảnh viết theo cả trang, nên khi tiêu đề hay vị trí của trang đổi, mọi chunk của trang đó được làm lại.
- Đổi model embedding thì index lại toàn bộ; phiên bản model lưu cùng mỗi chunk để không trộn vector của hai model.
- Bộ eval ghi đáp án bằng id `<trang>#<slug>`. CI kiểm tra mọi id trong bộ eval vẫn tồn tại; đổi tên heading mà
  quên sửa bộ eval thì CI báo lỗi, thay vì điểm âm thầm tụt.
- Trang docs trên Cloudflare deploy riêng (workflow `deploy-docs.yml`) từ cùng commit, nên link trích dẫn và nội
  dung index luôn cùng phiên bản.

## Các bước (eval trước, như agent)

| Bước | Việc | Xong khi |
|---|---|---|
| 0. Bộ eval | ~60 câu hỏi Anh/Việt (có câu chéo ngôn ngữ), mỗi câu gắn chunk đúng; chia train/val/test; thêm câu không có trong tài liệu | Commit trước khi có code tìm kiếm |
| 1. Index + từ khóa | Image `pgvector/pgvector:pg16`, bảng `meta.rag_chunk`, chunker theo heading, full-text | Có Recall@5 của tìm theo từ khóa |
| 2. Vector + hybrid | Embed bằng các ứng viên; hybrid RRF; contextual; rerank bật/tắt | Bảng Recall@5 / MRR / độ trễ p95 cho từng cấu hình, chọn trên val |
| 3. Tool cho agent | `search_docs` cho hai agent; trích dẫn `[doc:...]`; gỡ trích dẫn không có nguồn; ngưỡng "không có trong tài liệu"; case tài liệu bị chèn lệnh | Case end-to-end mới đạt, case cũ không tụt (Haiku và Groq) |
| 4. UI + admin | Chip nguồn mở đoạn văn và link mục docs; admin xem các lần tìm (query đã hash, kết quả, độ trễ) | Thấy trên bản preview |
| 5. Danh mục kho | Index schema và định nghĩa metric | Dùng cho text-to-SQL |

Metric: Recall@5, MRR@10 cho truy xuất; tỉ lệ trích dẫn đúng nguồn và tỉ lệ nói "không có" đúng lúc cho câu trả lời;
độ trễ p50/p95 trên laptop.
