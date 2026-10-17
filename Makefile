.DEFAULT_GOAL := help
SCENARIO ?=

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

configure: ## Fill repo/Grafana placeholders from demo.env
	./scripts/configure-repo.sh

github-app: ## Create the agent's GitHub App (one browser click) + private key
	python3 scripts/create-github-app.py

cluster-up: ## Create the local kind cluster, ArgoCD, secrets, bootstrap apps
	./infra/kind/up.sh

cluster-down: ## Delete the local kind cluster
	kind delete cluster --name $${KIND_CLUSTER_NAME:-ai-sre}

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

agent: ## Run the agent loop locally (DRY_RUN=true make agent to rehearse)
	./scripts/run-agent.sh run

agent-selftest: ## Agent connectivity + read-only RBAC proof
	./scripts/run-agent.sh selftest

agent-status: ## Incidents in the agent's local state DB
	./scripts/run-agent.sh status

.PHONY: help configure github-app cluster-up cluster-down agent agent-selftest agent-status test baseline scenarios inject reset status verify agent-kubeconfig verify-rbac
