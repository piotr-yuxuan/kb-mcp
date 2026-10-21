---
title: "ADR-001: Record architecture decisions"
---

- **Status:** Accepted, 2017-03-06
- **Author:** Ottilie Marsh, chief technology officer
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Yusuf Achterberg, Kwabena Stroud

## Context

Quillmoor is three months old and has eleven engineers. Decisions about languages,
storage and the way services talk to each other are being made in corridors, in chat
and on a whiteboard that is wiped every Friday. In a year, nobody will remember why we
chose what we chose. Newcomers will either reopen old arguments or change something
without knowing what it was protecting.

We want a written record that is cheap enough to keep up: something a person can draft
in an hour, discuss in one meeting, and read in five minutes long after the people who
made the decision have moved on.

## Decision

We keep an architecture decision record (ADR) for every decision that is expensive to
reverse or that affects more than one team. An ADR is a short wiki page, in this
section, that states one decision, the context in which it was made, and what follows
from it.

1. **Numbering.** ADRs are numbered in the order they are opened, from ADR-001.
   Numbers are never reused, not even for a proposal that is turned down.
2. **Title.** The title states the decision itself ("Run services on Kubernetes"),
   never the topic ("Container discussion").
3. **Status.** One of Proposed, Accepted, Rejected, Deprecated or Superseded, with the
   date it took that status. A rejected ADR stays in this section: knowing what we
   chose not to do, and why, saves the next person a week.
4. **Accepted means frozen.** Once an ADR is accepted, its body is not rewritten.
   Later facts go in a dated "Update" note at the end. A decision that changes gets a
   new ADR that supersedes the old one, and the old one gains a warning at the top that
   links to its successor.
5. **One format.** Every ADR uses the template below, so that readers know where to
   look.
6. **Review.** Anyone may propose an ADR. Proposals are discussed at the architecture
   review on Wednesday afternoons, and the record names the deciders.

The template:

```text
- Status: Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-NNN, with a date
- Author: who wrote it
- Deciders: who agreed it

## Context        what forces are at play, as they stood on the day
## Decision       what we will do, stated plainly
## Consequences   what becomes easier, what becomes harder
## Alternatives considered   what else we looked at, and why not
## Related ADRs   links, both ways
```

## Consequences

- Writing an ADR costs an hour or two of the proposer's time and part of a review
  meeting. We accept that cost for decisions that will outlive the people in the room.
- Some decisions will slip through without a record. When we notice one, we write it
  after the fact and say so in the status line.
- This section becomes the first place to look before proposing a change to how
  services are built, stored, deployed or connected.
- Small, reversible choices, such as a library inside one service, do not need an ADR.
  The team that owns the service decides.

## Alternatives considered

- **Long design documents in shared folders.** They take weeks, are rarely finished,
  and nobody can find the final version.
- **Markdown files next to the code.** Attractive to engineers, but our decisions
  cross repositories, and colleagues in product, finance and security should be able
  to read them without access to the code.
- **Nothing written down.** The present state, and the reason for this record.

## Related ADRs

Records added since, kept here as examples of each status:

- [ADR-007](adr-007-message-broker.md), superseded by
  [ADR-019](adr-019-replicated-event-log.md): how a superseded record and its successor
  point at each other.
- [ADR-016](adr-016-no-graphql.md): a rejected proposal, kept with its reasons.
