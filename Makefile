PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

export PYTHONPATH := scripts:$(PYTHONPATH)
export AGENT_VAULT_DIR ?= $(CURDIR)/.vault

.PHONY: install lint test check db-init mcp dashboard clean

install:
	$(PIP) install -r requirements.txt

lint:
	$(PYTHON) -m ruff check scripts

test:
	$(PYTHON) -m pytest -q scripts/tests

check: lint test

db-init:
	$(PYTHON) scripts/agent_db.py init

mcp:
	$(PYTHON) scripts/agent_mcp.py

dashboard:
	$(PYTHON) scripts/dashboard_main.py

clean:
	rm -rf .pytest_cache .vault
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
