# Incident records

Every remediation PR opened by the AI SRE agent adds `incidents/<TICKET>.md`
with the alert, diagnosis, evidence and the change it proposed. Together with
the Jira ticket, the PR conversation and ArgoCD's sync history, git becomes the
permanent, reviewable record of each incident.

ArgoCD does not deploy anything from this folder.
