# Đăng nhập Google / GitHub với Supabase

Hướng dẫn cho lần đầu dùng Supabase. Làm **GitHub trước**, xác nhận đăng nhập hoạt động rồi thêm Google. Bạn không cần chuyển warehouse hay học SQL trên Supabase để làm việc này.

## 1. Supabase làm gì trong CoinSight?

Supabase Auth xử lý đăng nhập: đưa người dùng tới Google/GitHub, nhận kết quả và cấp session token. Browser gửi token cho API CoinSight; API kiểm chữ ký, issuer và audience rồi xác định user.

```text
CoinSight → Supabase Auth → GitHub / Google
          ← session token ← xác nhận đăng nhập
Browser → CoinSight API → kiểm token → history / quota / owner permissions
```

Warehouse, model artifacts, lịch sử chat, feedback và memory vẫn dùng PostgreSQL của CoinSight. OAuth client secrets của GitHub/Google chỉ nhập vào Supabase. Không cần Supabase database password hoặc service-role/secret key trong app.

## 2. Mở đúng project

1. Mở [Supabase Dashboard](https://supabase.com/dashboard), tạo tài khoản hoặc đăng nhập. Dùng GitHub để vào dashboard cũng được; đây chưa phải cấu hình GitHub login cho CoinSight.
2. Tìm project có reference **`wudjldnoabzngluebepw`**. [Mở project](https://supabase.com/dashboard/project/wudjldnoabzngluebepw).
3. Nếu không thấy hoặc bị báo không có quyền, nhờ người tạo project mời đúng tài khoản vào organization. Chưa tạo project khác hay chép cấu hình cũ sang một project mới.
4. Nếu bạn thực sự muốn project riêng, tạo project trước rồi thay **tất cả** project URL/callback bên dưới bằng reference của project mới.

Các giá trị dưới đây thuộc project bạn đã cung cấp, không phải xác nhận project đó đang hoạt động hoặc thuộc tài khoản nào.

| Giá trị | Dùng ở đâu |
| --- | --- |
| `https://coinsight.kaiosthefox.dpdns.org` | Domain của app |
| `https://wudjldnoabzngluebepw.supabase.co` | `SUPABASE_URL` trên máy chạy API |
| `https://wudjldnoabzngluebepw.supabase.co/auth/v1/callback` | Callback nhập trong GitHub và Google |

## 3. Cấu hình nơi quay về sau đăng nhập

Trong project: **Authentication → URL Configuration**.

**Site URL:**

```text
https://coinsight.kaiosthefox.dpdns.org
```

**Redirect URLs:** thêm từng dòng rồi Save:

```text
https://coinsight.kaiosthefox.dpdns.org/
http://localhost:5173/
http://localhost:3000/
```

Code hiện dùng `redirectTo: window.location.origin + '/'`, nên các root URL này đủ cho app. Production dùng URL chính xác; không cần wildcard `/**` cho luồng hiện tại. Nếu đổi hostname hoặc port local, thêm đúng URL tương ứng.

**Hai loại redirect khác nhau:** GitHub/Google quay về **Supabase callback**; Supabase sau đó đưa browser về **CoinSight root URL**. Không đổi chỗ hai URL này.

Nguồn: [Supabase redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls).

## 4. Bật GitHub trước

1. Mở GitHub → avatar → **Settings → Developer settings → OAuth Apps → New OAuth App**. [Mở trang tạo OAuth App](https://github.com/settings/applications/new).
2. Điền:

| Field | Giá trị |
| --- | --- |
| Application name | `CoinSight` |
| Homepage URL | `https://coinsight.kaiosthefox.dpdns.org` |
| Authorization callback URL | `https://wudjldnoabzngluebepw.supabase.co/auth/v1/callback` |

3. Bấm **Register application**. Copy **Client ID**.
4. Bấm **Generate a new client secret**. Dán trực tiếp vào nơi cấu hình provider ở bước tiếp theo; không gửi qua chat hay commit vào repo.
5. Quay lại Supabase → **Authentication → Sign In / Providers → GitHub** (một số phiên bản dashboard ghi **Providers**).
6. Bật GitHub, nhập Client ID và Client Secret, kiểm callback hiển thị đúng project rồi **Save**.

Nguồn: [Supabase GitHub login](https://supabase.com/docs/guides/auth/social-login/auth-github).

## 5. Kết nối CoinSight với Supabase

Trong Supabase, mở project **Connect** hoặc **Settings → API Keys** để tìm **Project URL** và **Publishable key** (`sb_publishable_…`). Đừng lấy `sb_secret_…` hoặc `service_role`.

Trên **máy thực sự chạy API** (home server hoặc laptop dùng để thử), chỉnh `.env` hiện có. Giữ các cấu hình đang dùng và thêm:

```dotenv
SUPABASE_URL=https://wudjldnoabzngluebepw.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_WITH_YOUR_PROJECT_KEY
SUPABASE_PROVIDERS=github
AGENT_OWNER_EMAILS=YOUR_VERIFIED_GITHUB_EMAIL
```

Publishable key là cấu hình public, không phải client secret. Email owner phải đúng email API nhận từ provider, không nhất thiết là username GitHub. Chỉ thêm email bạn muốn có quyền owner.

Thay `.env` chưa đổi môi trường container đang chạy. Sau khi review đúng checkout và backup DB theo quy trình server:

```bash
git branch --show-current
git rev-parse --short HEAD
deploy/home/deploy.sh --force
```

`--force` deploy **checkout hiện tại**, không tự merge PR hay đổi sang main. Nó build/start toàn stack và chạy migrations qua service `migrate`; không phải chỉ bật nút Sign in. Chạy lệnh này trên server đích, không chạy nhầm trên laptop nếu site đang trỏ tới máy khác. Quy trình server và rollback: [home server](home_server.md), [CI/CD](deployment.md).

Kiểm cấu hình public mà không gọi LLM:

```bash
curl -fsS http://127.0.0.1:8000/v1/auth/config
```

Kết quả phải có URL project, publishable key và danh sách provider chứa `github`. Không có client secret trong response. Frontend lấy cấu hình này lúc chạy, không cần chép key vào source React.

Nguồn: [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys).

## 6. Thử GitHub login

1. Mở `http://localhost:5173` khi dùng Vite, hoặc `http://localhost:3000` khi chạy Compose. Local được hỗ trợ nếu đã thêm đúng Redirect URL. Không bắt buộc chỉ thử được trên live site.
2. Bấm **Sign in → GitHub**, cấp quyền rồi quay lại app.
3. Kiểm email và quyền owner trong app. Trong Supabase → **Authentication → Users**, user mới phải xuất hiện.
4. Hỏi một câu, reload trang, kiểm history còn đúng user. Sign out rồi kiểm quota signed-out và quyền admin bị chặn.
5. Lặp lại trên domain production. Local pass chưa chứng minh callback/tunnel production đúng.

Nếu đang giữ Cloudflare Access ở ngoài app, vẫn phải qua cổng Access trước. Supabase và Access có thể cùng tồn tại trong giai đoạn chuyển đổi.

## 7. Thêm Google sau khi GitHub hoạt động

1. Vào [Google Cloud Console](https://console.cloud.google.com/), chọn hoặc tạo một project dành cho CoinSight.
2. Mở **Google Auth Platform** (hoặc **APIs & Services → OAuth consent screen**). Trong **Branding**, đặt tên `CoinSight`, support email và contact email của bạn.
3. Trong **Audience**, chọn External nếu phục vụ người ngoài organization. Nếu đang Testing, thêm email của bạn vào **Test users**.
4. Vào **Clients → Create client** (hoặc **Credentials → Create credentials → OAuth client ID**), chọn **Web application**.
5. Authorized JavaScript origins: thêm `https://coinsight.kaiosthefox.dpdns.org`; thêm `http://localhost:5173` / `http://localhost:3000` nếu dùng local.
6. Authorized redirect URI: **`https://wudjldnoabzngluebepw.supabase.co/auth/v1/callback`**.
7. Copy Client ID và Client Secret vào Supabase → **Authentication → Sign In / Providers → Google**, bật provider và Save. Giữ các kiểm tra bảo mật mặc định; không bật skip nonce để chữa lỗi redirect.
8. Đổi `.env` thành `SUPABASE_PROVIDERS=google,github`, recreate/redeploy API theo bước 5 rồi thử Google theo bước 6.

Nguồn: [Supabase Google login](https://supabase.com/docs/guides/auth/social-login/auth-google).

## 8. Khi nào gỡ Cloudflare Access của app?

Chỉ chuyển sau khi đăng nhập trên domain production hoạt động, owner đúng và quota signed-out đã kiểm tra. Trong **Zero Trust → Access → Applications**, bỏ application bảo vệ **app hostname** `coinsight.kaiosthefox.dpdns.org`. Giữ SSH và cấu hình route/bypass docs cần thiết. **Không xóa Tunnel hoặc DNS route**: Supabase chỉ thay lớp đăng nhập, không thay kết nối tới server.

Sau chuyển đổi, visitor có thể đọc dashboard và dùng số câu miễn phí; đăng nhập mở quota theo cấu hình server. Account Access và Supabase dùng cùng email sẽ giữ user key/history. Email khác là user khác. Anonymous visitor không có history list hoặc memory dài hạn.

Nếu có sự cố, bật lại Access của app và điều tra. Không tắt JWT verification để mở đăng nhập.

## 9. Lỗi thường gặp

| Hiện tượng | Kiểm tra |
| --- | --- |
| Không mở được project Supabase | Đúng organization/account chưa? Cần chủ project mời quyền |
| Không có nút Sign in | `/api/v1/auth/config` có URL + publishable key chưa? API đã recreate chưa? |
| Provider is not enabled | Provider đã bật và Save trong Supabase; tên đã nằm trong `SUPABASE_PROVIDERS` chưa? |
| GitHub callback mismatch / Google `redirect_uri_mismatch` | Callback tại provider phải là Supabase callback, không phải domain app |
| Đăng nhập xong về sai domain | Site URL và root Redirect URL có đúng origin đang dùng không? |
| Google chỉ cho một số account vào | App đang Testing: thêm Test users hoặc hoàn tất quy trình publish/verification của Google |
| API trả 401 sau OAuth | Kiểm project URL, issuer, allowed provider và public signing keys. API hỗ trợ ES256/RS256; không dùng shared secret để bỏ qua kiểm tra |
| Có login nhưng không thấy Admin | Email từ provider phải khớp `AGENT_OWNER_EMAILS`; recreate API sau khi đổi |
| Email/password bị từ chối | Đây là policy hiện tại: chỉ Google/GitHub được chấp nhận. Đừng dùng form email sign-up để thử thay OAuth |

Client ID khác client secret; publishable key khác secret key. Mỗi giá trị ở đúng nơi trong hướng dẫn này là đủ, không cần dán credential vào chat.
