.PHONY: run discover assets assets-all paper paper-all check check-all analysis analysis-all

run:
	uv run snakemake -j 1 run_example

discover:
	uv run truthweave discover

assets: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave build-paper-assets --paper $(PAPER)

assets-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Building assets for $$paper"; \
		uv run truthweave build-paper-assets --paper $$paper; \
	done

paper: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave build-paper --paper $(PAPER)

paper-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Building paper for $$paper"; \
		uv run truthweave build-paper --paper $$paper; \
	done

check: discover
	@if [ -n "$(PAPER)" ]; then uv run truthweave check --paper $(PAPER); else uv run truthweave check; fi

check-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Checking $$paper"; \
		uv run truthweave check --paper $$paper; \
	done

analysis:
	@if [ -z "$(NAME)" ]; then echo "Set NAME=<analysis_name>"; exit 1; fi
	@if [ -n "$(RUN_ID)" ]; then \
		uv run python -m truthweave.analysis.$(NAME) --run_id $(RUN_ID); \
	else \
		uv run python -m truthweave.analysis.$(NAME); \
	fi

analysis-all:
	@for name in $$(uv run python -c 'from pathlib import Path;print(" ".join([p.stem for p in Path("src/truthweave/analysis").glob("*.py") if p.name != "__init__.py"]))'); do \
		echo "Running analysis $$name"; \
		uv run python -m truthweave.analysis.$$name; \
	done
