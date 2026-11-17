# 部署与运维手册

README 讲「怎么把它从零跑起来」，这份讲「它为什么这样跑、配置项在哪、数据存在哪、出问题怎么查」。
按顺序读一遍，你应该能在没有原作者的情况下独立维护这套部署。

- 代码里出现的包名 `newsblur_web` 是历史遗留，它同时是 Django 项目包、容器名前缀和镜像名前缀，改它要同步改 7000 多个文件里的引用，所以保留。
- 下文所有 `docker exec` 命令都可以换成 `make shell` / `make migrate` 等 Makefile 目标，两者等价。

---

## 1. 运行时拓扑

```
宿主机 :8080
  │
  └── newsblur_web            python:3.13-slim 自建镜像
        ├── gunicorn        1 worker × 16 gthread，监听 0.0.0.0:8000（容器内）
        ├── celery worker   --pool=solo -B，同进程内嵌 beat 线程
        │     ├── newsblur_db_postgres   postgres:18     127.0.0.1:5434 → 5432
        │     ├── newsblur_db_redis      redis:8.0       127.0.0.1:6579 → 6579
        │     └── newsblur_deeplx        deeplx sidecar  仅 compose 网络 1188
        └── 挂载：仓库根 → /srv/newsblur
```

| 容器 | 镜像 | 宿主端口 | 数据卷 | 职责 |
| --- | --- | --- | --- | --- |
| `newsblur_web` | 本地构建（`docker/newsblur_base_image.Dockerfile`） | `8080` → 8000 | `\${PWD}:/srv/newsblur` | Django + gunicorn + Celery worker + beat |
| `newsblur_db_postgres` | `postgres:18` | `127.0.0.1:5434` → 5432 | `docker/volumes/postgres` | 唯一的持久化数据 |
| `newsblur_db_redis` | `redis:8.0` | `127.0.0.1:6579` → 6579 | `docker/volumes/redis` | 队列、会话、缓存、抓取节流 |
| `newsblur_deeplx` | `ghcr.io/owo-network/deeplx:latest` | 无 | 无 | 一键翻译的 DeepL 代理 |

设计取舍，理解了就不会乱改：

- **一个 web 容器装两个进程。** 单用户场景下 Celery 单独开容器只会多一份 ~113 MB 的 Django 导入。代价是改任何被任务引用的代码后必须重启 worker（`make celery-restart`），见 §5.5。
- **只发布 8080。** Postgres 和 Redis 绑 `127.0.0.1`，Redis 无密码（`docker/redis/redis.conf` 里 `protected-mode no`），把它开到 `0.0.0.0` 等于把会话和队列交给整个局域网。
- **容器以你的 uid 运行**（`CURRENT_UID/CURRENT_GID`，默认 1000）。这样容器写进 bind mount 的 `logs/`、`static/`、`media/` 归你所有，不需要 `sudo chown`。代价是宿主 uid 不是 1000 时必须写 `.env`。
- **静态文件由 Django 自己发。** `static/` 是 `collectstatic` 的产物目录，`settings.STATICFILES_DIRS = [MEDIA_ROOT]`，所以不要往 `static/` 里手写文件，下次 collectstatic 会被覆盖。

### 镜像构建

`docker/newsblur_base_image.Dockerfile` 两阶段：

1. **builder**：`python:3.13-slim` + `uv`，按 `config/requirements.lock` 的哈希逐个安装（`--require-hashes`），依赖树锁定，不做解析。同时从 npm registry 取 ```esbuild/linux-x64@0.25.5` 的二进制（只装 x86_64，不跑 npm install）。
2. **runtime**：同一基础镜像，只 `apt-get install ca-certificates curl tzdata patch`，把 builder 的 site-packages 和 esbuild 复制过来。没有编译器、没有 uv、没有 git。

所以在 Apple Silicon 上构建要先 `docker buildx build --platform linux/amd64`，否则 esbuild 二进制架构不对，前端打包会在启动时失败。

---

## 2. 启动链路

容器 `Up` 之前有四段，任何一段失败的表现都不一样，按这个顺序排查最快。

| 阶段 | 做什么 | 失败表现 |
| --- | --- | --- |
| 1. compose | 拉起 postgres / redis / deeplx，`depends_on` 只保证启动顺序，**不等健康** | web 先起，连不上库 |
| 2. entrypoint | ① `media/js/modules` 比 `media/js/build/modules.js` 新 → 跑 `utils/build_modules.py` 打包 ES modules；② `static/staticfiles.json` 缺失或比 `media/css`、`media/js`、`newsblur_web/assets.yml` 旧 → 跑 `collectstatic` | 打印 `[entrypoint] ... failed` 但**不退出**，页面能开、样式或 JS 404 |
| 3. supervisor | `manage.py check_db`（每 5 秒重试，等不到只警告）→ 删残留的 `logs/gunicorn.pid` → 起 celery → 起 gunicorn | `[supervisor] check_db failed with N, starting anyway` 后照常启动 |
| 4. 守护循环 | 每 0.5 秒轮询两个子进程，每 30 秒查 celery RSS | 见下表 |

守护循环的四种动作：

| 条件 | 动作 | 为什么 |
| --- | --- | --- |
| gunicorn 退出 | 停 celery，容器以该退出码结束 | 没有 web 就没有服务，重启容器比留一个僵尸 worker 干净 |
| celery 退出 | 等 2 秒重启 celery，容器继续 | 任务超时不该把站点带下去 |
| `logs/restart-celery` 存在 | 删标记文件，重启 celery | 镜像里没有 `pkill`，用 bind mount 上的标记文件当信号，`make celery-restart` 就是 `touch` 它 |
| celery RSS > `CELERY_WORKER_MEMORY_LIMIT_MB`（默认 750） | 重启 celery | `--pool=solo` 没有 `max_memory_per_child`，只能外部看门狗 |

收到 `SIGTERM/SIGINT/SIGHUP` 时先停 gunicorn 再停 celery，各给 25 秒，超时 `kill -9`。

**已知取舍**：`check_db` 失败不阻止启动。数据库比 web 慢几秒起来时，第一次请求会 500，十几秒后自愈。如果容器一直 500，先 `make logs` 看有没有 `check_db failed`。

---

## 3. 配置

配置有三个来源，优先级从高到低：`docker-compose.yml` 的 `environment`（值来自 `.env`）→ `newsblur_web/settings.py` 里的 `os.environ.get(..., 默认值)` → 代码常量。

### 3.1 .env 可改的（compose 已透传）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CURRENT_UID` / `CURRENT_GID` | `1000` | 容器进程 uid/gid，必须等于 `id -u`，否则日志和静态文件写不进去 |
| `NEWSBLUR_PORT` | `8080` | 宿主端口，被占用时改这个 |
| `NEWSBLUR_URL` | `http://localhost:8080` | 站点对外地址。影响邮件里的链接、`settings_production` 的 cookie 与重定向 |
| `DJANGO_SETTINGS_MODULE` | `newsblur_web.settings` | 公网部署改 `newsblur_web.settings_production` |
| `SECRET_KEY` | 空（用开发默认值） | 生产必填，见 §3.4 |
| `ALLOWED_HOSTS` | 空 | 生产必填，逗号分隔，禁止 `*` |
| `CSRF_TRUSTED_ORIGINS` | 空 | 反代改域名/端口时补，逗号分隔 |
| `ATTACK_BAN_PROXY_HOPS` | `1` | 信任几层反代的 `X-Forwarded-For`，见 §8.4 |
| `ADMIN_EMAIL` / `SERVER_EMAIL` | 空 | 报错邮件收件人/发件人 |
| `EMAIL_BACKEND` / `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` | console / 空 | 默认只往 stdout 打邮件，不真发 |
| `TRANSLATE_ENABLED` | `True` | 关掉翻译按钮 |
| `TRANSLATE_ENDPOINT` / `TRANSLATE_TOKEN` / `TRANSLATE_TARGET_LANG` | deeplx sidecar / 空 / `ZH` | 见 §7 |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | `1` / `16` | 见 §10 |
| `CELERY_WORKER_MEMORY_LIMIT_MB` | `750` | 看门狗阈值 |
| `DOCKERBUILD` | `True` | 构建期标记，别动 |

### 3.2 settings.py 直接读、compose 没透传的

要改这些，要么在 `docker-compose.yml` 的 `environment` 里加一行（推荐，改完 `make up`），要么改 `settings.py`（改完 `make reload-web`）。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `STORY_RETENTION_DAYS` | `180` | 故事保留天数 |
| `STORY_RETENTION_MIN_PER_FEED` | `30` | 每个 feed 至少留多少条 |
| `STORY_RETENTION_MAX_PER_FEED` | `1000` | 每个 feed 最多留多少条 |
| `STORY_RETENTION_MAX_PER_FEED_ARCHIVE` | `10000` | archive 档的上限（个人版不启用 archive，保留字段） |
| `DAYS_OF_UNREAD` | `90` | 未读数统计窗口 |
| `PRO_MINUTES_BETWEEN_FETCHES` | `15` | 两次抓取的最小间隔 |
| `DOMAIN_FETCHES_PER_MINUTE` | `30` | 同一域名每分钟最多几次抓取 |
| `MUTED_FEED_FETCH_MINUTES` | `360` | 静音 feed 的抓取间隔 |
| `SEARCH_FREE_TEXT_INCLUDES_BODY` | `True` | 全文搜索是否搜正文，见 §6 |
| `TRANSLATION_CACHE_DAYS` | `180` | 翻译缓存保留天数 |
| `TRANSLATE_TIMEOUT` / `TRANSLATE_MAX_TEXTS` / `TRANSLATE_MAX_REQUEST_CHARS` / `TRANSLATE_CALLS_PER_MINUTE` | `25` / `60` / `12000` / `90` | 翻译限额 |

### 3.3 写死的常量

| 设置 | 值 | 能不能改 |
| --- | --- | --- |
| `TIME_ZONE` | `UTC` | **不要改**。代码里 `datetime.now()` 和 `utcnow()` 混用，改时区会让抓取间隔和历史时间线错乱 |
| `USE_TZ` | `False` | 同上，关掉时才与 `now()` 语义一致 |
| `LANGUAGE_CODE` | `zh-hans` | 可改，但要先 `python localization/manage.py compile` 生成对应 locale（仓库只带 en 和 zh-Hans） |
| `AUTO_PREMIUM` / `AUTO_PREMIUM_NEW_USERS` / `AUTO_ENABLE_NEW_USERS` | `True` | 个人版把新用户直接当高级会员；要演示免费档可关 |
| `DEBUG` | `True` | 默认开；公网部署走 `settings_production` 自动关，见 §3.4 |
| `ALLOWED_HOSTS`（开发档） | `["*"]` | 只在 `DEBUG=True` 时这样放宽，生产档会拒绝 |

### 3.4 开发档与生产档的差异

`settings_production.py` 只有几十行，全部是 `from .settings import *` 之后的重写：

| 项 | `settings.py`（开发） | `settings_production.py`（生产） |
| --- | --- | --- |
| `DEBUG` | `True` | `False` |
| `SECRET_KEY` | `personal-edition-secret-key-change-me` | 必须是环境变量且不能等于默认值，否则**拒绝启动** |
| `ALLOWED_HOSTS` | `["*"]` | 必须是环境变量，且不能包含 `*`，否则**拒绝启动** |
| Cookie/重定向 | 按 `http` 处理 | 由 `NEWSBLUR_URL` 推导：`https://` 开头才设 Secure cookie 与 HTTPS 重定向 |
| `SECURE_PROXY_SSL_HEADER` | 无 | `("HTTP_X_FORWARDED_PROTO", "https")` |
| `CSRF_TRUSTED_ORIGINS` | 空 | 默认取 `NEWSBLUR_URL` |
| `X_FRAME_OPTIONS` | 默认 | `SAMEORIGIN`（阅读器要 iframe 自己的预览） |
| `EMAIL_BACKEND` | console | SMTP，缺 `EMAIL_HOST` 时报错 |
| `CONN_HEALTH_CHECKS` | 关 | 开 |

公网部署用 `make check-deploy` 自检，它临时注入一个随机 `SECRET_KEY` 跑 `manage.py check --deploy`。**只剩两条告警是预期的**：

- `security.W004`：没开 HSTS，因为 TLS 由边缘反代终止，HSTS 头应该在反代上加。
- `security.W019`：`X_FRAME_OPTIONS=SAMEORIGIN` 而不是 `DENY`，因为阅读器要 iframe 自己的预览。

多出第三条就是配置回归，别放过。

### 3.5 改完配置怎么生效

| 改了什么 | 命令 |
| --- | --- |
| `.env` | `make up`（compose 会重建有变化的容器） |
| `docker-compose.yml` | `make up` |
| `settings.py` / 任何 `.py` | `make reload-web`（`gunicorn` 的 autoreload 默认关，见 `GUNICORN_RELOAD`） |
| `config/requirements.txt` / Dockerfile | `make build` 然后 `make up` |
| `media/css` / `media/js` | `make reload-web`，entrypoint 会重新打包和 collectstatic |

---

## 4. 数据

### 4.1 Postgres

- 库名、用户、密码都是 `newsblur`，宿主只绑 `127.0.0.1:5434`。
- 数据目录 `docker/volumes/postgres`，属主是容器内的 `postgres`（uid 999）。`docker compose down` **不会**删它。
- 40 多张表，迁移在 `apps/*/migrations/`。`apps/rss_feeds/migrations/0006_mstory_story_text.py` 会 `CREATE EXTENSION pg_trgm`，因为库用户是超级用户所以能装。
- 主要表：`feeds`（订阅源）、`rss_feeds_feeddata`（抓取元数据）、`rss_feeds_story`（故事）、`rss_feeds_mstory`（正文）、`story_tags`（用户标记/已读）、`feed_icons`、`fetch_history`（抓取日志）、`auth_user` / `profile_profile`。

进 psql：

```bash
docker exec -it newsblur_db_postgres psql -U newsblur -d newsblur
# 或者从宿主经隧道：ssh -L 5434:127.0.0.1:5434 <host> 然后 psql -h 127.0.0.1 -p 5434 -U newsblur
```

常用查询：

```sql
-- 库有多大
SELECT pg_size_pretty(pg_database_size('newsblur'));
-- 各表行数
SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 15;
-- 最近抓取失败
SELECT feed_id, COUNT(*) FROM fetch_history WHERE successful = false GROUP BY feed_id ORDER BY 2 DESC LIMIT 10;
```

> psql 会开分页器，脚本里加 `-P pager=off`。

### 4.2 Redis 的库分配

同一实例分库用，别乱 `FLUSHALL`：

| db | 用途 |
| --- | --- |
| 0 | 通用连接池、pub/sub |
| 1 | story hash（阅读器读故事走这里）、feed 读取 |
| 2 | 分析、feed 订阅缓存 |
| 3 | 统计 |
| 4 | **Celery broker** + feed 更新队列 |
| 5 | 会话（`SESSION_REDIS_DB`） |
| 6 | Django cache（`CACHES`） |
| 10 | story hash 临时 |

`appendonly yes`，数据在 `docker/volumes/redis`。清掉 db 4 会丢正在排队的抓取任务（重启后 beat 一分钟内会重新排），清 db 5 会让所有人登出，清 db 1 会让阅读器重新从 Postgres 回填故事。

### 4.3 重置

```bash
make down
sudo rm -rf docker/volumes/postgres docker/volumes/redis   # 确认路径后再执行
make up && make migrate
```

---

## 5. 后台任务

### 5.1 队列

worker 订阅四个队列（`newsblur_web/supervisor.py` 里的 `CELERY_QUEUES`）：

| 队列 | 内容 |
| --- | --- |
| `celery` | 默认队列 |
| `update_feeds` | 定期抓取 |
| `new_feeds` | 新订阅的首次抓取 |
| `archive` | 历史回填（`apps/profile/tasks.py` 的 `FetchArchiveFeeds*`）；个人版没有搜索后端，这个队列没有索引任务 |

worker 启动参数里必须带 `-Q` 列出全部四个，只订阅 `celery` 会导致「加了订阅但永远没有新故事」。

### 5.2 beat 定时表

| 任务 | 频率 |
| --- | --- |
| `task-feeds` | 1 分钟 |
| `task-broken-feeds` | 6 小时 |
| `trim-abandoned-feeds` | 24 小时 |
| `trim-stories` | 24 小时 |

beat 不是独立进程，而是 worker 里的守护线程（`newsblur_web/celeryapp.py` 的 `EmbeddedBeatThread`）：Celery 自带的 `-B` 会 fork 第二个解释器再导入一次 Django（约 110 MB），只为了每分钟往 Redis 塞几个任务名。线程版在 `scheduler.tick()` 抛异常时会重建 `Service`，不会静默停掉定时任务。

### 5.3 抓取节流

| 参数 | 默认 | 效果 |
| --- | --- | --- |
| `PRO_MINUTES_BETWEEN_FETCHES` | 15 | 同一 feed 两次抓取的最小间隔 |
| `DOMAIN_FETCHES_PER_MINUTE` | 30 | 同域名限速，防止把一个站打挂 |
| `MUTED_FEED_FETCH_MINUTES` | 360 | 静音 feed 降到 6 小时一次 |

### 5.4 故事保留

`trim-stories` 每天按 `STORY_RETENTION_DAYS`（180）删旧故事，但每个 feed 至少留 `STORY_RETENTION_MIN_PER_FEED`（30）条、最多 `STORY_RETENTION_MAX_PER_FEED`（1000）条。手动跑：

```bash
docker exec -t newsblur_web python manage.py trim_stories --days 30
docker exec -t newsblur_web python manage.py trim_stories --feed 42
```

### 5.5 改了代码要重启谁

| 改了 | 重启 |
| --- | --- |
| 视图、模板、静态资源 | 不用（`make reload-web` 只在改了 `.py` 时需要） |
| 任何被 Celery 任务引用的模块（任务、模型、抓取、打分） | `make celery-restart` |
| `settings.py`、URL 配置、`wsgi.py` | `make reload-web`（容器重启，celery 一起重启） |

忘了 `make celery-restart` 的表现是「代码改了但抓取行为没变」，很容易误判成逻辑错误。

### 5.6 手动运维命令

都在 `apps/*/management/commands/`：

| 命令 | 用途 |
| --- | --- |
| `refresh_feeds` | 批量抓取（`-f feed_id`、`-u username`、`-F` 强制、`-s` 单线程、`-d` 守护） |
| `refresh_feed` | 单 feed 抓取并打印细节（`-f` id 或 `-t` 标题） |
| `trim_stories` | 见上 |
| `trim_feeds` | 清理无订阅的 feed |
| `reconcile_feeds` | 修复订阅树与抓取队列不一致 |
| `backfill_story_text` | 回填正文（老故事缺 `story_text` 时用） |
| `calculate_scores` | 重算情报训练分数 |
| `prune_staticfiles` | 删除 `staticfiles.json` 不再引用的哈希文件 |
| `count_stories` / `count_subscribers` | 统计 |
| `remove_last_user` | 删掉最后注册的账号（测试用） |
| `generate_dev_session` | 生成开发会话 cookie（仅 `DEBUG`） |

---

## 6. 全文搜索

个人版没有 Elasticsearch。搜索走 Postgres：

- `apps/rss_feeds/migrations/0006_mstory_story_text.py` 建 `pg_trgm` 扩展和 `story_text` 字段，`0007` 建 GIN 索引。
- `SEARCH_FREE_TEXT_INCLUDES_BODY=True` 时正文参与搜索，代价是索引更大、写入更慢。
- 想只搜标题：把该变量改成 `False` 并重建索引；想彻底关掉正文：删掉 `story_text` 上的 GIN 索引（`DROP INDEX CONCURRENTLY`）。

正文是抓取时用 `trafilatura` 抽的，存在 `rss_feeds_mstory.story_text`。老故事没有正文时跑 `backfill_story_text`。

---

## 7. 翻译

阅读器里的「翻译」按钮走 `apps/reader/translation.py`，支持两个上游：

| 上游 | 说明 |
| --- | --- |
| DLX（`newsblur_deeplx` sidecar） | DeepLX 线格式，一次请求翻一批。DeepL 对匿名端点按 IP 限流，被限时全部返回 429 |
| Bing 网页翻译 | 兜底。需要从 `bing.com/translator` 抓 IG/IID 和 abuse token（缓存 45 分钟），一次翻一条，并发 6 |

`TRANSLATE_PROVIDER`：`deeplx` / `bing` / `auto`（默认）。`auto` 先试 DLX，遇到 429 后**熔断 15 分钟**不再打它，直接走 Bing。

限额：`TRANSLATE_CALLS_PER_MINUTE`（90）按分钟记账，`TRANSLATE_MAX_TEXTS`（60 条）/ `TRANSLATE_MAX_REQUEST_CHARS`（12000 字符）是单次请求上限，`TRANSLATE_TIMEOUT`（25 秒）。结果写 `TranslationCache` 表，保留 `TRANSLATION_CACHE_DAYS`（180）天。

关掉翻译：`TRANSLATE_ENABLED=False` + `make up`，按钮消失，DLX 容器可以一并注释掉。想换自建 DeepL 服务：把 `TRANSLATE_ENDPOINT` 指向任何接受 `POST {text, source_lang, target_lang}` 的地址即可。

看到 `429` 不是配置错了，是 DeepL 限流，`auto` 会自动降级；长期 429 就把 `TRANSLATE_PROVIDER` 固定成 `bing`。

---

## 8. 认证与安全

### 8.1 账号

- 注册：`/account/signup/`。`SignupForm` 要 username + email，密码可选（个人版默认无密码登录），email 会做 MX 查询，**离线环境注册会失败**，所以离线部署请用 `manage.py createsuperuser`。
- 用户创建后 `post_save` 信号自动建 `Profile`。
- 登录：`/account/login/`。
- 密码登录、会话、gReader token 三套并存，gReader 的 `Auth=` token 用 Django signing 签，30 天有效。

### 8.2 开发自动登录

`/reader/dev/autologin/<username>/`，仅当 `DEBUG=True` 且请求 host 是 `localhost` / `127.0.0.1` / `192.168.*` / `10.*` / `172.*` 时可用，其余情况 403。生产档 `DEBUG=False`，这个路由直接失效。

### 8.3 反代

生产必须让反代带上：

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

`settings_production` 靠 `X-Forwarded-Proto` 判断请求是不是 HTTPS，缺了会死循环重定向。`ALLOWED_HOSTS` 要包含真实域名，否则 Django 直接 400。

### 8.4 攻击防护

`apps/profile/middleware.py` + `utils/ip_rate_tracker.py` 按 IP 记「strikes」，越界后按 `600s → 3600s → 86400s` 三级递增封禁。`ATTACK_BAN_PROXY_HOPS` 决定从 `X-Forwarded-For` 右边数第几个地址算真实客户端（默认 1，对应一层反代）；反代层数变了必须同步改，否则要么误封反代、要么所有人共用一个 IP。

`ATTACK_BAN_DRY_RUN` 默认跟随 `DEBUG`：开发档只记录不封。生产上线前确认它是 `False`。

### 8.5 其他

- `ALLOWED_HOSTS=["*"]` 只出现在开发档。
- `DEBUG=True` 会暴露详细报错页和 `static` 直读，**不要**把开发档直接挂公网。
- `/robots.txt` 全站 `Disallow`。
- 会话是 `cached_db`：Redis db 5 存热数据，Postgres 兜底。

---

## 9. 日志与观测

| 位置 | 内容 | 轮转 |
| --- | --- | --- |
| `docker compose logs` | 所有容器 stdout，应用日志只到 `INFO` | compose 的 `json-file` 限制（见 `docker-compose.yml` 顶部 `x-logging`） |
| `logs/newsblur.log` | 应用日志，`DEBUG` 级 | 16 MB × 5 |
| `logs/errors.log` | gunicorn 错误 | 无自动轮转，异常时手动清 |
| `logs/gunicorn.pid` | gunicorn pid，启动时自动删除 | — |

**没有访问日志**：`gunicorn_conf.py` 里 `accesslog = None`，因为实测一天写 76 MB 且没有分析价值。要访问日志就在反代上开。

常用排查：

```bash
make logs                                  # 跟 web 容器
docker compose logs --tail=200 newsblur_db_postgres
docker exec -t newsblur_web grep -i "error\|traceback" logs/newsblur.log | tail -50
docker stats --no-stream                   # 内存，对照 CELERY_WORKER_MEMORY_LIMIT_MB
```

健康检查端点：

| 路径 | 返回 |
| --- | --- |
| `/health-check/` | `OK`（200） |
| `/_haproxychk` | 反代探活 |
| `/_dbcheck/postgres` | 数据库连通性 |
| `/_dbcheck/redis` | Redis 连通性 |

---

## 10. 容量与调优

内存基线（实测，单用户日常使用）：

| 进程 | RSS |
| --- | --- |
| gunicorn worker | ~130 MB，一天后基本持平 |
| celery worker | 200-400 MB，随抓取量涨 |
| postgres | 100-200 MB |
| redis | 20-50 MB |
| deeplx | 20-40 MB（compose 里 `mem_limit 192m`） |

整机 1 GB 能跑，2 GB 舒服。

- **不要加 gunicorn worker。** 每个 worker 都要完整导入 Django（~113 MB），单用户加 worker 只换来内存翻倍。并发靠 `GUNICORN_THREADS`（16）拿，实测单请求 15 ms、六并发 47 ms。
- **`max_requests=0`**：gthread worker 内存是平的，而单 worker 回收一次就是一次可见的停机。
- **celery 涨到 750 MB 会被看门狗重启**。长期频繁触发说明单次任务太重（通常是正文抽取），调 `CELERY_WORKER_MEMORY_LIMIT_MB` 或减少归档回填。
- **`MALLOC_ARENA_MAX=2`**：线程化 gunicorn + celery 会占几十个 glibc arena 且不归还，限制成 2 个能让 RSS 平稳。
- Postgres 默认参数够用；库超过几 GB 再考虑 `shared_buffers` / `work_mem`。
- 磁盘主要被 `rss_feeds_mstory.story_text` 和 `docker/volumes/` 占，控制 `STORY_RETENTION_DAYS` 和 `STORY_RETENTION_MAX_PER_FEED` 最有效。

---

## 11. 备份、升级、回滚

### 备份

```bash
make backup        # → backups/postgres-YYYYmmdd-HHMM.sql（gitignored）
```

只要这个 SQL 就够了：Redis 里的东西（队列、会话、缓存）都能重建，`docker/volumes/redis` 不必备份。定期备份建议加 cron：

```cron
0 4 * * * cd /path/to/repo && make backup && find backups -name 'postgres-*.sql' -mtime +14 -delete
```

### 恢复

```bash
make down
docker compose up -d newsblur_db_postgres
docker exec -i newsblur_db_postgres psql -U newsblur -d postgres \
  -c "DROP DATABASE IF EXISTS newsblur;" -c "CREATE DATABASE newsblur OWNER newsblur;"
docker exec -i newsblur_db_postgres psql -U newsblur -d newsblur < backups/postgres-20250101-0400.sql
make up && make migrate
```

### 升级

```bash
make backup
git pull
make build          # 只有依赖或 Dockerfile 变了才需要
make migrate
make up
```

迁移是向前兼容的（只加列不删列），所以先迁移后重启是安全的。跨大版本升级（Django 5.2 → 5.3、Postgres 17 → 18）要先看 `config/requirements.txt` 和 `docker-compose.yml` 的镜像 tag；Postgres 大版本升级不能复用旧数据目录，需要 `pg_dump` / `pg_restore`。

### 回滚

```bash
git checkout <上一个 commit>
make build && make up
```

数据库不会自动回滚。因为迁移只加不删，旧代码通常还能跑；如果新版本删了字段，就必须同时恢复备份。

---

## 12. 故障矩阵

| 症状 | 先查 | 处理 |
| --- | --- | --- |
| 8080 连不上 | `make ps` | 容器没起：`make logs` 看构建/启动错误；端口被占：改 `NEWSBLUR_PORT` |
| 页面 500，日志有 `check_db failed` | `docker compose logs newsblur_db_postgres` | Postgres 还在初始化，等 30 秒；一直失败看卷权限（`ls -ln docker/volumes`） |
| 页面能开但没样式、JS 404 | `ls static/staticfiles.json` | 删掉 `static/` 内容再 `make reload-web`，entrypoint 会重新 collectstatic |
| 加了订阅但没有新故事 | `docker exec -t newsblur_web celery -A newsblur_web inspect active` | worker 没订阅 `update_feeds`；或改了任务代码没 `make celery-restart` |
| 抓取突然变慢/停止 | `make stats` | celery 撞 750 MB 阈值被反复重启，看 `logs/` 里 `over the ...MB limit` |
| 登录后立刻掉线 | `redis-cli -p 6579 -n 5 dbsize` | 会话库被清或 Redis 没起来；`SESSION_REDIS_DB` 相关 |
| 翻译按钮报错 | `docker compose logs newsblur_deeplx` | 429 是上游限流，等熔断恢复或切 `bing` |
| 容器一启动就退出，日志只有 python REPL | `docker inspect newsblur_web --format '{{.Config.Entrypoint}}'` | 镜像默认 CMD 是 python，compose 里的 `entrypoint` 被删了 |
| 公网访问 400 Bad Request | `ALLOWED_HOSTS` | 加上真实域名，重启 |
| 公网死循环重定向 | 反代有没有传 `X-Forwarded-Proto` | 补上，见 §8.3 |
| `make migrate` 报 `permission denied` | `id -u` vs `CURRENT_UID` | 写进 `.env` |
| 改代码不生效 | 改的是不是任务代码 | `make celery-restart` |

---

## 13. 与上游 NewsBlur 的差异

这个仓库是 samuelclay/newsblur 的个人精简版，删掉的运维面不要照上游文档找：

| 上游有 | 这里 |
| --- | --- |
| Elasticsearch 全文索引 | 没有，用 Postgres `pg_trgm`（§6） |
| 多容器分离（web / task / node / nginx / haproxy） | 单 web 容器 + 内部 supervisor（§2） |
| Ansible + Consul + 多机部署 | 单机 docker compose |
| Sentry、Prometheus、Grafana | 只有文件日志和 `/health-check/` |
| 付费/会员/统计后台 | `AUTO_PREMIUM` 直接放行 |
| iOS / Android / 桌面客户端 | 已删除，只保留 web 阅读器 |
| 论坛、博客 | 已删除 |

保留的兼容面：gReader API（`/reader/api/0/`）、OPML 导入导出、情报训练、故事分享。
