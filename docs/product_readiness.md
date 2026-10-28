# Giới hạn & việc còn lại

Trang này giữ backlog và ranh giới của hệ thống, không chép lại hướng dẫn chạy hoặc bảng điểm model. [Evaluation](evaluation.md) giữ kết quả agent; [forecast results](forecasting_result.md) giữ kết quả ML; [home server](home_server.md) giữ quy trình triển khai.

## Những gì đã có implementation

Warehouse với quality/lineage, Kafka/Spark live data, read-only Trade/SRE, trace inspection, skills, numeric grounding, threads và user memory, model picker, prediction ledger, Supabase/Access authentication, usage limits, owner admin console và Paper Trade daily-quantile policy. Legacy per-model drift hiện production-disabled cho tới khi có reference profile đúng daily model.

CI tách dependency của API, serving agents và warehouse/eval. Có replay cassettes để bắt regression mà không gọi provider. Điều này không thay thế live acceptance sau deployment.

## Ưu tiên kiểm chứng

| Ưu tiên | Việc | Bằng chứng cần có |
| --- | --- | --- |
| 1 | RAG trên handbook | Bộ eval truy xuất viết trước; bảng ablation Recall@5 / MRR / độ trễ; trích dẫn mở đúng mục docs; [kế hoạch](rag.md) |
| 2 | Hoàn tất Google/GitHub sign-in | Hai provider hoạt động trên site, đúng user/owner, signed-out chỉ có free quota; [hướng dẫn](auth_setup.md) |
| 3 | Agent evaluation mới | Test cases độc lập cho phiên bản sau v6; val đã dùng để sửa v5 và v6 nên không còn là dữ liệu chưa thấy |
| 4 | Đánh giá scorer | Human labels (`evals/labels/train-v1.csv`), false positives của grounding/refusal, mức agreement |
| 5 | Text-to-SQL | SQL chỉ đọc có giới hạn; benchmark trên fixture warehouse; dùng danh mục kho từ RAG |
| 6 | Nạp đủ 20 coin | Dashboard chỉ hiện coin có dữ liệu; kiểm ETL và freshness từng symbol |
| 7 | Thiết kế lại theo dõi daily model | Ledger đủ mẫu và reference profile đúng daily quantile feature; legacy drift không tự kích hoạt retrain |
| 8 | Home-server acceptance | Migrations, models, data freshness, agents và ledger chạy thật; kiểm restart/restore |
| 9 | Agent orchestration | So một agent với delegation trên cùng cases, latency và cost |

## Giới hạn phải giữ rõ

- Eval hiện tập trung Operations với fixture warehouse; chưa bao phủ đầy đủ live Analyst, market tools và toàn bộ hạ tầng.
- Numeric grounding và citation validation là kiểm tra có giới hạn, không chứng minh mọi câu được nguồn hỗ trợ.
- Forecast chỉ hơn zero-return một mức nhỏ ở test hồi cứu. Anomaly chưa có ground-truth labels.
- Lịch sử chat/memory trong DB không có nghĩa A2A tasks đang chạy có thể tự resume sau restart.
- TLS/tunnel, quota và đăng nhập chưa tự chứng minh backup/restore, SLA, load capacity hoặc security audit đã hoàn tất.
- Daily classifier có gate baseline riêng. Không bỏ gate chỉ để có dự báo trên UI.

## Điều kiện để thêm model hoặc agent

Bắt đầu bằng failure đã đo được, baseline và bộ đánh giá. Chỉ thêm fine-tuning hay một tầng agent khi đo được lợi ích. Pipeline fine-tune seed và benchmark nhỏ không được trình bày thành model production.
