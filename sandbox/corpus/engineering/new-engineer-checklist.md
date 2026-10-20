---
title: "New engineer checklist"
---

# New engineer checklist

Owner: Platform, with each team's lead. Last reviewed: 2026-10-14.

This list covers only what is specific to engineering. Everything that every new joiner does, from your first day to your accounts, office access and buddy, is in [new joiner onboarding](../people/onboarding.md): do that first, and use this list beside it. Copy the list into your onboarding ticket, tick items off as you go, and tell your team lead when an item is wrong or out of date.

## Week one: access and tools

- [ ] Join your team's channel and `#team-platform`.
- [ ] On the code host, join the engineering group and your team's group. Register an SSH key and a signing key, as [Git conventions](git-conventions.md) describes.
- [ ] Ask for read access to Strongroom's `dev/` namespace; your team lead approves it.
- [ ] Check that you can pull from `registry.quillmoor.example`; access comes with the engineering group.
- [ ] Sign in to Lantern at `lantern.quillmoor.example` and find your team's dashboards.
- [ ] In Jira, find your team's board in ENG and the current sprint.
- [ ] Install Klaxon on your phone now, although you will not be on call for a while: [setting up Klaxon on your phone](../incidents/klaxon-setup.md).
- [ ] Install `qm` and get your team's repository running on your laptop with seed data, following [local development environment](local-development.md).

## Week two: your first change

- [ ] Read the [coding standards](coding-standards.md), the [code review guidelines](code-review.md) and the [testing strategy](testing-strategy.md).
- [ ] Pick a ticket labelled `good-first-ticket` from your team's backlog.
- [ ] Open your first change, and ask your team lead to suggest a reviewer.
- [ ] Review two of your teammates' changes, with an experienced reviewer reading your comments.
- [ ] Follow one of your changes all the way to production with a teammate, using [how code reaches production](../release/deployment-pipeline.md) as your map.

## First month: production

- [ ] Read your team's runbooks and [production incident management](../incidents/incident-management.md).
- [ ] Shadow a week of on-call with your team's primary; the rota rules are in [on-call rota and paging policy](../incidents/on-call.md).
- [ ] Read two recent PIRs from your area.
- [ ] Request production access only for what your role needs; it is checked in the [quarterly access reviews](../security/access-reviews.md).
- [ ] Come to a meeting of the backend or frontend guild.

## First quarter

- [ ] Join the on-call rota, after a reverse-shadow week and when your team lead agrees.
- [ ] Facilitate a sprint retrospective for your team.
- [ ] Improve one handbook page that confused you.

> [!TIP]
> Keep a list of everything that surprised or confused you in your first month, and bring it to your team lead. Fresh eyes notice what the rest of us stopped seeing, and that list is how pages like this one get better.
