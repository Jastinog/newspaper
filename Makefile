# Run project
run:
	uv run python manage.py makemigrations
	uv run python manage.py migrate
	uv run python manage.py collectstatic --no-input --clear >> /dev/null
	uv run python manage.py runserver 0.0.0.0:8002

# Initialize initial data
init:
	uv run python manage.py inituser
	uv run python manage.py initcore

# Run migrations only
migrate:
	uv run python manage.py makemigrations
	uv run python manage.py migrate

# Run tests
test:
	uv run python manage.py test

# Clean cache
clean:
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete

# Create superuser
superuser:
	uv run python manage.py createsuperuser

# Code formatting and linting with auto-fix
check:
	uv run black .
	uv run ruff check . --fix

# Install dependencies
install:
	uv sync

# Install production dependencies only
install-prod:
	uv sync --no-dev

# Update lock file
lock:
	uv lock

# Update all packages
update:
	uv lock --upgrade
	uv sync

# Add a new dependency (usage: make add p=<package>)
add:
	uv add $(p)

# Add a dev dependency (usage: make add-dev p=<package>)
add-dev:
	uv add --dev $(p)

# Clean old analytics data
analytics-cleanup:
	uv run python manage.py analytics_cleanup

# Activate virtual environment
shell:
	. .venv/bin/activate && exec $$SHELL
