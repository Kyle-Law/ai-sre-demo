.DEFAULT_GOAL := help
SCENARIO ?=
ARGS ?=
STEPS_UP := 01 02 03 04 05 06 07 08 09

help: ## Show targets
	@echo "Steps (each folder has a README):"
	@for d in [0-9][0-9]-*/; do printf "  \033[36m%-22s\033[0m %s\n" "$${d%/}" "$$(sed -n '1s/^# //p' $$d/README.md)"; done
	@echo
	@echo "Targets:"
	@grep -E '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}'

step-%: ## Run a step:    make step-05 (extra args: ARGS=...)
	@d=$$(ls -d $*-*/ 2>/dev/null | head -1); test -n "$$d" || { echo "no step $*"; exit 1; }; \
	  test -x "$$d/run.sh" || { echo "step $* has no run.sh; see $$d/README.md"; exit 1; }; "./$${d}run.sh" $(ARGS)

verify-%: ## Verify a step: make verify-05
	@d=$$(ls -d $*-*/ 2>/dev/null | head -1); test -n "$$d" || { echo "no step $*"; exit 1; }; \
	  test -x "$$d/verify.sh" || { echo "step $* has no verify.sh"; exit 1; }; "./$${d}verify.sh" $(ARGS)

up: ## Steps 01-09 in order (cluster + platform; needs demo.env incl. Jira)
	@for s in $(STEPS_UP); do $(MAKE) --no-print-directory step-$$s || exit 1; done

down: ## Delete the kind cluster
	kind delete cluster --name $${KIND_CLUSTER_NAME:-ai-sre}

test: ## Offline tests (agent, alert bridge, scenarios, repo layout) in .venv
	@test -x .venv/bin/python || python3 -m venv .venv
	@.venv/bin/pip install -q -e '11-agent[test]'
	.venv/bin/python -m pytest -q 11-agent/tests 08-jira-integration/tests 13-scenarios/tests tests

baseline: ## Tag the current known-good demo app as demo-baseline
	python3 13-scenarios/demo.py baseline

scenarios: ## List failure scenarios
	python3 13-scenarios/demo.py list

inject: ## Break something: make inject SCENARIO=01-oomkilled
	@test -n "$(SCENARIO)" || (echo "usage: make inject SCENARIO=01-oomkilled" && exit 1)
	python3 13-scenarios/demo.py inject $(SCENARIO)

report: ## Incident timing table (ARGS=--detail: how each was found + phase timing)
	@kubectl -n ai-sre-agent get deploy agent-controller >/dev/null 2>&1 || { echo "agent not deployed: make step-12"; exit 1; }
	@kubectl -n ai-sre-agent exec deploy/agent-controller -- ai-sre-agent report $(ARGS)

reset: ## Restore the demo app to demo-baseline (and uncordon nodes)
	python3 13-scenarios/demo.py reset --uncordon

.PHONY: help up down test baseline scenarios inject reset report
