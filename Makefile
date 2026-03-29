.PHONY: run discover assets assets-all refs refs-all provenance provenance-all profile profile-all claims claims-all packet packet-all verify verify-all review review-all paper paper-all check check-all analysis analysis-all benchmarks exemplars

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

refs: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave sync-refs --paper $(PAPER)

refs-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Syncing refs for $$paper"; \
		uv run truthweave sync-refs --paper $$paper; \
	done

provenance: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave provenance-report --paper $(PAPER) --format md

provenance-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Building provenance ledger for $$paper"; \
		uv run truthweave provenance-report --paper $$paper --format md; \
	done

profile: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave profile-report --paper $(PAPER) --format md

profile-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Building profile report for $$paper"; \
		uv run truthweave profile-report --paper $$paper --format md; \
	done

claims: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave claim-report --paper $(PAPER) --format md

claims-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Building claim ledger for $$paper"; \
		uv run truthweave claim-report --paper $$paper --format md; \
	done

packet: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave reviewer-packet --paper $(PAPER) --format md

packet-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Building reviewer packet for $$paper"; \
		uv run truthweave reviewer-packet --paper $$paper --format md; \
	done

verify: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave verify-paper --paper $(PAPER) --format md

verify-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Verifying $$paper"; \
		uv run truthweave verify-paper --paper $$paper --format md; \
	done

review: discover
	@if [ -z "$(PAPER)" ]; then echo "Set PAPER=<paper_id>"; exit 1; fi
	uv run truthweave review-thread --paper $(PAPER) --phase draft_reviewed --format md

review-all: discover
	@for paper in $$(uv run python -c 'import json;print(" ".join([p["paper_id"] for p in json.load(open("artifacts/manifests/papers_index.json"))["papers"]]))'); do \
		echo "Reviewing thread for $$paper"; \
		uv run truthweave review-thread --paper $$paper --phase draft_reviewed --format md; \
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

benchmarks:
	uv run truthweave benchmark-contracts --format md

exemplars: discover
	@for paper in finance_exemplar formal_methods_exemplar; do \
		echo "Validating exemplar $$paper"; \
		uv run truthweave validate-profile --paper $$paper; \
		uv run truthweave build-paper --paper $$paper; \
	done
