# Analyst console design brief

Phase 0 approved design · 14 November 2026

## Layout and visual system

Open on the case queue. Use a compact navigation rail and a workspace header that keeps simulator state visible. A content area aligned to a 12-column grid gives the table and evidence room. Use flat surfaces, subtle borders, and limited shadow for menus or dialogs. Use Inter for interface text and IBM Plex Mono for case IDs, evidence IDs and selected numeric values. Use tabular numerals for aligned amounts and scores.

| Token | Proposed value |
| --- | --- |
| Page title | 24/32 px, semibold |
| Section title | 16/24 px, semibold |
| Body and table cells | 14/20 px |
| Labels, secondary metadata, table headers | 12/16 px |
| Spacing | 4, 8, 12, 16, 24, 32 px |
| Controls | 36 px minimum desktop height, larger touch targets where space allows |
| Table rows | 44 px baseline, with wrapped text on narrower layouts |
| Radius | 4 px for controls, 6 px for contained panels |

| Role | Light | Dark |
| --- | --- | --- |
| Canvas | `#F5F7F9` | `#11161C` |
| Surface | `#FFFFFF` | `#192129` |
| Text | `#18232E` | `#E6EDF3` |
| Secondary text | `#516174` | `#A0ADBB` |
| Border | `#D6DEE6` | `#374553` |
| Teal accent for selection, links, focus and primary action | `#0F6B62` | `#66C6B7` |

Reserve teal for interaction. Use colorblind-friendly semantic foregrounds with distinct labels and icons on neutral surfaces.

| Status | Light | Dark | Lucide icon |
| --- | --- | --- | --- |
| Fraud | `#A33D16` | `#FFAB82` | ShieldAlert |
| Legit | `#215F9A` | `#9CCBFF` | CircleCheck |
| Review | `#785700` | `#F1CA64` | CircleHelp |
| Escalated | `#673EA0` | `#D6B5FF` | ArrowUpRight |

Show the risk score as a number with an optional neutral bar. The proposed status and accent foregrounds have a minimum 5.93:1 contrast against the listed neutral backgrounds. Validate WCAG AA contrast for interactive text, focus and status indicators in both themes. Default to system theme and remember the user's choice.

## Screens

| Screen | Proposed composition |
| --- | --- |
| Sign up and sign in | Show “Continue with GitHub” and “Continue with Google” on both pages. Explain that first sign-in creates an analyst workspace. Show the synthetic-data notice at signup and a retry action if authentication fails. |
| Case queue | Search and filters above a sortable table for status, risk, amount, merchant, channel and time. Keep an explicit case link in each row. Put sort state and active filters in the URL. |
| Case detail | Show the transaction summary and model score with signed horizontal feature bars. Put the live timeline beside the report at desktop widths and stack them on tablet. Expand timeline entries to inspect validated inputs and observations. Selecting a report citation opens and focuses the matching observation. Place approve, override and escalate beside the recommendation with a labeled notes field and the notice “Synthetic data only. Don’t enter real personal data.” Repeat the notice at signup. Show the recorded action and actor once the case changes. |
| Transaction explorer | Search by synthetic customer ID or alias. Show a chronological timeline with amount, location, device, channel and flagged attempts. Provide a compact distance and elapsed-time comparison with source and accuracy. |
| Evaluation | Place counts and time window beside the baseline and agent metrics. Use a precision-recall chart, per-scenario bars and a comparable ablation table with sample counts. Mark partial runs, cache-only timing and undefined metrics. |
| Simulator | Use a status control in the workspace header with start, pause, and replay. Show cursor progress and the active replay ID. Replay confirmation explains that it creates another run and preserves previous cases. |

Shared components include navigation, table and filter controls, status labels, loading and error states, evidence links, timeline disclosures, a signed contribution chart, accessible metric charts with tables, a decision form, and a replay control.

## Interaction and approval checks

Use semantic table headers with keyboard-operable sort buttons. Focus indicators remain visible in both themes. Timeline updates preserve focus and scroll position. Announce material state changes through a polite live region and allow users to inspect past events while an investigation continues. On disconnect show reconnecting status and retain committed events. Distinguish empty fixtures, no filter results, and network errors. Disable decision submission while pending and refresh the case with a clear explanation if another analyst already acted.

At 768 px, collapse the navigation to a rail or menu and stack the case sections. Allow horizontal scrolling for dense tables with persistent identity and status columns where space permits. Check the queue, report and decision path with keyboard navigation and reduced motion at desktop and tablet widths. The slate-and-teal direction is approved. Verify contrast and status legibility in the rendered UI in both themes. See [the approved scope](PLAN.md#phase-0-decisions-for-phase-1).
