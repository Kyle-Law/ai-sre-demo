#!/usr/bin/env bash
# Agent self-test: Kubernetes, Grafana, Jira and GitHub connectivity, plus the RBAC matrix,
# all from the agent's own credentials (agent.env + agent.kubeconfig).
exec "$(dirname "$0")/run.sh" selftest
