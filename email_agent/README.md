# email_agent — 每日邮件摘要

每天早上 07:00（新加坡时间）自动读取 **Gmail** 和 **NUS 邮箱**过去 24 小时的所有新邮件，用 Claude 分类、摘要、排优先级，然后把一封合并的摘要邮件发到你的 Gmail。

```
GitHub Actions (cron) → Gmail (IMAP) + NUS (Microsoft Graph)
                      → 去重 / 清洗正文 → Claude 结构化摘要 → HTML → Gmail SMTP
```

摘要内容：
1. **今日重点**：3-5 条
2. **🔴 需要你处理**：截止日期、来自哪个邮箱、原邮件链接
3. **按类别分组**：课程-学校 / 工作-研究 / 财务-账单 / 通知-系统 / Newsletter / 推广，每封一句话
4. 底部：各邮箱封数、推广折叠数、抓取错误提醒（如 NUS 登录过期）

邮件只读，不会被标为已读。某个邮箱出错时另一个照常摘要；Claude 不可用时退化为只列标题。

## 一次性设置

### 1. Gmail App Password
1. 打开 Google 账号的两步验证：https://myaccount.google.com/security
2. 生成 App Password：https://myaccount.google.com/apppasswords （名字随便填，如 `email_agent`）
3. 记下 16 位密码 → 读邮件 (IMAP) 和发摘要 (SMTP) 都用它。

### 2. NUS 邮箱（Microsoft 365）
Microsoft 365 已不支持用密码登录 IMAP，所以需要 OAuth：

1. 用任意 Microsoft 账号登录 https://portal.azure.com → **App registrations** → **New registration**
   - Supported account types：**Accounts in any organizational directory and personal Microsoft accounts**
   - Redirect URI：留空
2. 创建后进入该 app：
   - **Authentication** → *Allow public client flows* → **Yes** → Save
   - **API permissions** → Add → Microsoft Graph → Delegated → `Mail.Read`（`offline_access` 自动包含）
   - 复制 **Application (client) ID**
3. 在你自己电脑上运行（只需一次）：
   ```bash
   pip install msal
   NUS_CLIENT_ID=<上一步的 client id> python -m email_agent.scripts.login_nus
   ```
   按提示打开 https://microsoft.com/devicelogin，输入代码，用 NUS 账号（`exxxxxxx@u.nus.edu`）登录并同意授权。
4. 终端会打印一长串 refresh token → 存为 secret `NUS_REFRESH_TOKEN`。

> refresh token 每天被使用就会持续有效；若超过约 90 天没跑或你改了 NUS 密码，摘要底部会提示“NUS 抓取失败”，重新做第 3 步即可。

#### Plan B：NUS 不允许授权时
如果登录时提示 *Need admin approval*（NUS IT 未批准第三方 app），改用转发：
NUS Outlook 网页版 → 设置 → 邮件 → 转发 → 转发到你的 Gmail，并勾选“保留转发邮件的副本”。
然后不用设置 `NUS_*` secrets，摘要会从 Gmail 里一起读到 NUS 邮件。

### 3. GitHub Secrets
仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret | 值 |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com 生成 |
| `GMAIL_USER` | `samsonchewjunjie@gmail.com` |
| `GMAIL_APP_PASSWORD` | 第 1 步的 16 位密码 |
| `NUS_CLIENT_ID` | 第 2 步的 client id |
| `NUS_REFRESH_TOKEN` | 第 2 步打印的 token |
| `DIGEST_TO` | 收摘要的地址（不填默认发到 `GMAIL_USER`）|

### 4. 启用定时任务
GitHub 的定时 (`schedule`) workflow **只在默认分支 (main) 上运行**。代码在 `email_agent` 分支开发，合并进 `main` 后定时任务才会生效。
合并后到 Actions → *email-agent daily digest* → **Run workflow** 手动跑一次验证。

## 可选环境变量
| 变量 | 默认 | 说明 |
|---|---|---|
| `DIGEST_MODEL` | `claude-opus-5-5` | 摘要用的模型 |
| `DIGEST_EFFORT` | `medium` | `low` 更省钱，`high` 更细 |
| `DIGEST_HOURS` | `24` | 回看窗口 |
| `DIGEST_TZ` | `Asia/Singapore` | 摘要日期时区 |
| `DIGEST_MAX_BODY_CHARS` | `4000` | 每封正文截断长度 |
| `DIGEST_BATCH_SIZE` | `60` | 每次请求的邮件数，超过会分批再合并重点 |

## 成本
约 50–80 封/天 ≈ 每天 $0.3–0.4（≈ $10/月，Claude Opus 5.5）。

## 本地运行
```bash
pip install -r email_agent/requirements.txt
python -m pytest email_agent/tests -q

# 用假邮件，不调 Claude，生成 digest.html 预览
python -m email_agent.main --dry-run --no-llm --fixtures email_agent/tests/fixtures

# 真邮箱 + Claude，但不发送（先 export 上面的环境变量）
python -m email_agent.main --dry-run --hours 48
```

## 代码结构
| 文件 | 作用 |
|---|---|
| `main.py` | 入口：抓取 → 去重 → 摘要 → 渲染 → 发送 |
| `sources/imap_source.py` | Gmail（通用 IMAP，只读）|
| `sources/graph_source.py` | NUS via Microsoft Graph |
| `parser.py` | MIME/HTML → 纯文本，去引用历史 |
| `summarizer.py` | Claude 结构化输出 + prompt |
| `render.py`, `templates/digest.html.j2` | HTML 摘要 |
| `smtp_sender.py` | Gmail SMTP 发送 |
| `scripts/login_nus.py` | NUS 一次性登录 |
