# Personal-edition newsblur: four containers, gunicorn on :8080.
#
# Every target shells out to "docker compose", so your user has to be allowed to
# talk to the Docker daemon. Add yourself to the docker group once and start a new
# login session (group membership is only picked up by new sessions):
#   sudo usermod -aG docker "$USER"

COMPOSE := docker compose
WEB     := newsblur_web
SERVICE ?= newsblur_web
SCOPE   ?= apps
ARGS    ?= --noinput -v 1 --failfast

.PHONY: default up down restart ps logs web-logs celery-restart reload-web stats \
        shell migrate makemigrations check check-deploy collectstatic backup build prune smoke test

default: up

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100 $(SERVICE)

web-logs:
	$(COMPOSE) logs -f --tail=100 $(WEB)

# Celery shares the web container but imports its own copy of the code. Restart it
# after touching anything a task imports: task modules, models, feed fetching,
# scoring. The supervisor watches for this marker file and cycles the worker.
celery-restart:
	touch logs/restart-celery

# The web container runs one gunicorn worker with auto-reload off (the
# reloader doubles the module set). Restart it after editing Python. This also
# restarts the Celery worker, which lives in the same container.
reload-web:
	docker restart $(WEB)

# Per-container memory, for comparing against backups/baseline/docker-stats.txt.
stats:
	docker stats --no-stream

shell:
	docker exec -t $(WEB) python manage.py shell

migrate:
	docker exec -t $(WEB) python manage.py migrate

makemigrations:
	docker exec -t $(WEB) python manage.py makemigrations

check:
	docker exec -t $(WEB) python manage.py check

# Same defaults as the development guidelines: make test SCOPE=apps.rss_feeds ARGS="-v 2"
test:
	docker exec -t $(WEB) python manage.py test $(SCOPE) $(ARGS)

# Django's deploy checks against the production profile. Two warnings stay on
# purpose: HSTS is served by the edge proxy (security.W004) and the reader frames
# its own previews, so framing has to stay SAMEORIGIN (security.W019). See
# docs/DEPLOYMENT.md. Anything else appearing here is a regression.
check-deploy:
	docker exec -t $(WEB) env \
		DJANGO_SETTINGS_MODULE=newsblur_web.settings_production \
		SECRET_KEY=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))') \
		ALLOWED_HOSTS=$${ALLOWED_HOSTS:-newsblur.example.com} \
		NEWSBLUR_URL=$${NEWSBLUR_URL:-https://newsblur.example.com} \
		python manage.py check --deploy

collectstatic:
	docker exec -t $(WEB) python manage.py collectstatic --noinput

# Dumps land in backups/, which is gitignored.
backup:
	@mkdir -p backups
	docker exec -t newsblur_db_postgres pg_dump -U newsblur newsblur > backups/postgres-$$(date +%Y%m%d-%H%M).sql
	
# Browser smoke tests against the running stack. Real Chrome over the DevTools
# protocol, no npm dependency. Needs the reader on :8080 with DEBUG on, since it
# signs in through /reader/dev/autologin/ (apps/reader/views/pages.py).
smoke:
	node tests/browser/smoke.mjs

# Rebuilds the python image after config/requirements.txt or the Dockerfile change.
build:
	$(COMPOSE) build $(WEB)

# Every rebuild retags newsblur_python3:latest and leaves the previous image behind
# as a dangling one. This drops those layers; the running image and the base image
# it was built from stay.
prune:
	docker image prune -f
