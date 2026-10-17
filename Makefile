.DEFAULT_GOAL := help
SCENARIO ?=

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

configure: ## Fill repo/Grafana placeholders from demo.env
	./scripts/configure-repo.sh

test: ## Run all offline tests (agent, alert bridge, scenarios, manifests)
	python3 -m pytest -q agent/tests tests

baseline: ## Tag the current known-good apps/shop as demo-baseline
	python3 scenarios/demo.py baseline

scenarios: ## List failure scenarios
	python3 scenarios/demo.py list

inject: ## Break something: make inject SCENARIO=01-oomkilled
	@test -n "$(SCENARIO)" || (echo "usage: make inject SCENARIO=01-oomkilled" && exit 1)
	python3 scenarios/demo.py inject $(SCENARIO)

reset: ## Restore apps/shop to demo-baseline (and uncordon nodes)
	python3 scenarios/demo.py reset --uncordon

status: ## Scenario + pod status
	python3 scenarios/demo.py status

verify: ## Pre-show platform health check (admin kubeconfig)
	./scripts/verify-platform.sh

agent-kubeconfig: ## Mint the read-only agent kubeconfig (admin kubeconfig)
	./scripts/generate-agent-kubeconfig.sh --out agent.kubeconfig

verify-rbac: ## Prove the agent kubeconfig is read-only
	KUBECONFIG=agent.kubeconfig ./scripts/verify-rbac.sh

.PHONY: help configure test baseline scenarios inject reset status verify agent-kubeconfig verify-rbac
