# ------------------------------------------------------------------------------
# Color definitions
# ------------------------------------------------------------------------------
RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[0;33m
BLUE   := \033[0;34m
BOLD   := \033[1m
RESET  := \033[0m

# ------------------------------------------------------------------------------
# Help content
# ------------------------------------------------------------------------------
define HELP
$(BOLD)Manage narrio Usage:$(RESET)

  $(GREEN)make clean$(RESET)        		Clean Python compiled bytecode files.
  $(GREEN)make generate-secret$(RESET)        	Generate a new secret key.
  $(GREEN)make create-migration$(RESET)        	Create a new migration.
  $(GREEN)make migrate$(RESET)        		Migrate the database.
  $(GREEN)make test-coverage$(RESET)        	Run Django tests and generate coverage report.
  $(GREEN)make test$(RESET)        		Run Django tests.
  $(GREEN)make start-local$(RESET)        	Start the local serivces.
  $(GREEN)make stop-local$(RESET)        	Stop the local services.
  $(GREEN)make all$(RESET)          		Show help.
endef

export HELP

# ------------------------------------------------------------------------------
# Targets
# ------------------------------------------------------------------------------
help:
	@echo "$$HELP"

.PHONY: help generate-secret clean-migrations clean-pyc lambda-build lambda-push lambda-deploy lambda-deploy-all lambda-status

generate-secret: # Generates Django Secret Key
	python -c "import secrets; print(secrets.token_urlsafe())"

test-coverage: # Execute tests and generate coverage report
	coverage run --source='.' manage.py test
	coverage html

clean-migrations: # Clean existing migrations from all applications
	find ./narrio -path "*/migrations/*.py" -not -name "__init__.py" -not -name "*_load_initial_*.py" -delete
	find ./narrio -path "*/migrations/*.pyc" -delete

clean: # Clean Python compiled bytecode files"
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '.pytest_cache' -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "Finished cleaning."

openapi-generate-swagger: # Generate OpenAPI swagger schema
	python manage.py spectacular --file ./api/swagger.yaml

start-local: # Start local environment containers
	 docker compose -f docker-compose.yml up -d --build

stop-local: # Stop local environment containers
	 docker compose -f docker-compose.yml down --remove-orphans

clean-local: # Clean local environment containers
	docker compose -f docker-compose.yml down -v --remove-orphans

precommit-install: # Install pre-commit hooks
	python3 -m pre_commit install

precommit-run: # Run all pre-commit hooks manually
	python3 -m pre_commit run --all-files

test: # Run Django tests (reuses test DB for speed)
	python manage.py test --keepdb

test-fresh: # Run Django tests (recreates test DB from scratch)
	python manage.py test --noinput