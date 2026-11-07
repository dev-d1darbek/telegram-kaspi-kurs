.PHONY: help install run test lint format docker-build docker-up docker-down clean

help:
	@echo "Қолжетімді командалар:"
	@echo "  make install       — тәуелділіктерді орнату"
	@echo "  make run           — ботты іске қосу"
	@echo "  make test          — тесттерді жүргізу"
	@echo "  make lint          — линтер"
	@echo "  make format        — кодты форматтау"
	@echo "  make docker-up     — Docker контейнерді іске қосу"
	@echo "  make docker-down   — Docker контейнерді тоқтату"
	@echo "  make clean         — уақытша файлдарды тазалау"

install:
	pip install --upgrade pip
	pip install -r requirements.txt

run:
	python main.py

test:
	pytest -v

lint:
	ruff check .

format:
	black .

docker-build:
	docker compose build

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info