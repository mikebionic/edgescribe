.PHONY: setup install gui transcribe clean clean-models help

VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Full setup: venv + dependencies + model download
	@chmod +x setup.sh && ./setup.sh

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet

install: $(VENV)/bin/activate ## Install dependencies only (no model download)
	$(PIP) install -r requirements.txt --quiet

gui: ## Launch web GUI (http://localhost:7860)
	$(PY) gui.py

transcribe: ## Transcribe all audio in current directory
	$(PY) transcribe.py --input .

clean: ## Remove venv and caches
	rm -rf $(VENV) __pycache__ .pytest_cache
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

clean-models: ## Remove downloaded Whisper models (~1.5 GB)
	rm -rf ~/.cache/huggingface/hub/models--*faster-whisper*
	rm -rf ~/.cache/huggingface/hub/models--*mobiuslabsgmbh*
