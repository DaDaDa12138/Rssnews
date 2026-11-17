# Rssnews

单用户、自托管的 RSS 阅读器。源码从 [NewsBlur](https://github.com/samuelclay/newsblur) 裁剪而来（MIT），去掉托管服务的部分，保留「订阅 → 抓取 → 训练 → 阅读」这条主线，用 Docker Compose 打包成一条命令能起来的服务。

界面只有英文和简体中文（`locale/` 下只有 `en`、`zh_Hans`），默认简体中文。时间戳固定按 UTC 存储，显示层由浏览器换算。

## 目录

- [能做什么](#能做什么)
- [架构](#架构)
- [环境要求](#环境要求)
- [从零部署](#从零部署)
- [建账号与加订阅](#建账号与加订阅)
- [配置](#配置)
- [日常运维](#日常运维)
- [备份、恢复、升级](#备份恢复升级)
- [暴露到公网](#暴露到公网)
- [排错](#排错)
- [目录结构](#目录结构)
- [开发与测试](#开发与测试)
- [gReader API](#greader-api)
- [与上游的差异](#与上游的差异)
- [许可证](#许可证)

## 能做什么

- 订阅 RSS / Atom / JSON Feed，Celery beat 每分钟调度，按每个 feed 自己的抓取间隔更新
- 三栏阅读器（站点 / 标题 / 正文），原文抓取、图片代理、深浅色主题、键盘导航
- 智能训练器：对作者、标签、标题、正文关键词打分，正负反馈跨 feed 复用
- 全文搜索：标题 + 正文，走 PostgreSQL `pg_trgm`
- 收藏（star）、标签、按标签或文件夹导出 RSS
- 一键翻译：正文送进同栈的 DeepLX sidecar，结果落库缓存
- PWA 离线壳
- gReader 兼容 API：Reeder、FeedMe 这类客户端可以直接连（见 [gReader API](#greader-api)）

## 架构

web 容器里跑两套进程，外面没有 nginx，Django 自己发静态文件：

```
                     +-------------------- newsblur_web --------------------+
  浏览器 ---:8080--> | gunicorn 1 worker x 16 threads --> Django (WSGI)                  |
                     | celery worker --pool=solo + celery beat   (supervisor.py 托管)   |
                     +-------+---------------------+----------------------+--------------+
                             |                     |                      |
                     postgres:18               redis:8               deeplx（翻译）
                     127.0.0.1:5434            127.0.0.1:6579        仅 compose 内网 1188
```

| 容器 | 镜像 | 端口 | 作用 |
| --- | --- | --- | --- |
| `newsblur_web` | 本地构建，`docker/newsblur_base_image.Dockerfile` | `0.0.0.0:8080 -> 8000` | gunicorn + Celery worker + beat |
| `newsblur_db_postgres` | `postgres:18` | `127.0.0.1:5434 -> 5432` | 全部持久数据：用户、订阅、已抓取正文、评分 |
| `newsblur_db_redis` | `redis:8.0` | `127.0.0.1:6579` | 缓存、会话、未读计数、Celery 队列与调度 |
| `newsblur_deeplx` | `ghcr.io/owo-network/deeplx:latest` | 不发布 | 翻译 sidecar，内存上限 192 MB |

只有 8080 对外。Postgres 与 Redis 只绑回环地址：Redis 没设密码（`docker/redis/redis.conf` 里 `protected-mode no`），Postgres 的密码就是默认的 `newsblur`。要连数据库用 SSH 隧道，别把这两个端口开到 `0.0.0.0`。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Linux x86_64。构建阶段下载 `esbuild` 的 `linux-x64` 包，ARM 机器要先改 `docker/newsblur_base_image.Dockerfile` |
| Docker | Engine 24+，Compose v2（`docker compose version`） |
| 资源 | 2 vCPU / 2 GB 内存起步，磁盘 10 GB（镜像约 1.1 GB，再加数据库） |
| 网络 | 构建时要能访问 Docker Hub、ghcr.io、PyPI、registry.npmjs.org；运行时要能访问你订阅的 feed |
| 端口 | 8080（`NEWSBLUR_PORT`），5434 / 6579 只绑回环（`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT`）。端口被占用时改这三个变量；容器名是固定的，一台机器只跑一个实例 |
| 权限 | 当前用户在 `docker` 组，否则每条命令前加 `sudo` |

## 从零部署

最短路径：

```bash
git clone https://github.com/DaDaDa12138/Rssnews.git
cd Rssnews
cp .env.example .env
sed -i "s/^CURRENT_UID=.*/CURRENT_UID=$(id -u)/; s/^CURRENT_GID=.*/CURRENT_GID=$(id -g)/" .env
make            # docker compose up -d，首次会构建镜像，3-10 分钟
make migrate    # 建表
docker exec -it newsblur_web python manage.py createsuperuser
```

然后打开 <http://localhost:8080/>，用刚建的账号登录。

如果 `make migrate` 报连不上数据库，是 Postgres 还在初始化，等十秒重跑一次即可。

下面是把每一步拆开的版本，含验证命令。

### 1. 取代码

```bash
git clone https://github.com/DaDaDa12138/Rssnews.git
cd Rssnews
```

`static/`、`media/js/build/`、`docker/volumes/`、`logs/*.log` 都不在 git 里：前两个由容器启动时生成，后两个是运行时数据。所以第一次启动比之后慢十几秒。

### 2. 写 .env

```bash
cp .env.example .env
sed -i "s/^CURRENT_UID=.*/CURRENT_UID=$(id -u)/; s/^CURRENT_GID=.*/CURRENT_GID=$(id -g)/" .env
```

Compose 自动读同目录的 `.env` 做变量插值。`CURRENT_UID/GID` 决定容器以哪个身份写 bind mount 里的 `logs/` 和 `static/`；写错就会出现 root 拥有的文件，之后备份、清日志都会踩权限。

### 3. 起容器

```bash
make        # 等价于 docker compose up -d，首次自动 build
```

构建做三件事：`python:3.13-slim` 基础镜像；用 `uv` 按 `config/requirements.lock` 装带 hash 校验的依赖；从 npm registry 取 esbuild 0.25.5 二进制（运行阶段没有 Node）。

### 4. 建表

```bash
make migrate
```

首次建 40 多张表，并在 `apps/rss_feeds/migrations/0006_mstory_story_text.py` 里执行 `CREATE EXTENSION pg_trgm`（全文搜索用）。数据库用户就是镜像初始化时的超级用户，所以扩展装得上。

### 5. 验证

```bash
make ps
curl -fsS http://localhost:8080/health-check/                                    # OK
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/account/login/     # 200
```

`make ps` 四个容器都该是 `Up`。web 启动时先跑 `manage.py check_db` 等 Postgres 可连（每 5 秒重试），等不到会打印 `[supervisor] check_db failed with ..., starting anyway` 然后照常启动——看到这行说明数据库还没就绪，等十几秒再重试请求即可。想看启动过程用 `make logs`，正常会依次出现 `bundling ES modules`、`collecting static assets`、Celery 的 `ready`、gunicorn 的 `Listening at: http://0.0.0.0:8000`。

宿主机上确认监听：

```bash
ss -ltnp | grep -E '8080|5434|6579'
```

## 建账号与加订阅

### 建账号

两种方式，都会通过 `post_save` 信号自动建 `Profile`：

- 网页注册：<http://localhost:8080/account/signup/>
- 命令行：

```bash
docker exec -it newsblur_web python manage.py createsuperuser
```

`AUTO_PREMIUM`、`AUTO_PREMIUM_NEW_USERS`、`AUTO_ENABLE_NEW_USERS` 都是 `True`，本地实例没有付费墙，注册即可用全部功能。

> 网页注册会对邮箱域名做一次 MX 查询，纯离线或 DNS 不通的环境会提示邮件服务器不可达。离线就用 `createsuperuser`。

登录入口 <http://localhost:8080/account/login/>。未登录访问 `/` 是欢迎页，登录后同一个地址就是阅读器。

### 加订阅

阅读器左侧站点栏顶部的 **Add Site**（见 `templates/reader/feeds_skeleton.xhtml`），粘贴 feed 地址，例如：

```
https://www.ruanyifeng.com/blog/atom.xml
```

保存后由 Celery 在一分钟内调度第一次抓取，`make logs` 里能看到 `Task task-feeds[...] received`。想立刻抓某一条，在站点栏右键 feed 选 Insta-fetch。

OPML 批量导入的接口是 `POST /import/opml_upload`（multipart 字段名 `file`，需要登录会话和 CSRF token，返回 `{"code": 2}` 表示已入队）。这一版没有对应的网页入口，只能走接口。

## 配置

所有开关集中在 `.env`，改完 `docker compose up -d` 生效（只改环境变量不需要重建镜像）。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CURRENT_UID` / `CURRENT_GID` | `1000` | 容器内进程的 uid/gid，须等于宿主机用户 |
| `NEWSBLUR_PORT` | `8080` | 宿主机端口 |
| `NEWSBLUR_URL` | `http://localhost:8080` | 对外地址；邮件里的链接和 `CSRF_TRUSTED_ORIGINS` 的默认值。用 HTTPS 时必须是 `https://` |
| `DJANGO_SETTINGS_MODULE` | `newsblur_web.settings` | 换成 `newsblur_web.settings_production` 进生产姿态 |
| `SECRET_KEY` | 空 | 只有 `settings_production` 需要，且拒绝默认值 |
| `ALLOWED_HOSTS` | 空 | 逗号分隔，不能写 `*`；`settings_production` 缺它直接起不来 |
| `CSRF_TRUSTED_ORIGINS` | 空（回落 `NEWSBLUR_URL`） | 反代改写了 Host 时才需要 |
| `ATTACK_BAN_PROXY_HOPS` | `1` | 前面有几层反代，决定取哪个 `X-Forwarded-For` |
| `TRANSLATE_ENABLED` | `True` | 关掉后正文里没有翻译按钮 |
| `TRANSLATE_ENDPOINT` | `http://newsblur_deeplx:1188/translate` | 只要是 DeepLX 线格式的 `POST {text, source_lang, target_lang}` 都能换 |
| `TRANSLATE_TOKEN` | 空 | 同时作为 sidecar 的共享密钥 |
| `TRANSLATE_TARGET_LANG` | `ZH` | 目标语言 |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | `1` / `16` | 单用户一个 worker 足够，每加一个 worker 就多一份 Django 全量内存 |
| `CELERY_WORKER_MEMORY_LIMIT_MB` | `750` | supervisor 每 30 秒看一次 RSS，超了重启 worker |
| `ADMIN_EMAIL` / `SERVER_EMAIL` | `admin@localhost` | `ADMINS` / 发件人 |
| `EMAIL_BACKEND` | `...console.EmailBackend` | 默认把邮件（含重置密码链接）打到容器日志；公网实例换 SMTP |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` | 空 / `25` / 空 / 空 / `False` | SMTP 参数 |

### 没透传的开关

`newsblur_web/settings.py` 还直接读一批环境变量，但 `docker-compose.yml` 没把它们列进 `environment`，所以在 `.env` 里写它们不会生效。要用就自己在 compose 的 web 服务里加一行：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `STORY_RETENTION_DAYS` | `180` | 正文保留天数，超过由 `trim-stories` 清掉 |
| `STORY_RETENTION_MIN_PER_FEED` | `30` | 每个 feed 至少留多少条 |
| `STORY_RETENTION_MAX_PER_FEED` | `1000` | 每个 feed 最多留多少条 |
| `DAYS_OF_UNREAD` | `90` | 未读保留天数 |
| `PRO_MINUTES_BETWEEN_FETCHES` | `15` | 单个 feed 两次抓取的最小间隔 |
| `DOMAIN_FETCHES_PER_MINUTE` | `30` | 同一域名每分钟最多抓几次 |
| `MUTED_FEED_FETCH_MINUTES` | `360` | 被静音 feed 的抓取间隔 |
| `SEARCH_FREE_TEXT_INCLUDES_BODY` | `True` | 关掉后搜索只查标题，明显更快 |

### 时区

`TIME_ZONE` 固定 `UTC`，不是配置项。代码里 `datetime.now()` 和 `datetime.utcnow()` 混用，靠进程跑在 UTC 才等价；Django 启动时会把 `TIME_ZONE` 写进 `TZ` 环境变量，改成 `Asia/Shanghai` 会让已存时间戳、Redis 调度分数、`strftime('%s')` 一起偏移，而且不报错。要改显示时区就改 `Profile.timezone`。

## 日常运维

| 命令 | 做什么 |
| --- | --- |
| `make` | `docker compose up -d` |
| `make ps` | 容器状态 |
| `make logs` | 跟 web 容器日志（gunicorn + Celery + beat 混在一起） |
| `make logs SERVICE=newsblur_db_postgres` | 跟指定服务 |
| `make shell` | Django shell |
| `make migrate` | 应用迁移 |
| `make makemigrations` | 生成迁移 |
| `make check` | `manage.py check` |
| `make check-deploy` | 用生产 settings 跑 `check --deploy` |
| `make collectstatic` | 手动重建 `static/` |
| `make celery-restart` | 只重启 Celery（写 `logs/restart-celery`，supervisor 看到就循环 worker） |
| `make reload-web` | 重启整个 web 容器 |
| `make backup` | `pg_dump` 到 `backups/` |
| `make stats` | `docker stats --no-stream` |
| `make down` | 停容器，保留数据 |
| `make build` | 重建镜像（改了 `config/requirements*` 或 Dockerfile 之后） |
| `make prune` | 清掉重建留下的悬空镜像 |

**最容易踩的一条**：Celery 和 gunicorn 在同一个容器里，但各自 import 一份代码。改了任何被任务用到的东西（任务模块、模型、抓取、评分），不跑 `make reload-web` 或 `make celery-restart`，worker 会继续用旧代码，日志看起来一切正常。

日志在宿主机 `logs/`：`logs/newsblur.log`（应用，按大小轮转）、`logs/errors.log`（gunicorn 错误）、`logs/gunicorn.pid`、`logs/restart-celery`（触发文件）。容器 stdout 里只有 supervisor 和 Celery 的输出。

## 备份、恢复、升级

数据库是唯一真源，`make backup` 出纯 SQL：

```bash
make backup
ls -lh backups/                      # postgres-YYYYmmdd-HHMM.sql
```

恢复（先停写入更稳）：

```bash
make down
make up
sleep 10
docker compose exec -T newsblur_db_postgres psql -U newsblur -d newsblur < backups/postgres-20260101-0300.sql
```

冷备（连 Redis 里的会话和未读计数一起）：

```bash
make down
tar czf rssnews-data-$(date +%F).tgz docker/volumes
make up
```

升级：

```bash
git pull
make build
make up
make migrate
```

迁移按向前兼容写（新列可空、先加后收紧），但没有回滚脚本；跨大版本升级前先 `make backup`。

## 暴露到公网

单用户不等于可以裸奔。上线前至少做四件事：

1. `.env` 里把 `DJANGO_SETTINGS_MODULE` 切到 `newsblur_web.settings_production`。它关死 `DEBUG`，要求非默认 `SECRET_KEY` 和非 `*` 的 `ALLOWED_HOSTS`，缺一个就拒绝启动。
2. 生成密钥：`python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`。
3. 设 `NEWSBLUR_URL=https://rss.example.com`、`ALLOWED_HOSTS=rss.example.com`，并让反代传 `X-Forwarded-Proto`（`SECURE_PROXY_SSL_HEADER` 按这个头识别 HTTPS，`NEWSBLUR_URL` 是 https 时会开 `SECURE_SSL_REDIRECT` 和 secure cookie）。
4. 只把反代的 443 暴露出去，`8080` 改成 `127.0.0.1:8080:8000` 收回到回环。

Caddy 最省事：

```
rss.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

nginx：

```
server {
    listen 443 ssl http2;
    server_name rss.example.com;
    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

gunicorn 的 `timeout` 是 120 秒（`config/gunicorn_conf.py`），反代的读超时不要低于它，否则抓原文的慢请求会被截断。

上线后自查：

```bash
make check-deploy
curl -sI https://rss.example.com/health-check/ | head -1
```

`check-deploy` 会留两条告警：`security.W004`（HSTS 交给边缘代理）和 `security.W019`（阅读器要 iframe 自己的预览，`X_FRAME_OPTIONS` 只能是 `SAMEORIGIN`）。出现别的告警就是配置有漏。

## 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `permission denied while trying to connect to the Docker daemon` | 用户不在 docker 组 | `sudo usermod -aG docker $USER`，然后重新登录（组权限只对新会话生效） |
| `make` 报端口被占 | 8080 有别的服务 | 改 `NEWSBLUR_PORT` 后 `make up` |
| 页面能开但没样式 | `collectstatic` 失败，`static/staticfiles.json` 缺失或过期 | `docker logs newsblur_web \| grep -i static`；再手动 `make collectstatic` 看真实报错 |
| 生产模式起来就退出 | `SECRET_KEY` 或 `ALLOWED_HOSTS` 没配 | 看 `docker logs`，`settings_production` 启动时抛 `ImproperlyConfigured` |
| 访问返回 400 Bad Request | Host 不在 `ALLOWED_HOSTS` | 把实际域名加进去 |
| 登录后跳回登录页 / CSRF 校验失败 | `NEWSBLUR_URL` 与实际访问的 scheme 或 host 不一致 | 两者对齐（HTTPS 场景最容易漏） |
| 忘记密码收不到邮件 | 默认是 console backend | 链接在 `make logs` 里；或配 SMTP |
| Postgres 反复重启，日志有 `Permission denied` | `docker/volumes/postgres` 属主不是 uid 999 | `sudo chown -R 999:999 docker/volumes` |
| 改了任务代码没生效 | Celery 还在跑旧模块 | `make celery-restart`；改视图则 `make reload-web` |
| 报 `no such column` | 没跑迁移 | `make migrate` |
| 某条 feed 从来没抓过 | beat 没跑，或该 feed 被标 broken | `docker logs newsblur_web \| grep -E 'beat\|task-feeds'`；站点栏右键 Insta-fetch 强制抓一次 |
| 翻译按钮报错 | sidecar 没起，或被上游限流（429） | `docker compose logs newsblur_deeplx`；或 `TRANSLATE_ENABLED=False` 关掉 |
| 磁盘一直涨 | 正文与 Redis AOF 累积 | 调 `STORY_RETENTION_DAYS`、`STORY_RETENTION_MAX_PER_FEED`；`du -sh docker/volumes/* logs` |
| 想彻底重来 | 数据都在 bind mount 里 | `make down && sudo rm -rf docker/volumes/* static/* && make && make migrate` |

排查顺序固定：`make ps` → `docker logs newsblur_web --tail=100` → `logs/errors.log` → `logs/newsblur.log`。`/health-check/` 只证明 gunicorn 在响应，不证明 Celery 在跑。

## 目录结构

```
.
├── apps/                  Django 应用
│   ├── rss_feeds/         抓取、解析、搜索、正文抽取
│   ├── reader/            阅读器视图、评分、gReader API
│   ├── analyzer/          旧版关键词分析（保留兼容）
│   ├── profile/           用户档案、语言、健康检查
│   └── feed_import/       OPML 导入导出
├── config/                requirements.txt / requirements.lock、gunicorn 配置
├── docker/
│   ├── newsblur_base_image.Dockerfile   两阶段构建，唯一用到的镜像定义
│   ├── redis/redis.conf   Redis 配置（无密码，只靠回环保护）
│   └── volumes/           Postgres / Redis 数据（gitignored）
├── locale/zh_Hans/        翻译
├── localization/          翻译工具链与语言清单
├── media/                 静态源文件（css / js / img），collectstatic 从这里取
├── newsblur_web/         settings、urls、entrypoint、supervisor
├── static/                collectstatic 产物（gitignored，启动时生成）
├── templates/             Django 模板
├── tests/browser/         浏览器 smoke 测试
├── utils/                 日志、编码、抓取工具
├── legacy/                历史脚本，未接入当前运行路径
├── Makefile               所有运维入口
├── docker-compose.yml     四个服务
└── .env.example           配置模板
```

## 开发与测试

```bash
make check                                   # Django system check
make test                                    # 全部 apps 测试，--failfast
make test SCOPE=apps.rss_feeds ARGS="-v 2"   # 单个应用，详细输出
```

测试必须跑在容器里（宿主机没有依赖）：`make test` 实际执行的是 `docker exec -t newsblur_web python manage.py test ...`。仓库里有 52 个 `test_*.py`、400 多个测试方法。

浏览器 smoke 测试：

```bash
make smoke                 # 需要 DEBUG 打开，且本机有 Chrome
SMOKE_BASE_URL=http://localhost:8080 SMOKE_USER=demo make smoke
```

它通过 DevTools 协议驱动真实 Chrome，走 `/reader/dev/autologin/` 登录，不依赖 npm 包。

开发时的自动登录（`DEBUG=True` 且 Host 是 localhost / 127.0.0.1 / 192.168. / 10. / 172. 才可用，生产模式返回 403）：

```
http://localhost:8080/reader/dev/autologin/
http://localhost:8080/reader/dev/autologin/<username>/
```

改前端资源：源文件在 `media/`，`media/js/modules/` 里的 ES module 由 `utils/build_modules.py` 打成 `media/js/build/modules.js`，`media/` 再经 django-pipeline 压成带 hash 的 `static/` 产物。这两步 entrypoint 每次启动按 mtime 判断要不要重跑，所以改完 `make reload-web` 就够。

## gReader API

挂在 `/reader/api/0/`，是 Reeder、FeedMe 这类客户端用的那套协议。认证四种任选：`Authorization: GoogleLogin auth=<token>`、`Authorization: Bearer <token>`、`?auth=<token>`，或者已有的 Django 会话 cookie。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/login/` | 表单 `Email` + `Passwd`，返回 `SID=.. LSID=.. Auth=..` 三行纯文本 |
| GET | `/token/` | 用现有认证换新 token |
| GET | `/user-info` | 当前用户 |
| GET | `/subscription/list` | 订阅列表（含文件夹） |
| GET | `/tag/list` | 标签列表 |
| GET | `/unread-count` | 未读数 |
| GET | `/stream/contents/<stream>` | 条目流 |
| POST | `/edit-tag` | `a` / `r` 传标签，`i` 传条目 id |
| POST | `/mark-all-as-read` | `s` 传 stream id |

`<stream>` 支持 `feed/<id>`、`user/-/label/<文件夹>`、`user/-/state/com.google/starred`、`user/-/state/com.google/reading-list`。查询参数：`n`（条数，默认 20，上限 100）、`c`（偏移）、`r=o`（正序）、`it` / `xt`（包含或排除 `.../read`、`.../starred`）。

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/reader/api/0/login/ \
  -d 'Email=me@example.com&Passwd=secret' | sed -n 's/^Auth=//p')

curl -s -H "Authorization:GoogleLogin auth=$TOKEN" \
  'http://localhost:8080/reader/api/0/stream/contents/user/-/state/com.google/reading-list?n=5'
```

这套 API 只读写现有订阅，没有「加订阅」的端点：订阅走界面或 OPML。

## 与上游的差异

删掉的部分（不是漏了，是这版不做）：

- `clients/`：iOS / Android / 浏览器扩展
- `ansible/`、`blog/`、营销页、多机部署脚本
- 托管业务：付费、premium 校验、OAuth、公开 API、推送、社交（blurblog）、团队
- 监控接入（Sentry、StatsD 之类）

保留的阅读器能力：训练器、全文搜索、收藏与标签、按标签或文件夹导出 RSS、原文抓取、图片代理、PWA、翻译、gReader API。

改成单用户假设的地方：`AUTO_PREMIUM=True` 关掉付费墙，`settings.py` 默认 `DEBUG=True`、`ALLOWED_HOSTS=['*']`、`ATTACK_BAN_DRY_RUN` 跟随 `DEBUG`，适合内网；对外必须切 `settings_production`。

数据库层仍是多用户的表结构，`User` 外键到处都在，只是这版不提供配额、计费和注册限制。

## 许可证

MIT，见 [LICENSE.md](LICENSE.md)。原始版权声明保留：

```
Copyright (c) 2009 Samuel Clay, NewsBlur <samuel@newsblur.com>
```

这个仓库是裁剪与改动版，不是 NewsBlur 官方发行版，也不受其支持。

---

## 附录：给自动化部署的检查清单

按顺序执行，每步给出期望，任一步不符就停：

```bash
# 0. 依赖
docker compose version                 # v2.x
id -u; id -g                           # 与 .env 的 CURRENT_UID/GID 一致

# 1. 配置
cp .env.example .env
sed -i "s/^CURRENT_UID=.*/CURRENT_UID=$(id -u)/; s/^CURRENT_GID=.*/CURRENT_GID=$(id -g)/" .env

# 2. 启动（首次构建镜像，3-10 分钟，exit 0）
make

# 3. 四个容器都要 Up
make ps

# 4. 建表（exit 0）
make migrate

# 5. 自检
curl -fsS http://localhost:8080/health-check/                                  # OK
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/account/login/   # 200

# 6. 账号
docker exec -it newsblur_web python manage.py createsuperuser

# 7. 端到端：登录拿 token，再读条目流
curl -s -X POST http://localhost:8080/reader/api/0/login/ -d 'Email=<user>&Passwd=<pass>'   # 有 Auth= 行
```

失败时的判断顺序：

1. `docker logs newsblur_web --tail=100` 里找 `ImproperlyConfigured`（配置错）、`could not connect to server`（数据库没起来）、`ModuleNotFoundError`（镜像没重建）
2. `docker logs newsblur_db_postgres --tail=50` 里找 `Permission denied`（卷属主不对）
3. `curl -v http://localhost:8080/health-check/` 是连接被拒（gunicorn 没起）还是 502（端口映射错）
4. 页面能开但 400，是 `ALLOWED_HOSTS`；能开但没样式，是 `collectstatic`
