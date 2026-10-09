# DSS contract v1 — handoff cho Dương

Contract này chỉ dành cho **daily direction classifier hiện tại**. Bài toán
regression giờ đã chốt riêng tại [hourly_forecast_contract.md](hourly_forecast_contract.md);
không thay nghĩa `probability_up` bằng forecast return/price.

Đây là contract của **bài toán phân loại hướng giá theo ngày** mà code và API
CoinSight hiện dùng. Giữ nguyên ý nghĩa của API `/v1` trong quá trình cải thiện
model. `model_version`/`feature_version` là dấu vết của từng lần huấn luyện,
không phải phiên bản mới của API.

## 1. Câu hỏi cần trả lời

Với một coin `BTC`, `ETH` hoặc `SOL`, sau khi nến Spot `<symbol>USDT` của ngày
UTC `D` đã đóng và vào warehouse: **xác suất giá đóng nến ngày `D+1` cao hơn
giá đóng nến ngày `D` là bao nhiêu?** Giá bằng hoặc thấp hơn là nhãn `0`; cao
hơn là nhãn `1`. `as_of_date = D`, `target_date = D+1`; xác suất trong `[0, 1]`.
Đây không phải giá mục tiêu, tín hiệu mua/bán, hoặc dự đoán từ nến live 1 phút.

## 2. Contract đầu vào: warehouse → DSS

| Nguồn | Khóa/hạt | Điều kiện sử dụng |
| --- | --- | --- |
| `dw.fact_ohlcv_daily` + `dw.dim_asset/date/source` | Coin × ngày UTC × nguồn | Chỉ `source_code='binance'`, nến đã đóng và được batch quality chấp nhận; lấy OHLC, quote volume, `batch_id`. |
| `dw.fact_ohlcv_hourly` | Coin × giờ UTC × nguồn | Dùng 24 nến của **cùng ngày D** để tính `hourly_range`; thiếu giờ thì feature này không hợp lệ. |
| `meta.etl_batch`, `meta.batch_dependency`, `meta.source_file_manifest` | Batch nạp → batch tải → ZIP | Truy nguồn và kiểm chất lượng; không dùng cột của ngày `D+1` làm feature. |

Feature hiện tại trong [feature_builder.py](../pipeline/decision/feature_builder.py):
`return_1d`, `return_7d`, `range_pct`, `volume_change`, `hourly_range`, cùng
`symbol`. `next_close` chỉ tạo **nhãn khi train**, tuyệt đối không đưa vào
feature dự đoán. Một nhãn chỉ hợp lệ nếu ngày kế tiếp trong dữ liệu đúng là
`D+1`; không nhảy qua ngày bị thiếu. Nếu thiếu feature hoặc nến chưa cập nhật,
trả trạng thái thiếu/cũ thay vì tạo xác suất.

## 3. Contract đầu ra: DSS → warehouse

| Bảng/artifact | Ghi khi nào | Ý nghĩa |
| --- | --- | --- |
| `meta.model_evaluation` | Mỗi lần candidate được đánh giá | Ghi train/validation/test rows, Brier của model/baseline, `accepted` hoặc `rejected`. Candidate bị từ chối vẫn có bản ghi để giải thích. |
| `data/models/direction.joblib` + `dw.dim_model` | Chỉ sau khi candidate được chấp nhận | Artifact, `model_version`, `feature_version`, training cutoff, SHA-256 và điểm đánh giá. |
| `dw.fact_direction_prediction` | Chỉ từ model đã chấp nhận, với feature ngày mới nhất hợp lệ | Một coin × `as_of_date` × `target_date` × model; xác suất `[0,1]`; upsert theo khóa này. |
| `meta.prediction_batch_lineage` | Khi ghi prediction | Nối prediction với `load_batch_id` của dữ liệu feature. |

Candidate hiện là logistic regression dùng chung ba coin. Code chia theo thời
gian, giữ 30 ngày cho validation và 30 ngày cuối cho test, bỏ ngày sát ranh
giới để nhãn không nhìn sang kỳ sau. Baseline là tỷ lệ ngày tăng trong phần
train. **Chỉ publish nếu Brier model thấp hơn baseline ở cả validation lẫn
test**; điểm thấp hơn là tốt hơn. Không nới điều kiện này chỉ để UI có số.
Training DAG thử vào thứ Hai; DAG predict chạy hằng ngày lúc 07:30 UTC, sau
batch warehouse dự kiến 06:00 UTC. Nếu ZIP ngày trước chưa sẵn sàng, prediction
có thể thiếu hoặc cũ. Dương có thể thay thuật toán/feature sau khi đánh giá,
nhưng vẫn phải giữ ý nghĩa target, khóa, metadata và API bên dưới.

## 4. Contract API v1: DSS → UI/agent

Các endpoint ở [api.py](../app/api.py), schema ở
[api_schemas.py](../app/api_schemas.py). API **chỉ đọc** kết quả trong DB;
model job chịu trách nhiệm train và ghi. Mọi endpoint trả envelope:
`{status, data, provenance, quality, trace_id}`.

| Endpoint | Khi có dữ liệu | Khi chưa thể dùng |
| --- | --- | --- |
| `GET /v1/model/evaluation` | `status=ready`; `data.decision` là `accepted` hoặc `rejected`, kèm Brier và số dòng train/validation/test. | `status=insufficient_data`, `data=null` nếu chưa từng đánh giá. **`ready` chỉ nghĩa là bản ghi đánh giá tồn tại; không đồng nghĩa model được chấp nhận.** |
| `GET /v1/assets/{symbol}/prediction` | `status=ready`; `data` có `symbol`, `as_of_date`, `target_date`, `probability_up`, `model_version`, `model_brier_score`, `baseline_brier_score`. | `status=insufficient_data`, `data=null` nếu chưa có prediction đã publish; `stale` nếu prediction dùng nến ngày cũ. |
| `GET /v1/assets/{symbol}/prediction/lineage` | `status=ready`; model version, feature version, cutoff, artifact SHA-256, các `load_batches` của prediction mới nhất. | `status=unavailable`, `data=null` nếu không có prediction. |

`provenance.computed_at` là thời điểm ghi kết quả; `provenance.model_version`
là model đã tạo prediction; `quality.warnings` giải thích thiếu/cũ/từ chối.
UI/agent chỉ được hiển thị `probability_up` khi prediction `status=ready` và
`data` có giá trị. Bản đánh giá mới nhất có thể bị `rejected` trong khi một
model cũ đã được chấp nhận vẫn tồn tại; đừng suy ra trạng thái prediction từ
`evaluation.data.decision` mà phải gọi endpoint prediction.

**Trạng thái đang thấy trên dữ liệu thật:** evaluation trả `ready` với
`decision=rejected`, prediction trả `insufficient_data` với `data=null`.
Đó là kết quả kiểm định, không phải lỗi API. Các ví dụ xác suất trong test/demo
là giả lập và không được ghi vào database hoặc dashboard thật.

## 5. Cách Dương thử và bàn giao

```bash
make dss-demo      # dữ liệu tổng hợp, chạy khi Docker đang tắt; không ghi DB/API
make dss-train     # dữ liệu warehouse thật; cần PostgreSQL đang chạy
make dss-predict   # chỉ thành công nếu có artifact đã được chấp nhận
```

Sau khi chạy với dữ liệu thật, đối chiếu `/v1/model/evaluation`,
`/v1/assets/BTC/prediction`, và `/v1/assets/BTC/prediction/lineage` trong
`http://localhost:8000/docs`. Bàn giao gồm: câu hỏi/nhãn giữ đúng contract,
feature không rò dữ liệu tương lai, điểm validation/test so với baseline,
quyết định publish hay abstain, version/checksum, và ít nhất một test cho
trường hợp bị từ chối. Nếu đổi SQL/schema, cập nhật migration và test contract.

**Việc còn cần kiểm tra:** `train()` hiện kiểm tối thiểu 180 ngày trên tập ngày
chung và sự hiện diện của ba coin; chưa bắt buộc mỗi coin có đủ 180 ngày liên
tục. Dương cần kiểm tra độ phủ từng coin trước khi coi dữ liệu train là đạt
contract. Việc lặp lại huấn luyện hằng tuần rồi dùng cùng test period để
quyết định publish có thể khiến test dần trở thành tập chọn model; cần đánh
giá thêm bằng các cửa sổ thời gian kế tiếp trước khi gọi kết quả là đáng tin.
Model và API hiện chỉ hỗ trợ BTC/ETH/SOL, dù warehouse có 20 coin.
