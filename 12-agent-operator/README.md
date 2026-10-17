# 12 · Agent operator: the agent inside the cluster

**Goal:** run the same agent as step 11, but as a Kubernetes controller. Each Jira ticket becomes
an **AgentSession** resource, and every LLM diagnosis runs as its own short-lived **Job** that holds
no write credentials at all.

```
ns ai-sre-agent                                   ns ai-sre
┌──────────────────────────────┐   creates        ┌───────────────────────────────┐
│ Deployment agent-controller  │ ───────────────▶ │ Job diagnose-sup-1-…          │
│  polls Jira every 20s        │                  │  SA ai-sre-agent (read-only)  │
│  AgentSession per ticket     │ ◀── reads logs ─ │  Claude + kubectl/PromQL/git  │
│  validates, then writes:     │   (Diagnosis)    │  prints one Diagnosis, exits  │
│  Jira comments, GitHub PR    │                  │  no Jira / GitHub credentials │
└──────────────────────────────┘                  └───────────────────────────────┘
```

## Concepts

- **Controller vs investigator.** The controller ([ai_sre_agent/incluster.py](../11-agent/ai_sre_agent/incluster.py))
  is plain code: it polls Jira, keeps state, and does every write (Jira comments, the PR). The LLM
  only runs in the investigator Job, which gets the model key and a Grafana *Viewer* token, and
  reads the public repo anonymously. A prompt-injected investigator has nothing it can write with.
- **A session per ticket = a resource, not a pod.** A ticket can wait hours for human review, and
  that needs no LLM. The controller handles waiting for review, merge, ArgoCD sync and verification
  itself, and starts a Job only when thinking is needed (first diagnosis, one retry). State lives in
  the AgentSession's `.status` ([manifests/crd.yaml](manifests/crd.yaml)), so it survives controller
  restarts and `kubectl get agentsessions` is the incident board.
- **The controller is a way in, so it's fenced.** It may create Jobs in `ai-sre`, and anything that
  can create a Job could run it as any ServiceAccount there. The **ValidatingAdmissionPolicy**
  ([manifests/admission-policy.yaml](manifests/admission-policy.yaml)) pins every Job in `ai-sre` to
  the read-only ServiceAccount, the agent image, only the `investigator-credentials` Secret and only
  emptyDir volumes. It applies to everyone, cluster admins included.
- **It must work while the cluster is broken.** In scenario 06 the only node is cordoned, so new
  pods can't schedule, including a diagnosis Job. Both the controller and the Jobs tolerate
  `node.kubernetes.io/unschedulable` and run with the `ai-sre-critical` PriorityClass.
- **Context.** Each ticket starts in a fresh LLM session, which keeps context small by design. The
  diagnosis loop caches its prompt prefix across turns (`cache_control`) and clears stale tool output
  on long runs (context editing, `clear_tool_uses_20250919`).
- **No registry.** `run.sh` builds `ai-sre-agent:dev` from [11-agent/Dockerfile](../11-agent/Dockerfile)
  and loads it into the kind node with `kind load docker-image`.

## Run

Steps 08–11 first (Jira, read-only access, GitHub App, a working `agent.env`). **Stop the local agent
(step 11)**: both would pick up the same tickets. Tickets the local agent already handled are recorded
only in its local `.agent/state.db`, so close them in Jira first.

```bash
DRY_RUN=true make step-12     # rehearse: diagnoses and logs, writes nothing to Jira/GitHub
make verify-12                # deployment, admission policy, RBAC for both identities
make verify-12 ARGS=--selftest   # (or ./12-agent-operator/verify.sh --selftest)
make step-12                  # for real (re-run after changing agent.env or the agent code)
```

## Look around

```bash
kubectl -n ai-sre-agent get agentsessions -w                  # incident board, live
kubectl -n ai-sre-agent get agentsession sup-1 -o yaml        # one incident's full state
kubectl -n ai-sre-agent logs deploy/agent-controller -f       # controller + audit events
kubectl -n ai-sre get jobs,pods -l app=ai-sre-investigator    # diagnosis Jobs
kubectl -n ai-sre logs job/<diagnose-…>                       # every tool call the model made
kubectl -n ai-sre create job rogue --image=busybox -- true    # denied by the admission policy
```

Then run a scenario from step 13 and watch an AgentSession appear and move through
`DIAGNOSING → PR_OPEN → MERGED → SYNCED → VERIFIED`.

**Back to local mode:** `kubectl -n argocd delete application agent-operator` (ArgoCD prunes the
controller), then `make step-11`.

**Next:** [13 · Failure scenarios](../13-scenarios/)
