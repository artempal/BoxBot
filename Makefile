.PHONY: setup run test deploy clean setup-local

# Setup the environment
setup:
	pip install -r boxbot/requirements.txt

# Setup local development environment
setup-local:
	python scripts/setup_dynamodb_local.py

# Run the bot locally in development mode
run:
	python scripts/run_local.py

# Run tests
test:
	pytest tests/ --cov=boxbot --cov-report=term-missing

# Build deployment package
build:
	mkdir -p dist
	pip install -r boxbot/requirements.txt -t dist/
	cp -r boxbot dist/
	cd dist && zip -r ../deployment.zip .

# Deploy to AWS Lambda (requires AWS CLI to be configured)
deploy: build
	aws lambda update-function-code \
		--function-name BoxBot \
		--zip-file fileb://deployment.zip

# Set up webhook for production
setup-webhook:
	python -m boxbot.lambda.setup_webhook

# Clean up build artifacts
clean:
	rm -rf dist
	rm -f deployment.zip
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf .coverage
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete 