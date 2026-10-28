# Skills

Skill là hướng dẫn cho một loại câu hỏi, agent chỉ đọc khi cần. Mỗi skill là một file
`warehouse_agents/skills/<tên>/SKILL.md`, theo định dạng skill của Anthropic.

## Cách agent dùng skill

```text
system prompt: danh sách skill (tên + description)
      │  câu hỏi khớp một description
      ▼
load_skill(tên) cùng bước với tool đầu tiên   →  đọc SKILL.md
      ▼
gọi tool theo checklist  →  trả lời theo template  →  trích [skill:tên]
```

- Agent chỉ thấy `name` và `description` cho tới khi gọi `load_skill`. Toàn bộ nội dung chỉ vào context khi cần.
- Mỗi câu trả lời load tối đa một skill. Bước chỉ load skill không tính vào giới hạn 6 bước.
- Trích dẫn `[skill:tên]` chỉ hợp lệ nếu skill đó đã được load trong lượt này; trích dẫn khác bị gỡ
  (`skills.validate_citations`).
- Trên UI, trích dẫn hiện thành chip `Skill · <tên việc kiểm tra>`; bấm để đọc nội dung skill. Bốn skill mang tên
  tình huống nên chip đổi sang tên việc kiểm tra, để không bị đọc như một kết luận: `service-unreachable` →
  Service health check, `missing-candles` → Missing-candle check, `model-drift` → Model drift check,
  `warehouse-reconciliation` → Reconciliation check.

Đây không phải RAG: agent chọn skill theo tên trong danh sách, không tìm kiếm hay xếp hạng tài liệu nào. Bảy skill
đủ ngắn để nằm trong prompt. Truy xuất thật dành cho tài liệu lớn hơn: xem [RAG](rag.md).

## Các skill hiện có

| Skill | Dùng khi | Tool chính |
|---|---|---|
| `missing-candles` | Thiếu, trễ hoặc trùng nến giờ | `warehouse_coverage`, `warehouse_status`, `warehouse_lineage` |
| `warehouse-reconciliation` | Số dòng không khớp, mart khác fact, check chất lượng lỗi | `warehouse_reconciliation`, `warehouse_mart_parity`, `warehouse_quality` |
| `model-drift` | **Production-disabled**; file hướng dẫn cũ giữ offline | `model_health` legacy, không advertise |
| `service-unreachable` | Service chậm, lỗi, không truy cập được | `service_health`, `search_traces`, `inspect_trace` |
| `market-brief` | Giá hiện tại, biến động gần đây, độ mới dữ liệu | `market_data` |
| `incident-report` | Báo cáo sự cố, kiểm tra toàn hệ thống | Nhiều tool cùng lúc |
| `forecast-explainer` | Giải thích dự báo daily BTC/ETH và quantile uncertainty | `forecast_support` |

## Cấu trúc một SKILL.md

| Phần | Nội dung |
|---|---|
| Frontmatter | `name` (trùng tên thư mục), `description` 20–400 ký tự: làm gì và khi nào dùng |
| Tool trả về gì | Tên field thật và ý nghĩa, ví dụ `accounting_delta` phải bằng 0 |
| Workflow | Checklist tool cần gọi, gọi chung trong một bước khi độc lập |
| Đọc kết quả | Bảng: quan sát → ý nghĩa → việc operator nên làm |
| Báo cáo | Template với chỗ trống `<field>` |
| Gotchas | Lỗi mà eval đã bắt được |

Mọi skill kết thúc bằng cùng một quy tắc: mọi con số trong câu trả lời phải lấy từ kết quả tool.

## Vì sao không có số ví dụ

Bản v2 của skill có ví dụ như "3 of the last 48 hours are missing for BTC". Model chép các số đó như
thể đã quan sát, và điểm val giảm từ 96,4% xuống 75%. Từ v3, skill chỉ dùng chỗ trống `<missing_hours>`.
Chi tiết ở [Đánh giá agent](evaluation.md#hồi-quy-v2-và-bản-sửa-v3).

## Sửa hoặc thêm skill

1. Sửa `SKILL.md`, giữ dưới khoảng 4 KB: Groq free tier giới hạn 8.000 token/phút, skill dài làm hết quota.
2. Chạy `make eval-test`: loader kiểm tra frontmatter và kích thước.
3. Chạy eval trên train và val (`make eval SPLIT=train`, rồi `SPLIT=val`). Không sửa skill dựa trên lỗi ở test.
4. Restart agent để nạp skill mới: `docker compose --env-file .env -f warehouse_agents/compose.yml up -d --force-recreate`.
