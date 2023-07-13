.PHONY: vet

.SILENT:

vet: ## Run linters, auto-formaters, and other tools
	black handler.py
	flake8 --max-line-length=88 handler.py
	isort --force-single-line-imports handler.py