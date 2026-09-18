.PHONY: install test cov lint demo bench docker clean

install:
	pip install -r requirements.txt

test:
	pytest -v

cov:
	pytest --cov=researcher --cov-report=term-missing --cov-fail-under=60

demo:
	python -m researcher ask "What is photosynthesis and what are its main stages?" --demo

bench:
	python -m researcher benchmark "What is photosynthesis?" --repeat 3

docker:
	docker build -t research-assistant . && docker run --rm --env-file .env research-assistant ask "What is photosynthesis?"

clean:
	rm -rf .pytest_cache .coverage htmlcov .cache __pycache__ */__pycache__ */*/__pycache__
