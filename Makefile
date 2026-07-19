.PHONY: help places verify conformance install-hooks site site-dev

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

places: ## build the national place registry from Census gazetteer
	python3 -m pipeline.places

verify: ## full validation gate: schema conformance + referential integrity + freshness
	python3 -m pipeline.validate

conformance: ## JSON Schema conformance only
	python3 -m pipeline.validate --conformance-only

install-hooks: ## enable the pre-commit gate on data/ changes
	git config core.hooksPath .githooks

site: ## build the static site
	cd site && npm run build

site-dev: ## run the site dev server
	cd site && npm run dev
