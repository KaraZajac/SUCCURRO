.PHONY: help places build meta verify conformance install-hooks site site-dev

MODULES = findtreatment summermeals hrsa headstart hud bmlt nami pflag feedingamerica ndbn \
          mutualaidhub littlefreepantry va tsml nnedv lsc mha clubhouse ccusa eoir liheap

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

places: ## build the national place registry from Census gazetteer
	python3 -m pipeline.places

build: ## run every source module, then reconcile, enrich, recount meta
	@for m in $(MODULES); do echo "== $$m"; python3 -m pipeline.$$m || exit 1; done
	python3 -m pipeline.reconcile
	python3 -m pipeline.enrich
	python3 -m pipeline.meta

meta: ## recount data/meta.yaml
	python3 -m pipeline.meta

reconcile: ## cross-source dedup by layered precedence
	python3 -m pipeline.reconcile

modules: ## print the module list (used by the refresh workflow)
	@echo $(MODULES)

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

archive: ## add Wayback archive_url to source records (--save via ARGS)
	python3 -m pipeline.archive $(ARGS)
