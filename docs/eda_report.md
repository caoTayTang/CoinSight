# EDA chạy lại từ warehouse

[Mở báo cáo HTML tương tác](/reports/eda.html).

File: `frontend/public/reports/eda.html`. Mở trực tiếp được khi offline. Bản hiện tại
đọc dữ liệu từ PostgreSQL local, **không còn lấy output notebook của người khác**.
Notebook `research/eda.ipynb` được giữ nguyên để tham khảo.

## 1. Dữ liệu đang dùng là gì?

- Nguồn: archive nến Binance Spot, cặp với USDT.
- Coin: BTC, ETH, SOL, ADA, DOGE, SHIB.
- Độ dài nến: một ngày UTC; không phải feed live một phút hay dataset dự báo giờ.
- Lần chạy local: 2024-01-01 đến hết 2026-10-17, 1.021 nến/coin, tổng 6.126 nến.
- Có OHLC, quote volume USDT, load/extract batch và thông tin archive nếu fact đã có lineage.
- OHLC/return chỉ biết khi nến đóng; ngày trên dòng dữ liệu là ngày mở nến.

Chọn 2024 để bắt đầu với gần ba năm và một khoảng chung cho sáu coin. Đây là quyết
định giới hạn phạm vi để học và kiểm chứng, **không phải khẳng định 2024 là điểm train
model tối ưu** hoặc dữ liệu trước đó vô ích. Muốn kết luận ổn định qua nhiều chế độ
thị trường thì cần thử thêm các giai đoạn cũ, không chọn phạm vi vì metric đẹp hơn.

## 2. Báo cáo trả lời câu hỏi gì?

Mỗi kết luận có bằng chứng số, ý nghĩa và hành động tiếp theo:

1. **Dữ liệu có đủ không?** Đếm thiếu trên toàn khoảng yêu cầu, kiểm OHLC/volume/trùng,
   không chỉ nhìn nến đầu/cuối. Hiển thị cả fact chưa có checksum nguồn.
2. **Rủi ro có ổn định theo thời gian không?** Return, drawdown, biến động và thống kê
   từng năm; năm đầu/cuối được ghi rõ số mẫu và ngày thực tế.
3. **Các coin có thật sự đa dạng hóa?** Correlation trên cùng timestamp return cho
   mọi cặp, cộng correlation trượt để thấy thay đổi qua thời gian.
4. **Hướng kỳ trước có giúp dự báo kỳ sau?** Một quy tắc momentum cố định, so baseline
   chọn trên train; chỉ đánh giá trên phần giữ riêng theo thời gian.
5. **Nếu hướng khó đoán, có thể mô tả rủi ro tốt hơn không?** So |return kế tiếp| sau
   trạng thái biến động cao/thấp, dùng feature quá khứ và ngưỡng chỉ tính trên train.
6. **Dữ liệu nhìn thực tế ra sao?** Candlestick OHLC thật từ DB, không dựng từ chỉ số giá.

## 3. Chạy lại trên DB hiện tại

```bash
docker compose up -d postgres
docker compose run --rm migrate
make eda
open frontend/public/reports/eda.html
```

`make eda` dùng URL PostgreSQL host từ Makefile, mặc định localhost. Lệnh chỉ SELECT,
không train model, không tải dữ liệu và không thay đổi warehouse.

Đổi phạm vi rõ ràng:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with-requirements scripts/requirements-eda.txt \
  python -m scripts.run_eda --start 2024-01-01 --end 2026-10-18 \
  --symbols BTC,ETH,SOL,ADA,DOGE,SHIB --interval 1d
```

`--end` là mốc exclusive UTC. Không truyền thì lấy đầu ngày UTC hiện tại để loại nến
chưa đóng. Không dùng một ngày tương lai. Có hỗ trợ `--interval 1h`, nhưng cần backfill
giờ riêng; chỉ đổi tham số không tự tạo dữ liệu giờ.

Script dừng nếu thiếu dưới 60 nến chung/return liên tiếp chung, có trùng khóa hoặc
OHLC/volume không hợp lệ. Không âm thầm dùng lại output notebook.

## 4. Nếu cần backfill

Bước này **thực sự tải và ghi DB**, tách riêng khỏi EDA:

```bash
make eda-backfill
```

Mặc định chỉ sáu coin trên, nến ngày, từ 2024-01. Script
`scripts/backfill_eda.py` dùng downloader/cache và loader hiện có; staging với
`replace=False` và load theo `extract_batch_id`, không xóa staging của batch khác.

Có thể đổi tháng bắt đầu:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with-requirements pipeline/requirements.txt \
  python -m scripts.backfill_eda --start 2020-01 --symbols BTC,ETH
```

Nạp thêm dữ liệu không có nghĩa phải dùng tất cả để train. Luôn kiểm nến thiếu và
ngày niêm yết. Xem [Kiểm chứng kho dữ liệu](warehouse_proof.md).

## 5. Kiểm dự báo trong EDA được làm thế nào?

- Target là simple return kỳ t: `close[t] / close[t−1] − 1`.
- Quy tắc cố định: lấy dấu return t−1 để dự đoán hướng t; đứng giá thuộc lớp không tăng.
- 75% đầu khoảng lịch yêu cầu là train, 25% cuối là holdout, không shuffle.
- Baseline luôn đoán lớp phổ biến **trên train**, không chọn theo holdout.
- So MAE của return kỳ trước với baseline return = 0 trên cùng mẫu holdout.
- Khoảng bootstrap 95% dùng block 7 nến ngày hoặc 24 nến giờ, 500 lần, seed 42.
- Nếu CI của chênh accuracy chứa 0: chưa có bằng chứng quy tắc vượt baseline.

Đây chưa phải train classifier hay kiểm hiệu quả giao dịch. Khoảng bootstrap chỉ là
thăm dò, phụ thuộc block và chưa điều chỉnh cho việc kiểm nhiều coin. Không tune
feature trên holdout rồi tiếp tục gọi nó là test cuối chưa xem.

Tương quan cùng kỳ không được coi là bằng chứng dự báo. Ví dụ cặp tương quan cao nhất
được chọn từ EDA chỉ để minh họa; kiểm tra trễ của cặp đó vẫn là khám phá có chọn mẫu,
không phải kết quả kiểm định độc lập.

## 6. Snapshot và khả năng tái hiện

Mỗi lần chạy lưu vào `data/eda/` (được gitignore):

- CSV các dòng thực sự dùng, có thứ tự ổn định.
- JSON chứa phạm vi, SHA-256 snapshot, coverage, rủi ro và kết quả kiểm trễ.

DB được đọc trong một transaction read-only repeatable-read. SHA-256 nhận diện nội
dung snapshot; nó không chứng minh nguồn Binance đúng và không thay checksum ZIP.

Trong HTML có lệnh chạy lại từ chính CSV:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with-requirements scripts/requirements-eda.txt \
  python -m scripts.run_eda --start 2024-01-01 --end 2026-10-18 \
  --symbols BTC,ETH,SOL,ADA,DOGE,SHIB --interval 1d \
  --snapshot data/eda/eda-1d-d74baf2920e4.csv
```

Thay filename/phạm vi bằng thông tin lần chạy của bạn. Lệnh này không kết nối DB.
Snapshot không được public lên frontend; chỉ HTML đã xuất được đưa vào trang web.

## 7. Kết quả local và cách hiểu

Lần chạy trên khoảng 2024-01-01 → 2026-10-17:

- 6.126 nến, không thiếu trong khoảng yêu cầu; có 1.020 return liên tiếp chung.
- 840 fact cũ chưa có SHA-256 nguồn; giữ nguyên `null`, không gán lineage bằng suy đoán.
- BTC có 50,59% ngày tăng trên toàn khoảng nhưng vẫn có drawdown khoảng −52,97%.
- Holdout BTC có 256 mẫu: momentum một kỳ đúng 48,44%, baseline cố định đúng 49,22%.
  Chênh −0,78 điểm %, CI chứa 0: chưa thấy lợi thế của quy tắc này.
- BTC holdout: |return kế tiếp| TB sau trạng thái biến động cao là 2,05% (78 mẫu),
  so với 1,40% (178 mẫu) sau trạng thái thấp. Gợi ý thử feature rủi ro, chưa chứng minh
  dự báo hướng hoặc ý nghĩa thống kê của chênh lệch.

Các số này chỉ thuộc phạm vi và snapshot trên. Sáu coin được chọn và một sàn không
đại diện toàn thị trường, nhất là các coin đã hủy niêm yết.

## 8. Kiểm chứng bằng ví dụ số thật và định nghĩa bài toán

[Mở bản kiểm chứng đã chạy](/reports/eda-checks.html).

Lệnh kiểm lại snapshot và các archive trong cache:

```bash
uv run --python 3.12 --with-requirements scripts/requirements-eda.txt \
  python -m scripts.verify_eda --summary data/eda/eda-1d-d74baf2920e4.json \
  --verify-provider
```

Thay filename theo lần EDA của bạn. `--verify-provider` tải checksum hiện tại cho một
ZIP mẫu mỗi coin; không có tùy chọn này thì chỉ kiểm cache so với manifest đã ghi.
Script không sửa fact hoặc gán nguồn cho fact cũ.

Lần kiểm hiện tại:

- SHA-256 snapshot khớp JSON.
- 252 ZIP có lineage: SHA-256 local khớp giá trị đã ghi.
- 5.286 fact có lineage: OHLC/quote volume khớp đúng dòng CSV, tính đến độ làm tròn
  của schema warehouse. 840 fact cũ không có đủ lineage được ghi riêng là chưa đối chiếu.
- Sáu checksum nhà cung cấp mẫu, một ZIP mỗi coin, đều khớp; không tuyên bố đã kiểm
  lại checksum online của mọi archive.
- Tính return bằng hai giá thật và drawdown bằng một đỉnh trước đáy thật.
- So cùng kỳ/trễ một kỳ, baseline và CI; kiểm độ nhạy bootstrap block 3/7/14 ngày.

Định nghĩa model sản phẩm không phải phép thử ngày trong EDA: xem
[Bài toán mô hình: câu hỏi, input/output](model_question.md). Mô hình giờ chưa được
train mới trong bước kiểm chứng này.

## 9. Bản xuất từ notebook cũ

`scripts/export_eda_html.py` vẫn còn để tham khảo, không phải lệnh EDA mặc định nữa.
Nếu muốn xuất bản notebook cũ, dùng output khác để tránh ghi đè báo cáo DB:

```bash
uv run --python 3.12 --with plotly==6.3.1 python -m scripts.export_eda_html \
  --output /tmp/eda-notebook-saved.html
```

Sau khi thay HTML/docs, build lại frontend nếu đang dùng Docker:

```bash
docker compose up -d --no-deps --build frontend
```
