#!/usr/bin/env bash
# Step 06: the demo app ("checkout" in namespace shop) inside a restricted AppProject.
source "$(dirname "$0")/../lib/common.sh"
need_context
need_pushed 06-demo-app

step "AppProject 'shop' (guardrail) + Application 'shop'"
kubectl apply -f 06-demo-app/appproject.yaml
kubectl apply -f 06-demo-app/application.yaml
wait_app shop 300
kubectl -n shop get deploy,pods,svc

cat <<EOF

Try the app:  kubectl -n shop port-forward svc/checkout 9898:80   ->  http://localhost:9898
Next: make verify-06, then make step-07
EOF
