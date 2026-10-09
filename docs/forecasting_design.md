# Nghiên cứu các mô hình dự báo — Dương

Trang này giữ **lý do chọn kiến trúc và các phương án mở rộng** từ đề xuất của Dương.
Bài toán, đặc trưng, thời gian, đầu ra và phân chia dữ liệu chỉ được định nghĩa tại
[giao ước dự báo giờ](hourly_forecast_contract.md).
Các phương án dưới đây chưa triển khai; Dương còn cần kiểm chứng phần Transformer
với bài báo và mã nguồn gốc trước khi sử dụng.

## 1. XGBoost: bước triển khai đầu tiên

Nhận đặc trưng dạng bảng, chạy được trên CPU và ít công đoạn hơn mô hình mạng sâu.
Dùng BTC `XGBRegressor` để thử tập dữ liệu và hai phương pháp đối chiếu trước.
Cấu hình khởi đầu được giữ trong giao ước giờ; trang này không tạo bộ tham số thứ hai.

## 2. GRU và LSTM: học chuỗi quá khứ

Hai loại mạng hồi tiếp nhận chuỗi đặc trưng của 168 giờ. Chúng dùng các cổng để
kiểm soát thông tin được giữ/quên. Dùng `torch.nn.GRU` / `torch.nn.LSTM`, không tự
viết lại công thức cổng. So sánh với cùng kích thước trạng thái, số lớp và ngân sách
huấn luyện để tập trung vào sự khác nhau giữa hai loại mạng.

| Lựa chọn khởi đầu | Giá trị dự kiến |
| --- | --- |
| Kích thước trạng thái ẩn | 64 hoặc 128 |
| Số lớp | 1–2 |
| Đầu ra | Lớp tuyến tính dự báo một log-return |
| Hàm mất mát | Huber |
| Bộ tối ưu | AdamW |
| Tốc độ học | 1e-4 đến 3e-3 |
| Số mẫu mỗi lượt | 64/128/256 |
| Chặn gradient | 1.0 |
| Dừng sớm | 10 vòng không cải thiện trên tập kiểm định |
| Giới hạn vòng huấn luyện | 100 |

Bộ chuẩn hóa chỉ học từ tập tập huấn luyện, được lưu cùng checkpoint. Mạng nhận
`[số mẫu, 168, 13]` và trả một số cho mỗi mẫu.

## 3. Hồi quy dựa trên PatchTST

Nguồn: [bài báo PatchTST](https://arxiv.org/pdf/2211.14730).
Chia chuỗi thành các đoạn nhỏ (patch), coi mỗi đoạn là một token. Các kênh đặc
trưng dùng chung bộ mã hóa Transformer, giúp giảm số token so với từng mốc thời gian.

Điểm cần ghi rõ: PatchTST gốc xử lý độc lập theo kênh, còn CoinSight cần một
return từ nhiều kênh. Vì vậy cần đầu kết hợp biểu diễn các kênh trước lớp hồi quy.
Đây là biến thể dựa trên PatchTST, không được tuyên bố tái lập nguyên bản bài báo.

| Lựa chọn khởi đầu | Giá trị dự kiến |
| --- | --- |
| Độ dài đoạn / bước dịch | 12 hoặc 24 / 6 hoặc 12 |
| Chiều biểu diễn | 64 hoặc 128 |
| Số đầu attention | 4 |
| Số lớp | 2 hoặc 3 |
| Chiều lớp truyền thẳng | 128 hoặc 256 |
| Dropout | 0.1 |

Luồng tensor: `[N,168,13]` → `[N,13,168]` → chia đoạn từng kênh → bộ mã hóa
chung → kết hợp kênh → `[N,1]`. Kiểm tra số đoạn và chiều tensor trước khi tập huấn luyện.

## 4. Hồi quy dựa trên iTransformer

Nguồn: [bài báo iTransformer](https://arxiv.org/pdf/2310.06625).
Mỗi đặc trưng là một token chứa lịch sử 168 giờ; attention học quan hệ giữa các
đặc trưng thay vì coi mỗi mốc thời gian là một token.

Luồng tensor: `[N,168,13]` → 13 token đặc trưng `[N,13,D]` → bộ mã hóa Transformer
→ đầu hồi quy một log-return `[N,1]`. Không nhầm 168 giờ với 13 đặc trưng.

Khởi đầu: chiều biểu diễn 64/128, 4 đầu attention, 2–3 lớp, chiều lớp truyền
thẳng 128/256 và dropout 0.1. Huấn luyện từ đầu; chuẩn hóa bám mã nguồn chính thức.
Đầu ra điều chỉnh cho CoinSight phải được ghi rõ trong thông tin lần chạy.

## 5. So sánh công bằng

Dùng cùng nguồn, coin, nhãn, ranh cửa sổ, tập dữ liệu và metric theo giao ước.
XGBoost nhận độ trễ/thống kê cửa sổ; mạng chuỗi nhận tensor thời gian. Điều cần
đảm bảo là cùng thông tin được phép thấy, không phải cùng hình dạng ma trận.

Ghi rõ ngân sách tinh chỉnh và mọi thay đổi khác bài báo gốc. Mạng sâu cần nhiều
hạt giống ngẫu nhiên để đo độ ổn định; lưu cấu hình và checkpoint để tái lập.
Không chỉnh mô hình dựa trên tập kiểm tra cuối. Các kỳ dự báo 6h/24h, mô hình
chung nhiều coin và dữ liệu phút chỉ xét sau khi bài toán một giờ chạy đúng.
