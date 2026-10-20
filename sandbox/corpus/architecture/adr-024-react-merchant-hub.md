---
title: "ADR-024: React for Merchant Hub"
---

- **Status:** Accepted, 2026-05-18
- **Author:** Priya Castellane, design system lead
- **Deciders:** Ottilie Marsh, Ama Rowntree, Bram Oyelaran, Nadia Ferreira

## Context

Merchant Hub, the merchants' web dashboard served by `merchant-hub`, is two front ends
wearing one coat. The pages built between 2017 and 2020 are rendered on the server from
templates, with a little script added by hand. The pages built since are React
components, mounted inside the same page shell. A merchant moving from Payments to
Payouts crosses from one world to the other without knowing it. We do.

Inkwell, our design system, ships React components in `@quillmoor/inkwell`. The
server-rendered pages cannot use them, so they rely on a separate, CSS-only copy of
Inkwell's styles that we maintain by hand and that always lags behind.

Three pieces of work in the past year have shown what that costs:

- **Inkwell tokens v2** (ENG-24) renamed the colour tokens. The React pages picked up
  the new names with a package upgrade. The CSS-only copy took three weeks of manual
  edits, and two pages shipped with the old colours.
- **Accessibility remediation** (ENG-25) found problems on both kinds of page, but the
  fixes on React pages came from Inkwell for free, while every fix on a
  server-rendered page was written by hand, page by page.
- **Dark mode** (ENG-26, see [the product brief](../product/brief-dark-mode.md)) needs
  every colour on every page to come from tokens. On the server-rendered pages,
  colours are written straight into templates in hundreds of places.

Thirty-four server-rendered pages remain, out of ninety-one.

## Decision

Merchant Hub is a single React application, written in TypeScript.

- **No new server-rendered pages.** Every new page, and every page substantially
  changed, is built in React.
- **The remaining server-rendered pages are rewritten**, starting with the most visited
  and those that block dark mode. The team plans the order each quarter.
- **Inkwell components only.** Pages are built from Inkwell components and tokens. A
  need that Inkwell does not meet goes to the design system team as a contribution or
  a request, not into a local one-off component.
- **Colours and themes come from tokens**, never from values written in a page. How
  themes work is described in [Theming and dark mode](../design/theming.md), and the
  tokens themselves in [Inkwell design tokens and principles](../design/tokens.md).
- **Data comes from `merchant-api`**, through its composite endpoints for Merchant Hub
  ([ADR-016](adr-016-no-graphql.md)), always naming the newest API version
  ([ADR-023](adr-023-api-versioning.md)).
- **The CSS-only copy of Inkwell is frozen today** and deleted with the last
  server-rendered page.

## Consequences

- One stack to learn, test and secure. New engineers in Merchant Experience no longer
  need to understand two ways of building a page.
- Design system changes, including accessibility fixes, reach every rewritten page
  through a package upgrade.
- The rewrite takes capacity away from new features for several quarters. Product has
  agreed to that trade, and dark mode will reach pages as they are rewritten rather
  than all at once.
- More rendering happens in the browser. We must watch first-load time on slow
  connections and keep the bundle split by section.
- The server side of `merchant-hub` shrinks to serving the application and handling
  sign-in.

## Alternatives considered

- **Vue or Svelte.** Both capable, but Inkwell is built in React, and so are two thirds
  of our pages. Changing framework would mean rewriting both.
- **Web components.** A standard, and framework-neutral, which would let Inkwell serve
  both stacks. Rewriting Inkwell as web components is a larger project than rewriting
  the remaining pages.
- **Keep both stacks.** We have tried this for six years. The cost grows with every
  token change and every page.

## Related ADRs

- [ADR-016](adr-016-no-graphql.md): composite endpoints instead of GraphQL.
- [ADR-023](adr-023-api-versioning.md): API versions by date.
