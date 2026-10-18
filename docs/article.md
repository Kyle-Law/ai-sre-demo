# I gave an AI agent read only access to my Kubernetes cluster. Here's what happened.

*It found the bad commit, wrote the fix and opened a pull request in under a minute. It still couldn't merge it, and that's the whole point.*

I've been an old school Kubernetes user for a while. I do everything through kubectl. I look up fields with `kubectl explain`, I memorise the short names for every resource, and I spend a lot of evenings in the official docs. That's how I learned, and honestly I still enjoy it.

But this year AI agents got good. Really good. Over the past six months they went from "fun to chat with" to "can actually drive a terminal". So I kept asking myself the same question: if an agent can do all of this, do I still need to know Kubernetes?

I don't think the answer is a simple yes or no. So I built something to find out.

## Where AI actually helps

Think about the last incident you were paged for. An alert fires, you open your laptop, and then you do the same thing you always do. Get the pods. Describe the broken one. Read the logs. Check the events. Look at what changed in git recently. Only after all that do you start thinking.

"When an alert fires, the first 15 minutes of an incident are often consumed by the same mechanical investigative steps." That line is from Boris Tane in Chapter 10 of *Observability Engineering*, and it stuck with me.

Those first minutes are routine, and they're exactly where downtime hurts most, because the SLA clock is already running. That felt like the right place to bring in an agent. Not to replace the engineer, just to do the legwork so that when a human looks at the problem, the evidence is already there.

## The idea in one sentence

The agent gets **read only eyes** and **git only hands**.

It can look at anything it needs to diagnose a problem, but it can't change the cluster. The only way it can fix something is by opening a pull request, which a human reviews and merges. Then ArgoCD applies it, like any other change.

Here's the whole setup:

![Architecture](architecture.png)

1. The app breaks because of a realistic bad commit.
2. A Grafana alert fires.
3. A small bridge turns the alert into a Jira ticket.
4. The agent picks up the ticket, investigates and posts the root cause.
5. It opens a GitHub pull request with the fix. A human reviews it and merges it.
6. ArgoCD syncs the change. The agent checks the alert is gone and closes the ticket.

Everything runs on my laptop in a kind cluster, with Cilium for networking, ArgoCD for GitOps, Prometheus and Grafana for monitoring, Jira for tickets, and Claude as the model.

## Let's walk through a real incident

I'll break something on purpose. I push a commit that moves the readiness probe of the `checkout` app to the wrong port. It looks like a harmless config tweak. Nobody would blink at it in a busy week.

ArgoCD rolls it out. The new pods never become ready, so the rollout gets stuck. Kubernetes protects us here because the old pods keep serving traffic, but the deployment is broken and nobody knows yet.

After a minute Grafana fires `DeploymentRolloutStuck`, and the bridge opens a Jira ticket with the alert details.

Now the agent takes over. It picks up the ticket, moves it to Pending so everyone knows it's being worked on, and starts investigating. This is where it gets interesting, because the agent writes down every step, with timestamps:

```
+  2s  kubectl get pods in namespace shop
+  5s  kubectl describe pod (readiness probe failing)
+  9s  recent commits touching the app manifests
+ 12s  diff of the most recent commit
```

Then it posts its findings on the ticket. The root cause, the exact commit and its author, the evidence, and a short story of how it got there: "the new pods fail their readiness probe, the probe changed in the last commit, the app doesn't listen on that port". You can check that story against the real tool calls right below it. I like that a lot. It's not "trust me", it's "here's what I looked at".

Then it opens a pull request that puts the probe back on the right port, along with an incident record in the repo.

I review the PR and merge it. ArgoCD picks it up within 30 seconds. The agent waits until the deployment has been healthy and the alert has been quiet for 90 seconds, then it posts a closing comment and moves the ticket to Done.

Here's where the time went on that incident:

* Alert to pull request: **49 seconds**
* Me reviewing and merging: **5 minutes 19 seconds**
* Merge to verified: **2 minutes 5 seconds**
* Total MTTR: **8 minutes 13 seconds**

Under three minutes of that was the agent. The rest was me reading the PR. And that's the part I *want* to keep, because that's the human judgment.

## When it can't fix something

Not every problem lives in git. One of my scenarios cordons the only node, so no new pods can schedule. There's no commit to revert.

The agent figures that out, explains it on the ticket, flags it for a human and lists what to do next. No pull request. I'd much rather have an agent that knows its limits than one that guesses.

My first version had a funny gap here. After escalating, the agent just walked away. A human uncordoned the node, the alert resolved, and the ticket sat in Pending forever. Now the agent keeps an eye on escalated tickets for a day, and once the fix holds it closes them with a "resolved after human action" comment.

## The guardrails

This is the part I spent the most time on, because giving an LLM access to a cluster should make you a little nervous.

**Kubernetes permissions.** The agent's ServiceAccount can only get, list and watch. No Secrets, no exec, no port forwarding, no writes of any kind. I prove this with a script that checks every permission against the API server and then tries a real delete, which has to fail.

**A second check in code.** Before the agent runs any kubectl command, a small wrapper refuses anything that isn't a read, anything touching Secrets, and any flag that would switch identity or cluster. RBAC is the real wall, but it's nice to have two.

**Git as the only way in.** The agent is a GitHub App installed on one repo, with tokens that expire after an hour. Branch protection means it can open pull requests but never merge them. CI also rejects any agent PR that touches files outside the app's manifests.

**Splitting thinking from doing.** This one came later and I think it's the most important. The LLM runs in a short lived Kubernetes Job that has no Jira or GitHub credentials at all. It investigates, prints its diagnosis and exits. A separate controller, plain Python with no LLM in it, checks the proposed change and does all the writing. So even if someone managed to trick the model with a nasty log line, it has nothing to write with.

**Prompt injection.** Logs, events, commit messages and ticket text are all treated as untrusted data in the prompt. A log line that says "ignore your instructions" is just a log line.

## From my laptop to inside the cluster

I didn't start with the controller. My first version ran on my laptop with a kubeconfig that held a short lived token for the read only ServiceAccount. It worked, but it always bugged me. A token file on disk, a script making sure the agent didn't pick up my admin config by accident, and the whole thing stopped when I closed my laptop.

So I moved it into the cluster. Now there's a small controller Deployment that watches Jira. Every ticket becomes a custom resource called an AgentSession, so `kubectl get agentsessions` is basically my incident board. When the controller needs thinking done, it starts a Job for it. The waiting parts (waiting for review, waiting for the merge, waiting for ArgoCD) don't need an LLM at all, so they don't use one.

The nice side effect: there's no kubeconfig anymore. Kubernetes mounts a token into the pod and rotates it for me. An admission policy also makes sure the controller can only start Jobs that look exactly like the investigator, so its permission to create Jobs can't be turned into something else.

## Things that surprised me

**Small bugs break the whole loop.** At one point the agent never noticed ArgoCD had synced. It turned out I was cutting long command output to 12,000 characters before showing it to the model, and I was also parsing that cut version myself. The list of ArgoCD Applications was over 100,000 characters, so the JSON was broken and the check quietly failed. Lesson: what the model sees and what your code parses should be two different things.

**Jira workflows have opinions.** My Jira project has no direct path from Pending to Done. The agent kept trying and failing. I ended up supporting paths like "Work in progress, then Done" so it can walk through the workflow one step at a time.

**A smaller model is fine for this.** I switched from a bigger model to Claude Haiku to save money, and for these scenarios the diagnoses were just as good. Prompt caching and clearing old tool output during long investigations also helped keep the cost down.

**Service accounts everywhere.** At first the Jira comments came from my personal account. Now both the bridge and the agent use their own Jira service accounts with scoped tokens, and the self test fails if the token belongs to anyone else. It sounds small, but it matters for the audit trail.

## So, do you still need to learn Kubernetes?

After building this, my answer is a pretty clear yes.

The agent is great at the mechanical part. It's fast and it never forgets to check the events. But someone still has to review that pull request. Someone has to know whether moving a probe, raising a memory limit or reverting an image tag is actually the right call, or just makes the alert go away. And when the agent says "this isn't fixable in git, a human needs to look", that human needs to know what they're looking at.

What changes is where your time goes. Less time typing the same five commands at 3am, more time on the judgment calls. I'm fine with that trade.

## Try it yourself

The whole thing is on GitHub, built as 15 numbered steps. You start with an empty kind cluster, then add the network, ArgoCD, monitoring, the demo app, alert rules, the Jira bridge, the agent's permissions, the GitHub guardrails, and finally the agent itself. Each step has a short README explaining the concepts, a script to run it and a script to verify it. There are six failure scenarios you can inject with one command, and `make report` prints the MTTR of every incident, split into agent time and human time.

If you want to compare it with what's already out there, HolmesGPT and K8sGPT are the closest open source projects, and kagent is worth a look if you like the idea of agents as Kubernetes resources.

**Repo:** [the AI SRE demo on GitHub](https://github.com/Kyle-Law/ai-sre-demo)

Have you connected AI agents to Kubernetes yet? I'd love to hear what worked for you, what scared you, and which tools I should try next.
