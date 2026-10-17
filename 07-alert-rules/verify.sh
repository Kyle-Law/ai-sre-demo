#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

rules_json() { grafana_api /api/prometheus/grafana/api/v1/rules; }
five_rules_loaded() {
  [[ "$(grafana_api /api/v1/provisioning/alert-rules | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')" -ge 5 ]]
}
no_rule_errors() {
  rules_json | python3 -c '
import sys, json
rules = [r for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"]]
sys.exit(0 if rules and all(r["health"] == "ok" for r in rules) else 1)'
}

echo "Alert rules"
check "ArgoCD app 'alert-rules' Synced/Healthy" app_healthy alert-rules
check "ConfigMap ai-sre-alert-rules labelled grafana_alert=1" kubectl -n monitoring get cm ai-sre-alert-rules -l grafana_alert=1 -o name
check "Grafana loaded 5 rules" five_rules_loaded
check "every rule evaluates without error" no_rule_errors
summary
echo
rules_json | python3 -c '
import sys, json
for g in json.load(sys.stdin)["data"]["groups"]:
    for r in g["rules"]:
        print(f"  {r[\"name\"]:28} {r[\"state\"]:9} health={r[\"health\"]}")'
