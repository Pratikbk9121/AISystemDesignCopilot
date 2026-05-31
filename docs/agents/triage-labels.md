# Triage Label Vocabulary

This project uses the following labels to track issue lifecycle states.

## Label Mapping

| Triage Role         | GitHub Label      | Meaning                                               |
|---------------------|-------------------|-------------------------------------------------------|
| Needs Triage        | `needs-triage`    | Maintainer needs to evaluate this issue               |
| Needs Info          | `needs-info`      | Waiting on reporter to provide more information       |
| Ready for Agent     | `ready-for-agent` | Fully specified, AFK-ready (agent can implement)      |
| Ready for Human     | `ready-for-human` | Needs human implementation (too complex for agents)   |
| Won't Fix           | `wontfix`         | Will not be actioned (closed, duplicate, out of scope)|

## Usage

The `/triage` skill applies these labels as it moves issues through the triage state machine:

```
[New Issue]
    ↓
needs-triage → (evaluate) → needs-info / ready-for-agent / ready-for-human / wontfix
    ↓
needs-info → (reporter responds) → needs-triage (re-evaluate)
    ↓
ready-for-agent → (agent picks up) → [In Progress]
    ↓
ready-for-human → (human picks up) → [In Progress]
    ↓
wontfix → [Closed]
```

## Creating Labels

If these labels don't exist in your repository yet, create them:

```bash
gh label create "needs-triage" --description "Maintainer needs to evaluate" --color "fbca04"
gh label create "needs-info" --description "Waiting on reporter" --color "d876e3"
gh label create "ready-for-agent" --description "Fully specified, AFK-ready" --color "0e8a16"
gh label create "ready-for-human" --description "Needs human implementation" --color "1d76db"
gh label create "wontfix" --description "Will not be actioned" --color "ffffff"
```
