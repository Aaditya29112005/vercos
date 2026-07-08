.PHONY: install lint format test local-api deploy seed clean

install:
	pip install -r requirements.txt

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

test:
	pytest tests/ --cov=src --cov-report=term-missing -vv

local-api:
	sam local start-api --template infrastructure/template.yaml --port 8080

deploy:
	sam build --template infrastructure/template.yaml && sam deploy --guided

seed:
	python scripts/seed.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -f {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
