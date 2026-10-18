#!/usr/bin/env bash
# Agent self-test from this machine: Grafana, Jira and GitHub with agent.env's credentials.
# Kubernetes access and the RBAC matrix are checked inside the cluster: make verify-12 ARGS=--selftest
exec "$(dirname "$0")/run.sh" selftest
