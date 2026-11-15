# Kịch bản video CO4031, nhóm 7, lớp L02

Phần A là tóm tắt: ai làm gì, quay bằng máy nào, chuẩn bị gì. Phần B là lời thoại chi tiết theo từng slide
và từng bước demo. Lời thoại viết đầy đủ để đọc thử cho quen; lúc quay thì nói theo ý, đừng đọc nguyên văn.

---

## Phần A. Tóm tắt

### Yêu cầu của đề

- Video 10–15 phút, mọi thành viên xuất hiện và trình bày, hình và tiếng rõ.
- Upload YouTube (unlisted) hoặc Google Drive; link ghi ở trang bìa báo cáo.
- Hạn nộp: 23:59 Chủ nhật 15/11/2026. Nộp ZIP trước 22:00 cho an toàn.

### Thứ tự và thời lượng

Mỗi người nói liền một phần, không xen kẽ. Tổng khoảng 13 phút 45 giây.

| Thứ tự | Người | Slide | Thời gian | Nội dung | Demo, UI |
| --- | --- | --- | --- | --- | --- |
| 1 | Hà Bảo Nhi | 1–10 | 0:00–4:15 | Mở đầu, kiến trúc, thiết kế kho, ETL, kiểm tra chất lượng | Airflow, DataGrip, tab Data |
| 2 | Lê Chí Đại | 11–17 | 4:15–8:30 | Nạp lại idempotent, OLAP, luồng trực tiếp, vận hành, agent | Airflow, DataGrip, Kafka UI, dashboard, agent, Jaeger |
| 3 | Đào Quang Dương | 18–26 | 8:30–13:45 | DSS, dự báo, cổng công bố, kết quả, hạn chế, kết | Trình duyệt: API JSON, dashboard |

### Quay bằng máy nào

| Người | Máy | Truy cập server |
| --- | --- | --- |
| Nhi | Máy Mac của Đại, quay ngồi cùng Đại | Đường hầm SSH của Đại |
| Đại | Máy Mac của Đại | Đường hầm SSH của Đại |
| Dương | Máy của Dương | Không cần; chỉ dùng URL công khai |

Lý do: SSH vào server đi qua ứng dụng Cloudflare Access chỉ cấp cho máy của Đại. Nhi và Đại quay cùng máy nên
dùng chung đường hầm. Phần demo của Dương chỉ cần dashboard và hai API công khai, nên không cần SSH.

### Chuẩn bị chung (Đại làm trước khi quay)

- [x] Supabase đã resume, đăng nhập được.
- [ ] Dọn đĩa server (đang 92%).
- [ ] Đăng nhập dashboard bằng tài khoản owner, để agent không bị giới hạn 5 câu của khách.
- [ ] Mở đường hầm SSH, giữ terminal này mở suốt lúc Nhi và Đại quay:

  ```bash
  ssh -N home \
    -L 5432:127.0.0.1:5432 \
    -L 8080:127.0.0.1:8080 \
    -L 8081:127.0.0.1:8081 \
    -L 16686:127.0.0.1:16686
  ```

- [ ] Mở sẵn các tab:

  | Tab | Địa chỉ |
  | --- | --- |
  | Dashboard | <https://coinsight.kaiosthefox.dpdns.org> |
  | Airflow | <http://localhost:8081> |
  | Kafka UI | <http://localhost:8080> |
  | Jaeger | <http://localhost:16686> |
  | DataGrip | PostgreSQL `localhost:5432`, database `crypto_dw`, user `crypto`, password `crypto`; mở `report/demo/demo1_nhi.sql` và `demo2_dai.sql` |

- [ ] Kiểm tra lần chạy mới nhất của `coinsight_warehouse_daily` trong Airflow là success (xanh).
- [ ] Không chạy `make` hay lệnh nạp nào trên host server bằng root (sự cố 22/10). Mọi thao tác nạp đi qua Airflow UI.

### Chuẩn bị riêng

| Người | Cần chuẩn bị |
| --- | --- |
| Nhi | Đọc slide 1–10 và phần B.1. Làm quen các UI theo mục "Nhi làm quen UI" bên dưới, rồi thử trọn Demo 1 trên máy Đại. |
| Đại | Đường hầm, các tab, tài khoản owner, DataGrip mở sẵn `demo2_dai.sql`. Thử hỏi agent trước một lần để chắc agent trả lời. |
| Dương | Đọc slide 18–26 và phần B.3. Mở sẵn hai URL API và dashboard trên trình duyệt (Firefox hiển thị JSON dễ đọc). Tùy chọn: gửi Đại hai thư mục snapshot nếu muốn demo backtest. |

### Nhi làm quen UI (khoảng 30 phút, trên máy Đại, đường hầm đang mở)

1. Airflow <http://localhost:8081>:
   - Danh sách DAG, bấm `coinsight_warehouse_daily`.
   - Tab Graph: ba task và mũi tên giữa chúng.
   - Lưới các lần chạy: ô xanh là thành công, đỏ là lỗi. Bấm một ô task, mở Logs.
   - Tìm trong log của `quality_report` đoạn in 12 rule. Không bấm Clear hay Trigger; đó là việc của Đại.
2. DataGrip:
   - Mở `report/demo/demo1_nhi.sql`, đặt con trỏ vào từng câu, Cmd+Enter để chạy.
   - Panel Database bên trái: mở schema `dw`, xem các bảng `dim_*` và `fact_*`. Chuột phải một bảng, Diagram, Show Diagram để thấy quan hệ.
   - Tăng cỡ chữ editor và kết quả (Settings, Editor, Font) để đọc được trên video.
3. Dashboard, tab Data: đọc số dòng, độ phủ và nến thiếu; hiểu "Behind" nghĩa là gì (slide 15).
4. Quay thử Demo 1 một lần, xem lại, canh còn khoảng 1 phút 15 giây.

### Thiết bị và cách quay

- OBS, 1920×1080, 30 fps. Slide hoặc màn hình demo toàn khung, webcam góc phải dưới.
- Mic rời hoặc tai nghe có mic, phòng yên tĩnh. Quay thử 20 giây, nghe lại rồi mới quay thật.
- Mỗi người một file liền mạch gồm slide và demo: `p1_nhi.mp4`, `p2_dai.mp4`, `p3_duong.mp4`.
  Nói sai thì quay lại từ đầu slide đó, không cắt giữa câu.
- Trước khi quay: không mở `.env`, ẩn thông báo, cỡ chữ DataGrip và terminal khoảng 18pt.
  Trình duyệt: ẩn thanh bookmark, phóng to 125% để chữ đọc được trên video.
- Đại ghép video (DaVinci Resolve hoặc CapCut), chèn tên người ở góc dưới khi đổi phần.

### Lịch

| Thời điểm | Việc | Ai |
| --- | --- | --- |
| Chủ nhật 15/11 sáng | Dọn server, mở đường hầm, quay phần 1 và 2 | Nhi, Đại |
| Chủ nhật 15/11 sáng | Quay phần 3 | Dương |
| Chủ nhật 15/11 trưa | Ghép, kiểm tra ≤ 15 phút, upload unlisted | Đại |
| Chủ nhật 15/11 chiều | Điền link video vào bìa, build lại `report.pdf` | Nhi |
| Chủ nhật 15/11 trước 22:00 | Chạy `report/make_submission.sh`, nộp ZIP lên LMS | Dương |

---

## Phần B. Lời thoại chi tiết

Thời lượng ghi cạnh mỗi slide là ước lượng. Phần trong ngoặc vuông là hành động, không đọc thành tiếng.

### B.1. Hà Bảo Nhi (slide 1–10, khoảng 4 phút 15 giây)

#### Slide 1. Bìa (15 giây)

> Em chào thầy. Nhóm 7 lớp L02 xin trình bày đồ án CoinSight: kho dữ liệu nến giá crypto và hệ hỗ trợ quyết định.
> Nhóm gồm ba bạn: Lê Chí Đại, Đào Quang Dương, và em là Hà Bảo Nhi.

#### Slide 2. Ba người, ba phần (20 giây)

> Video chia ba phần liền nhau. Em trình bày phần đầu: bài toán, kiến trúc, và cách thiết kế kho cùng quy trình ETL.
> Sau đó bạn Đại nói về cách dùng và vận hành kho: nạp lại, truy vấn OLAP, luồng dữ liệu trực tiếp và agent hỏi đáp.
> Cuối cùng bạn Dương trình bày hệ hỗ trợ quyết định và tổng kết.
> Mỗi phần đều có demo trên hệ thống đang chạy thật.

#### Slide 3. Câu hỏi (25 giây)

> Nhóm bắt đầu từ hai câu hỏi của một người theo dõi thị trường crypto.
> Câu thứ nhất: quý vừa rồi, nhóm coin nào tăng mạnh nhất? Đây là câu hỏi về quá khứ, cần tổng hợp theo nhóm coin và theo thời gian, đúng là việc của kho dữ liệu.
> Câu thứ hai khó hơn: ngày mai BTC có tăng không, và có nên tin con số dự báo đó không? Đây là việc của hệ hỗ trợ quyết định.
> Toàn bộ thiết kế phía sau đi ra từ hai câu hỏi này.

#### Slide 4. Hai luồng vào một kho (25 giây)

> Dữ liệu vào kho theo hai luồng.
> Luồng batch ở trên: mỗi sáng hệ thống tải file ZIP nến ngày và nến giờ từ kho dữ liệu công khai của Binance, đưa vào vùng staging, chạy 12 rule kiểm tra, rồi nạp vào schema `dw` và làm mới mart OLAP. Airflow chạy luồng này lúc 6 giờ sáng giờ UTC.
> Luồng stream ở dưới: nến 1 phút đi từ WebSocket của Binance qua Kafka, Spark, vào bảng fact trực tiếp, rồi FastAPI đẩy lên giao diện.
> Batch cho lịch sử chính xác vì archive là bản chính thức của sàn. Stream cho biết phút vừa đóng. Hai luồng dùng chung bảng `dim_asset`.

#### Slide 5. Phần 1, Kho dữ liệu (10 giây)

> Trong phần này em sẽ đi theo một cây nến BTC ngày 24 tháng 10 năm 2026, từ lúc nó là một dòng trong file ZIP tới lúc nó nằm trong bảng fact của kho.

#### Slide 6. Bốn quy trình, một bộ dimension (35 giây)

> Nhóm thiết kế theo phương pháp Kimball, bắt đầu từ bus matrix.
> Có bốn quy trình nghiệp vụ, mỗi quy trình là một bảng fact: nến ngày, nến giờ, chỉ số trực tiếp, và dự báo hướng giá.
> Các cột là dimension dùng chung: ngày, giờ, coin, nguồn dữ liệu, và mô hình. Fact dự báo dùng dimension ngày hai lần, nên ghi là nhân hai; em sẽ giải thích ở slide sau.
> Bên phải là grain. Bảng ngày có grain là một coin, một ngày UTC, một nguồn. Bảng giờ là một coin, một giờ UTC, một nguồn.
> Khóa chính của bảng fact chính là grain, nên cơ sở dữ liệu tự chặn nến bị trùng.
> Nhóm tách ngày và giờ thành hai bảng, để một phép `sum` không bao giờ trộn hai grain với nhau.

#### Slide 7. Galaxy schema (30 giây)

> Ghép bốn fact lại thì được một galaxy schema, hay còn gọi là fact constellation: nhiều bảng fact dùng chung các dimension.
> Bên trái là `dim_date` và `dim_time`. Bên phải là `dim_asset`, `dim_source` và `dim_model`.
> Điểm đáng chú ý là fact dự báo dùng `dim_date` với hai vai trò, nét đứt trên hình: một lần là ngày dữ liệu đầu vào, một lần là ngày mục tiêu được dự báo. Đây là role-playing dimension.
> EERD và lược đồ quan hệ đầy đủ có trong báo cáo.

#### Slide 8. Những lựa chọn khi thiết kế dimension (35 giây)

> Slide này là các quyết định thiết kế cho từng dimension và lý do.
> `dim_date` dùng khóa dạng số như 20261024, phủ từ 2010 tới 2030. Khóa này đọc bằng mắt được và lọc theo khoảng rất dễ.
> `dim_time` chỉ có 24 dòng, mỗi giờ một dòng, kèm phiên giao dịch châu Á, châu Âu, châu Mỹ. Nếu gộp ngày với giờ thành một dimension thì mỗi năm phình ra 8.760 dòng.
> `dim_asset` dùng khóa thay thế và SCD loại 1, tức là ghi đè khi thông tin coin thay đổi, vì câu hỏi của nhóm không cần biết coin từng thuộc nhóm nào trong quá khứ.
> `dim_source` phân biệt archive, REST và live, khi cùng một cây nến có hai bản từ hai nguồn.
> Về measure: volume thì cộng được, còn giá open, close, high, low thì không cộng được. Ví dụ close của một quý là close của ngày cuối quý, không phải tổng.

#### Slide 9. Cây nến bị kiểm tra trước khi vào kho (35 giây)

> Trước khi vào kho, mỗi dòng trong staging phải qua 12 rule.
> 7 rule đầu loại dòng: thiếu giá trị, giá âm hoặc bằng 0, OHLC không nhất quán, volume âm, thời gian lệch khỏi khung nến, nguồn không xác định, ngày không có trong lịch.
> 5 rule sau chỉ cảnh báo: nến trùng grain, volume bằng 0, nến bị đứt quãng, dữ liệu chưa đủ mới, và tổng nến giờ không khớp nến ngày.
> Ví dụ bên phải: high nhỏ hơn open là vô lý, nên rule `ohlc_consistency` loại dòng này.
> Nếu hơn 5% số dòng bị loại thì cả lần nạp bị hủy, vì khi đó lỗi thường nằm ở nguồn hoặc ở parser, không phải ở vài dòng lẻ.
> Ngoài ra, mỗi file ZIP được kiểm SHA-256 khi tải về, nên file hỏng hay file bị sửa đều bị phát hiện.

#### Slide 10. Demo 1: Airflow nạp một ngày (1 phút 15 giây)

> Bây giờ em demo trên hệ thống đang chạy.

1. [Mở tab Airflow, bấm vào DAG `coinsight_warehouse_daily`, chọn tab Graph]
   > Đây là DAG nạp kho hằng ngày, chạy lúc 6 giờ sáng UTC. DAG có ba task: `extract_binance` tải và kiểm archive của ngày hôm trước, `transform_load` kiểm tra chất lượng rồi nạp, và `quality_report` in kết quả kiểm tra.
2. [Bấm vào lần chạy gần nhất (ô xanh), chọn task `quality_report`, mở Logs, cuộn tới đoạn in các rule]
   > Đây là log của lần chạy sáng nay. Mỗi dòng là một rule, có mức error hoặc warning. Lần này tất cả đều ok, không dòng nào bị loại.
3. [Chuyển sang DataGrip, `demo1_nhi.sql`, chạy câu 1]

   ```sql
   select batch_id, symbol, candle_interval, staging_rows, rejected_rows,
          duplicate_rows, accepted_rows, changed_rows
   from meta.warehouse_load_report
   where symbol = 'BTC' order by batch_id desc limit 4;
   ```

   > Mỗi lần nạp ghi lại một báo cáo. Với BTC, lần nạp mới nhất có 24 nến giờ và 1 nến ngày vào staging. Cột staging luôn bằng tổng bị loại, bị trùng và được nhận. Nếu đẳng thức này sai thì có dòng bị mất ở đâu đó.
4. [Chạy câu 2]

   ```sql
   select d.full_date, a.symbol, a.category, s.source_code,
          f.open_price, f.high_price, f.low_price, f.close_price, f.batch_id
   from dw.fact_ohlcv_daily f
   join dw.dim_asset a using (asset_key)
   join dw.dim_date d on d.date_key = f.date_key
   join dw.dim_source s using (source_key)
   where a.symbol = 'BTC' and d.full_date = date '2026-10-24';
   ```

   > Và đây là cây nến BTC ngày 24 tháng 10 em nhắc từ đầu, đã nằm trong bảng fact, nối với các dimension ngày, coin và nguồn. Cột `batch_id` cho biết nó vào kho ở lần nạp nào.
5. [Mở tab Dashboard, bấm tab Data]
   > Cuối cùng là tab Data trên dashboard: số dòng của từng bảng, độ phủ theo coin, và số nến bị thiếu. Đây là chỗ người dùng biết kho có đủ dữ liệu hay không trước khi tin vào con số.

> Phần của em tới đây là hết. Tiếp theo bạn Đại sẽ trình bày cách dùng và vận hành kho.

### B.2. Lê Chí Đại (slide 11–17, khoảng 4 phút 15 giây)

#### Slide 11. Phần 2, Dùng và vận hành kho (10 giây)

> Em là Đại. Dữ liệu đã vào kho. Phần này nói về ba việc: nạp lại sao cho an toàn, dùng kho để trả lời câu hỏi mở đầu, và giữ hệ thống chạy đúng mỗi ngày.

#### Slide 12. Nạp lại một ngày, kho không đổi (35 giây)

> Trong thực tế, một ngày có thể bị nạp nhiều lần: Airflow thử lại khi lỗi, hoặc Binance sửa lại archive. Vì vậy lần nạp phải idempotent: nạp một lần hay mười lần thì kho vẫn như nhau.
> Câu lệnh nạp dùng upsert của PostgreSQL. Gặp khóa grain đã có thì cập nhật, nhưng mệnh đề `where ... is distinct from` chỉ cho ghi khi số đo thật sự khác. Dòng giống hệt thì bỏ qua.
> `RETURNING` trả về những dòng thực sự đổi, và con số đó vào cột `changed_rows` của báo cáo nạp mà bạn Nhi vừa cho xem.
> Nhóm kiểm chứng bằng cách tính checksum SHA-256 của bảng fact trước và sau khi nạp lại: hai giá trị bằng nhau.

#### Slide 13. Trả lời câu hỏi mở đầu bằng CUBE (40 giây)

> Giờ quay lại câu hỏi đầu tiên: quý vừa rồi nhóm coin nào tăng mạnh nhất.
> Câu truy vấn tính lợi suất ngày trung bình và độ biến động theo nhóm coin, năm và quý, bỏ stablecoin ra. `group by cube` sinh ra mọi tổ hợp của ba chiều này, tám tổ hợp, trong một lần quét.
> Dòng tổng hợp được ghi là `'ALL'` thay vì để `NULL`, để người đọc không nhầm với dữ liệu thiếu.
> Mart còn dùng `ROLLUP` để đi từ tháng lên quý lên năm, `GROUPING SETS` cho các tổ hợp coin, phiên và giờ, và `rank()` để lấy top ba coin tăng và giảm mỗi quý.
> Các kết quả này là materialized view, được làm mới trong cùng transaction với lần nạp, nên mart không bao giờ lệch với kho.

#### Slide 14. Nến phút đi đường riêng (35 giây)

> Luồng thứ hai là dữ liệu trực tiếp.
> WebSocket của Binance chỉ phát nến đã đóng. Khi mất kết nối, producer gọi REST để bù những nến bị lỡ. Ví dụ tuần rồi server nhà em tắt năm ngày, khi bật lại producer tự bù đủ nến phút, không có lỗ hổng nào.
> Kafka giữ thứ tự và cho phép đọc lại. Spark Structured Streaming loại trùng theo `event_id` với watermark một ngày.
> Ghi xong, PostgreSQL phát `NOTIFY`, và FastAPI đẩy dữ liệu qua WebSocket tới giao diện.
> Dữ liệu trực tiếp chỉ để xem thị trường lúc này. Phân tích lịch sử và mô hình chỉ đọc dữ liệu batch, vì archive mới là bản chính thức.

#### Slide 15. Mỗi sáng, và khi có sự cố (30 giây)

> Lịch chạy: 6 giờ UTC Airflow nạp kho, 7 giờ 30 chạy dự báo, và thứ Hai thì train lại mô hình.
> Sau 7 giờ UTC mà chưa có dữ liệu ngày hôm qua thì tab Data báo trạng thái Behind.
> Khi một con số trông lạ, nhóm truy ngược được: từ con số trên mart về dòng fact và `batch_id`, từ batch về bảng `meta.etl_batch` và tên file nguồn, và từ file về file ZIP cùng SHA-256 của nó. Tức là luôn biết con số đến từ file nào và lần nạp nào.

#### Slide 16. Hỏi kho bằng tiếng người (35 giây)

> Không phải ai cũng viết SQL, nên nhóm làm thêm agent hỏi đáp.
> Có hai agent LangGraph nói chuyện với nhau qua giao thức A2A. Agent Analyst trả lời về thị trường, mart và dự báo. Agent Operations kiểm tra nến thiếu, lần nạp lỗi và drift mô hình.
> Agent đọc kho bằng role `coinsight_observer`, chỉ có quyền đọc. Mọi con số trong câu trả lời phải có trong kết quả công cụ trả về, nếu không câu trả lời bị chặn. Đây là cách nhóm chống bịa số.
> Bộ test 14 câu với Claude Haiku 4.5: điểm tổng 92,9%, chọn đúng công cụ 100%, số không có nguồn 1,1%, chống prompt injection 100%. Điểm yếu là mới từ chối được 50% các yêu cầu ghi dữ liệu hoặc xin tư vấn đầu tư.

#### Slide 17. Demo 2: OLAP, luồng trực tiếp và agent (2 phút)

1. [Airflow: mở lần chạy gần nhất của `coinsight_warehouse_daily`, bấm Clear, xác nhận. Chờ ba task xanh, mở log `quality_report`]
   > Em cho Airflow nạp lại đúng ngày vừa nạp. Task extract tải lại archive, thấy checksum đã có trong kho nên không đưa gì vào staging, và log báo kho đã cập nhật. Số dòng fact không đổi.
   [Đọc đúng dòng log trên màn hình. Nếu lần chạy lại có nạp, chạy câu 1 của `demo1_nhi.sql` và chỉ cột `changed_rows` = 0. Đại thử trước khi quay để biết rơi vào trường hợp nào.]
   [Nếu chờ lâu, cắt đoạn chờ khi dựng video]
2. [DataGrip, `demo2_dai.sql`, chạy câu 1 và câu 2]

   ```sql
   select category, year, quarter, assets,
          round(avg_daily_return * 100, 2) as avg_daily_return_pct,
          round(daily_volatility * 100, 2) as daily_volatility_pct
   from mart.mv_category_performance
   where year = 2026 and quarter = 3;

   select symbol, category, round(period_return * 100, 1) as return_pct, gain_rank
   from mart.v_top_movers where year = 2026 and quarter = 3 order by gain_rank;
   ```

   > Đây là câu trả lời cho câu hỏi mở đầu. Quý 3 năm 2026, nhóm layer-1 có lợi suất ngày trung bình khoảng 0,56%, cao hơn nhóm meme khoảng 0,39%. Nhưng nhóm meme biến động mạnh hơn. Dòng `ALL` là tổng của cả hai nhóm.
   > Theo từng coin, ETH tăng mạnh nhất quý, khoảng 71%, sát sau là ADA.
3. [Mở Kafka UI, chọn topic `crypto-prices-live`, tab Messages]
   > Đây là topic Kafka của luồng trực tiếp. Cứ mỗi phút có message mới cho 20 coin.
   [Chuyển sang Dashboard, tab Market, chọn BTC]
   > Và trên dashboard, nến phút của BTC cập nhật ngay khi nến đóng, không cần tải lại trang.
4. [Mở khung Assistant trên dashboard, gõ lệnh `sre`, hỏi: "Kho dữ liệu đã nạp đến ngày nào và lần kiểm tra chất lượng gần nhất có lỗi không?"]
   > Giờ hỏi agent vận hành bằng tiếng Việt. Agent gọi hai công cụ chỉ đọc: trạng thái kho và báo cáo chất lượng. Lần nạp lúc 6 giờ sáng nay, batch mới nhất, các check đều đạt, không dòng lỗi. Khớp với log Airflow vừa xem ở bước 1.
   [Mở phần evidence dưới câu trả lời. Đọc số batch và giờ nạp trên màn hình, không đọc theo kịch bản. Lưu ý: batch chạy sáng nay nạp dữ liệu của ngày hôm qua.]
   [Không hỏi về tháng hay quý: agent không có công cụ đọc mart, sẽ hỏi lại hoặc từ chối. Câu hỏi quý đã trả lời bằng SQL ở bước 2.]
5. [Mở Jaeger, Service chọn `coinsight-sre`, Find Traces, mở trace mới nhất]
   > Mỗi câu hỏi để lại một trace. Ở đây thấy từng bước: các lượt gọi mô hình, công cụ nào chạy, câu truy vấn Postgres nào, mất bao lâu. Khi agent trả lời sai, nhóm mở trace để biết sai ở bước nào.

> Phần của em hết. Tiếp theo bạn Dương trình bày hệ hỗ trợ quyết định.

### B.3. Đào Quang Dương (slide 18–26, khoảng 5 phút 15 giây)

#### Slide 18. Phần 3, Hệ hỗ trợ quyết định (10 giây)

> Em là Dương. Kho cho biết chuyện đã xảy ra. Hệ hỗ trợ quyết định thử đoán chuyện sắp xảy ra, và quan trọng hơn là phải biết lúc nào nên im lặng.

#### Slide 19. Ba pha ra quyết định của Simon (35 giây)

> Nhóm tổ chức DSS theo ba pha ra quyết định của Simon.
> Pha Intelligence là nhận biết tình hình: mart OLAP, phát hiện bất thường bằng Isolation Forest và MAD, và tab Data cho biết dữ liệu có đủ không.
> Pha Design là xây phương án: mô hình được xây từ bảng `fact_ohlcv_daily`, và luôn được so với một baseline đơn giản trên dữ liệu chia theo thời gian.
> Pha Choice là chọn: chỉ công bố dự báo khi mô hình thắng baseline, và chính sách paper trade biến dự báo thành lệnh mua bán mô phỏng.
> Theo cấu trúc DSS kinh điển: kho là phần quản lý dữ liệu, các mô hình là phần quản lý mô hình, dashboard và agent là giao diện người dùng.

#### Slide 20. Ngày mai tăng hay giảm? (40 giây)

> Bài toán đầu tiên: sau khi nến ngày D đóng, tính xác suất giá đóng cửa ngày D+1 cao hơn ngày D, cho BTC, ETH và SOL.
> Đặc trưng gồm lợi suất 1 ngày, lợi suất 7 ngày, biên độ giá trong ngày, thay đổi volume, và biên độ tính từ đủ 24 nến giờ.
> Mô hình là logistic regression. Dữ liệu chia theo thời gian: 30 ngày cuối làm tập kiểm tra, 30 ngày trước đó làm tập kiểm định, không xáo trộn, để mô hình không nhìn thấy tương lai.
> Cổng công bố dùng Brier score, là trung bình bình phương sai lệch giữa xác suất dự báo và kết quả thật. Brier của mô hình phải thấp hơn baseline trên cả hai tập. Không đạt thì giao diện ghi "Model below baseline. Signal withheld." và không hiện tín hiệu.

#### Slide 21. Dự báo một khoảng, không phải một điểm (40 giây)

> Hướng thứ hai là dự báo một khoảng giá thay vì một con số.
> Đầu vào là 90 nến ngày, mỗi nến 25 đặc trưng. Bản v2 ghép thêm BTC, ETH và SOL thành ma trận 90 nhân 75.
> GRU và LSTM dự báo ba phân vị q10, q50 và q90, train bằng pinball loss.
> Cách đọc: nếu q10 lớn hơn 0 thì khá chắc giá tăng; nếu q90 nhỏ hơn 0 thì khá chắc giảm; còn lại là không chắc.
> Tập test chỉ được dùng một lần, sau đó bị đánh dấu `TEST_CONSUMED` để không ai chọn mô hình dựa trên nó nữa.
> Bên phải là chính sách paper trade daily-quantile v1: chỉ mua bán spot, không bán khống, mỗi lệnh tối đa 8% danh mục, dừng khi danh mục sụt 25%, và không đặt lệnh nếu giá cũ hơn 300 giây. Đây chỉ là mô phỏng, chưa tính phí.

#### Slide 22. Kết quả âm, nhưng có cơ sở (40 giây)

> Nhóm cũng thử dự báo lợi suất BTC của giờ kế tiếp. Thước đo là relative MAE: MAE của mô hình chia cho MAE khi luôn đoán bằng 0. Nhỏ hơn 1 nghĩa là tốt hơn đoán 0.
> Mục tiêu 0,97 được khóa trước khi train. Kết quả: ensemble CatBoost 0,9929, XGBoost 0,9957, TCN và LSTM khoảng 0,998. Bản đóng băng chạy trên dữ liệu tháng 1 tới tháng 10 năm 2026 đạt 0,9970. Không mô hình nào đạt mục tiêu.
> Độ chính xác đoán đúng hướng năm 2026 là 52,96%, chỉ nhỉnh hơn tung đồng xu.
> Nhóm báo cáo trung thực kết quả âm này: lợi suất theo giờ gần như không dự báo được. Mô hình được giữ lại như công cụ tham khảo có ghi rõ giới hạn, không phải tín hiệu giao dịch.

#### Slide 23. Demo 3: dự báo và cổng công bố (1 phút)

1. [Trình duyệt, mở `https://coinsight.kaiosthefox.dpdns.org/api/v1/model/evaluation`]
   > Đây là kết quả đánh giá mô hình hướng giá hiện tại. Brier trên tập kiểm định là 0,2486, baseline 0,2496. Trên tập kiểm tra là 0,2497, baseline 0,2503. Mô hình thấp hơn baseline trên cả hai tập nên quyết định là `accepted`. Mức thắng rất nhỏ, đúng với kết luận là thị trường rất khó đoán.
2. [Mở `https://coinsight.kaiosthefox.dpdns.org/api/v1/assets/BTC/prediction`]
   > Dự báo cho BTC: `as_of_date` là ngày dữ liệu đầu vào, `target_date` là ngày được dự báo, và `probability_up` là xác suất tăng, ở đây gần 0,5. Hai ngày này chính là hai vai của `dim_date` mà bạn Nhi nhắc ở phần thiết kế.
   [Con số sẽ khác lúc quay; đọc đúng số trên màn hình]
3. [Dashboard, chọn BTC, tab Signal]
   > Trên dashboard, tab Signal hiện tín hiệu của mô hình. Nếu mô hình thua baseline thì chỗ này ghi "Signal withheld" và hệ thống không đưa ra tín hiệu.
   [Mô tả đúng những gì tab hiện lúc quay.]
4. [Mở hình biểu đồ giá và khoảng q10–q90 trên tập test, từ báo cáo]
   > Còn đây là dự báo khoảng của GRU trên tập test: đường giá thật so với dải q10 tới q90 mà mô hình dự báo.
   [Nhận xét theo hình thật: giá thật nằm trong dải bao nhiêu phần, dải rộng ra lúc nào.]

#### Slide 24. Kho ngày 25/10/2026 (20 giây)

> Tổng kết bằng con số. Tại ngày 25 tháng 10, kho có 20 coin, 6.238 nến ngày không thiếu nến nào, 175.809 nến giờ thiếu 81 nến, và lần nạp gần nhất 500 dòng không dòng nào bị loại.
> Nạp lại cùng archive thì checksum bảng fact không đổi.

#### Slide 25. Điều chưa làm tốt (40 giây)

> Nhóm cũng tự đánh giá những điểm chưa làm tốt, mỗi phần một điểm.
> Phần kho dữ liệu: ETL mới nạp đủ lịch sử cho 6 trên 20 coin, và vì `dim_asset` dùng SCD loại 1 nên khi một coin đổi nhóm, số liệu cũ cũng đổi theo.
> Phần vận hành: bảng `fact_live_metric` nối với `dim_asset` bằng symbol thay vì khóa thay thế, và agent mới từ chối được một nửa số yêu cầu ghi hoặc xin tư vấn.
> Phần mô hình: mô hình ngày đã chọn ứng viên bằng điểm trên tập test nhiều lần, nên tập test không còn độc lập.
> Việc tiếp theo: backfill 14 coin còn lại, chuyển sang `asset_key`, và làm lại đánh giá mô hình ngày với tập test chỉ dùng một lần.

#### Slide 26. Cảm ơn (10 giây)

> Mã nguồn và tài liệu ở GitHub trên màn hình. Thay mặt nhóm 7, em cảm ơn thầy đã xem.
