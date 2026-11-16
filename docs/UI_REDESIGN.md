# Inquest UI redesign proposal

Fraud operations console · Approved design and implementation notes

## 1. Design direction

Put the work on one aligned surface. Cases opens on the queue, with counts and active filters on the same grid as the table. Case details put the recommendation and decision next to the evidence needed to make it. Borrow the queue-to-context progression from Stripe Radar, URL-backed filtering and compact navigation from Linear, consistent action states from Vercel Geist, and transaction-first tables with explicit time and amount formatting from Mercury. Use Geist Sans for interface copy, retain IBM Plex Mono for data, and use warm paper surfaces with cobalt controls in light mode and graphite surfaces with lighter blue controls in dark mode. Use the taste skill’s alignment, typography, copy, and accessibility checks for an operations console. [Stripe Radar](https://docs.stripe.com/radar/transaction-reviews) · [Linear filters](https://linear.app/docs/filters) · [Vercel Geist Button](https://vercel.com/geist/button) · [Mercury transactions](https://support.mercury.com/hc/en-us/articles/38790547830036-Viewing-cashflow-and-transactions-data-on-your-Transactions-page)

## 2. Design tokens

| Token | Specification |
| --- | --- |
| Typefaces | Geist Sans for interface text. IBM Plex Mono for IDs, scores, and aligned numeric columns where useful. Use tabular figures for values and timestamps, including values set in Geist Sans. |
| Type scale | Page title 26/32 at 650. Section heading 16/22 at 650. Table and body 14/20 at 400–500. Controls and labels 13/18 at 550. Supporting metadata 13/18 at 400. Lead metrics 22/28 at 650. |
| Spacing | 4, 8, 12, 16, 20, 24, 32, 40 px. Inline icons sit 8 px from labels. Paired panels use a 16 px gap. |
| Radii | 4 px for controls and chips, 6 px for panels and dialogs. Circular shapes serve avatars, indicators, and chart marks. |
| Borders | One pixel. Use the subtle token for row and panel dividers and the stronger control token where the edge identifies a field. |
| Elevation | Flat canvas, panels, and table surfaces. Menus and dialogs use one understated neutral shadow and a visible border. Light shadow `0 8px 24px rgb(23 33 43 / 12%)`. Dark shadow `0 8px 24px rgb(0 0 0 / 40%)`. |
| Focus | 2 px interaction ring with 2 px offset. Use a surface-colored inner gap on filled buttons or sticky edges. Scroll to keep the ring in view. |
| Motion | 160 ms for button and row state transitions, 180 ms for menus and dialogs. Use color and opacity, with at most a 1 px button press. Reduced motion removes decorative transitions and uses a static busy glyph plus status text. |

### Light and dark palettes

The final palette follows the request to recolor the whole application. Light mode layers warm paper and stone surfaces. Dark mode uses graphite with cooler controls. Cobalt marks links, selected controls, and focus. Green/amber/rust/berry are reserved for labeled statuses and case actions. The plot uses neutral inks distinct from the action accent.

| Role | Light | Dark |
| --- | --- | --- |
| Canvas | `#F5F4F0` | `#10141B` |
| Panel | `#FFFEFA` | `#171D26` |
| Rail and table header | `#EFEEE8` | `#121821` |
| Neutral hover | `#EEEEE9` | `#222B38` |
| Neutral press | `#E5E8ED` | `#2B3647` |
| Text | `#1B2330` | `#EDF1F8` |
| Secondary text and metadata | `#4D5768` | `#AEB9CA` |
| Dividers | `#DAD9D1` | `#333D4B` |
| Control outlines | `#727D8F` | `#7D8DA5` |
| Interaction links, focus, and primary fill | `#2349BD` | `#9AB5FF` |
| Primary hover / press | `#1D3DA4` / `#193487` | `#B4C8FF` / `#87A7FA` |
| Text on primary | `#FFFFFF` | `#111C37` |
| Selected navigation and filter tint | `#E7EDFF` | `#23345F` |
| Contribution bars right / left | `#475D77` / `#6D6657` | `#A9BDD8` / `#C1B7A0` |

| Status and Lucide icon | Light text / fill | Dark text / fill | Text contrast light / dark |
| --- | --- | --- | --- |
| Fraud · ShieldAlert | `#913419` / `#FCEBE5` | `#FFAF92` / `#412A25` | 6.70 / 7.46 |
| Legitimate · CircleCheck | `#285C40` / `#E7F2E9` | `#A9DEC0` / `#233B31` | 6.78 / 7.98 |
| Needs review · CircleHelp | `#6D4E05` / `#FFF1D0` | `#F6CF77` / `#3E3321` | 6.84 / 8.30 |
| Escalated · ArrowUpRight | `#813653` / `#F9EBEF` | `#F2B2CD` / `#402A39` | 7.02 / 7.48 |

Queued, investigating, and generic resolved use neutral ink with distinct icons. Status labels and icon shapes carry meaning in grayscale. A caution treatment marks block confirmation. The tested neutral text pairs reach at least 5.94:1 in light and 6.13:1 in dark. Control outlines reach at least 3.39:1 and 3.62:1. The lowest tested interaction ink pair reaches 6.51:1 and 6.03:1. [WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) · [WCAG non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## 3. Layout system

- **Workspace shell.** 184 px text navigation rail and 56 px sticky header at 1200 px and above. At 1024 px, use a 64 px icon rail with accessible names and focus tooltips. At 768 px, use a single labeled horizontal navigation row beneath the header. Header right contains Simulator, theme, and account in separate groups. The workspace identifier is selectable and appears once as a label in the account area on compact screens.
- **Page header.** Align title, optional context, and any page-level primary action to the content grid. Case detail adds a back link that restores the queue URL. Keep page headings consistent and use section headings for transaction, evidence, and report groupings.
- **Content.** Use equal 32/24/20 px gutters at 1440/1024/768 px and a 1360 px maximum content width. Use a 12-column grid with 16 px gaps at desktop widths. The transaction and score panels split 7/5, timeline and report 6/6, and explorer history and comparison 8/4. At 768 px, case panels stack in reading order and the explorer comparison expands under the selected attempt. Login and signup share a 384 px form aligned to the workspace content edge.
- **Data surfaces.** Use 40–44 px rows with a 36 px table header. Place counts in an inline strip, then toolbar, table, and footer on the same ruled surface. Keep case identity and status visible when scrolling sideways at the target widths and clip scroll to the table region. Let secondary cell content wrap before relying on horizontal scrolling. Align amounts, scores, and count denominators.
- **Panels.** Use one surface and a border with 16 px inset. Use section dividers for details on the same subject. Keep label/value grids aligned and give report forms a comfortable reading width. Keep busy, empty, and failed content in the same frame as the successful view.

## 4. Component states

All interactive controls take the visible focus ring, retain their label when busy, and keep their size when a state changes. Status feedback also uses explicit text. State-specific details follow.

| Component | Default and hover | Focus and active | Disabled, loading, and error |
| --- | --- | --- | --- |
| Button | Shared variant and size tokens. Hover adjusts the fill or underline. | Visible ring, pressed fill, 1 px press. | Disabled uses muted ink and a clear unavailable reason where needed. Busy reserves the icon slot for a spinner and holds the label and width. Errors appear beside the action. |
| Icon button | Square control with an accessible action name and tooltip on hover or focus. | Same ring and press as text buttons. Open triggers expose expanded state. | Same busy/disabled behavior. Preserve the accessible label during progress. |
| Input | Visible label, field border, and concise placeholder as a hint. Hover strengthens the outline. | Focus preserves the field border. Changes update the existing search behavior. | Disabled uses a quiet surface. Search pending preserves the typed value. Inline error uses text and `aria-describedby`; invalid input adds `aria-invalid`. |
| Select | Labeled native control with one consistent chevron and padding. | Native keyboard selection, visible trigger ring, selected value remains visible. | Keep current choice while results load. Disable only if use is impossible. Errors appear beside the relevant control or results. |
| Filter chip | Show applied label and value; a named remove control gets a separate focus stop only if needed. | Soft blue selected fill and an obvious remove action on hover or focus. | Preserve applied chips while results refresh. A failed request keeps filters and offers a retry. |
| Table | Native headers, named scroll region, left-pinned context, zebra-free row separators. Row hover uses neutral fill. | Sort buttons use `aria-sort` on the active header and expose direction. All tabs and row links remain reachable. | Skeleton uses the same geometry. Refresh retains existing data where supported. Empty/refetch error keeps toolbar and uses a named next step. Pagination disables only unavailable actions. |
| Status badge | Compact label, 14 px icon, semantic tint. | Static badge stays outside tab order. If a badge filters, render the interaction as a separate button. | A loading badge uses a neutral placeholder. Unknown or unavailable status has plain text and a neutral style. |
| Risk score | Display probability with consistent precision and threshold context on detail. Use neutral tone and an optional baseline marker. | Any drill-in is a separate named link. | Use an em dash with an accessible label for missing values; use a skeleton when fetching. |
| Tabs / view switch | Use one compact segmented strip for related views, with a neutral hover. | Tabs follow the arrow-key pattern and expose selected state with text weight and the accent indicator. | Show a stable content area while loading. Retry lives inside the affected panel. Document unavailable views beside their label. |
| Dialog | Title, plain-language consequence, grouped Cancel and Confirm controls. | Native modal focus containment, initial focus on Cancel for replay and decisions, Escape closes when safe, focus returns to opener. | Confirm becomes busy without resizing. Keep recoverable error inline and keep the dialog open until success or dismissal. |
| Toast | Short status text after an acknowledged action, with a named dismiss control if persistent. | A polite live region announces success once. Focus remains on the work. | Pending status lives at the originating control. Failures with a required next step stay inline until resolved, with no duplicate toast. |
| Timeline item | Stable sequence order with a brief event line. Tool entries disclose validated input and observation. | Chevron and named disclosure show open state. Citations open the matching entry, scroll it into view, and focus its summary. | Keep committed entries during reconnect. Status line distinguishes connecting, receiving, reconnecting, and unavailable. Use existing SSE and resume behavior. |
| Citation chip | Evidence ID and human-readable claim with visible link styling. | Focus ring, hover affordance, and the matching timeline summary receives focus on activation. | Disable only while matching evidence is unavailable. Explain the reason and keep the report legible. |
| Contribution bars | Shared zero axis, labels and signed values, stable type widths. Scale both directions by the same maximum absolute value. | Static chart is read in order. Any future tooltip would need a keyboard equivalent. | Skeleton preserves label/value positions. Missing features use a named empty state. |
| Empty / error / skeleton | Name the condition and the nearest actionable next step. Reserve layout space during load. | Move focus only on a deliberate route transition or to a relevant confirmation/validation target. | Show one polite loading announcement. Display errors in the failed region with a retry or a route back. Remove shimmer under reduced motion. |

## 5. Button and action system

One component supports **primary**, **secondary**, **ghost**, **caution**, **icon-only**, and **link**. Primary uses the solid cobalt token and sits at the right end of an action group or form. Secondary uses the neutral panel and a visible border. Ghost uses an outlined focus ring and a quiet hover surface. Caution uses the warm color only for a consequential confirmation. Icon-only is square with a 16 px Lucide icon, a name, and a tooltip. Links navigate or jump to evidence. Sizes are 32, 36, and 40 px with 4 px corners, 16 px icons, and 8 px gaps. Use 40 px controls in the tablet header and main action areas. A spinner replaces the leading icon in a reserved slot, with the original label held in place and a polite busy announcement. Use sentence-case verbs with a clear object. Use one primary per active view, including a popover or dialog while it has focus.

Provider buttons are equal-width, 40 px secondary controls. Their identity marks are the official GitHub and Google assets, with Lucide for interface actions. Keep the same POST forms, intent values, and OAuth callbacks. The Google mark retains its official colors. [GitHub brand toolkit](https://brand.github.com/foundations/logo) · [Google sign-in branding](https://developers.google.com/identity/branding-guidelines)

| Area | Action | Variant | Location | State rules |
| --- | --- | --- | --- | --- |
| Shell | Cases, Explorer, Evaluation | Link navigation | Rail or compact horizontal row | Current destination is visible and announced. Case detail keeps Cases selected. |
| Shell | Open Simulator | Secondary | Header, next to its state label | Shows status while closed. Expanded control exposes cursor, total, and replay ID. |
| Shell | Select system, light, or dark theme | Named icon-only trigger, native selection or radio menu | Header | Current preference is explicit. System follows the browser and persistence survives navigation. |
| Shell | Open account / Sign out | Named icon-only trigger / ghost | Header account popover | Show workspace and analyst IDs from the existing session. Sign out disables while sending and shows an inline retry on failure. |
| Auth | Continue with GitHub / Continue with Google | Equal secondary | Same vertical group in Login and Sign Up | Maintain shared hierarchy. Enable configured providers, announce loading or failure, and surface a provider-specific unavailable reason. |
| Auth | Switch between Login and Sign Up | Link | Below the provider group | Preserve clear destination labels. |
| Auth | Retry after a failure | Secondary for fetching providers; existing provider actions for callback errors | Error under heading or provider group | A callback error invites a deliberate provider selection. Keep both configured providers available. |
| Queue | Search cases | Input with named clear icon | Left of toolbar | Search case ID, transaction ID, customer, or merchant through the existing search. Keep URL and active summary in sync. |
| Queue | Filter status, risk, and channel | Secondary filter trigger, labeled controls, removable chips | Toolbar and applied-filter row | Preserve current URL semantics and reset pagination when criteria change. Use searchable merchant text and sortable amount/time as described under Future. |
| Queue | Clear filters | Ghost | End of applied filters | Show only with active filters. Keep sort and restore the first page. |
| Queue | Sort status, risk, amount, merchant, channel, and time | Ghost header controls | Table headings | Keyboard operable, one current direction, existing URL sort parameters. |
| Queue | Open case | Link | Explicit case link in each row | Accessible case and transaction name. Preserve queue URL on return. |
| Queue | First page / Next page | Secondary | Footer, opposite row count | Keep existing cursor semantics. Disable Next page at end or during placeholder fetch. Footer distinguishes visible row count and workspace totals. |
| Case | Back to queue | Link | Above page heading | Restore search, filters, sort, and cursor for entry from the queue. |
| Case | Review decision | Link | Next to the case status at tablet widths | When the report is ready, jump to and focus the decision heading. |
| Case | Start investigation | Primary | Right of the case heading when action is available | Prevent duplicate submissions while busy. Keep the existing idempotency key and refresh after a conflict. |
| Case | Expand/collapse evidence item | Ghost disclosure | Timeline row | Report citations reuse the native disclosure behavior and check focus target. |
| Case | Jump to cited evidence | Link-style button | Report claim | Activate only while the matching evidence exists. Open and focus its summary. |
| Case | Review stream status | Status text | Timeline heading | Announce the existing reconnect state politely. Preserve committed events and current focus. |
| Case | Approve recommendation / Override / Escalate | Native radio choices | Same decision fieldset beside the recommendation | Approve accepts the displayed recommendation. Override shows a disposition choice. Escalate records that the case needs further review. Each option states its consequence. |
| Case | Write analyst notes | Labeled textarea | Below decision choices | Optional, maximum 1000 characters. Keep the synthetic-data notice and preserve draft text on a failed submit. |
| Case | Submit decision | Primary | End of decision form | Open a compact confirmation naming selected action. On confirming, disable repeat submission while pending, keep the existing version and request headers, and show conflict feedback or recorded actor/time. |
| Case | Cancel / Confirm decision | Secondary / primary or caution for a block | Decision confirmation | Name the outcome. Cancel restores focus and the form. Keep failure inline and close only on an accepted result or explicit dismissal. |
| Explorer | Search customers / Select customer | Input / ghost result row | Search and results area | Search by ID or alias. Announce results, no matches, and data errors. Retain keyboard order. |
| Explorer | Inspect attempt / Compare distance | Ghost disclosure or selectable row | History list | Preserve selected attempt and focus. At tablet width show its comparison inline. Explain absent comparison values. |
| Explorer | View matching cases | Link | Flagged attempt row | Link to the existing queue search for the transaction. The queue shows matching replays for selection. |
| Explorer | Latest attempts / Older attempts | Secondary | History footer | Preserve current cursor; disable an unavailable page. |
| Evaluation | Select scorer or agent cohort | Labeled select | Beside each section title | Keep the evaluation window and denominator next to the selection. |
| Evaluation | Show chart / Show table | Tabs | Precision–recall panel | Same data and an accessible table. Use neutral plot marks and keep scenario counts available. Mark cache-only timing, partial runs, and undefined values. |
| Simulator | Start / Pause / Resume | Primary in popover | After cursor progress | Match current replay state. Hold width while pending; label failures at the controls. |
| Simulator | Replay | Secondary | Simulator controls, spatially separated from routine start/pause | Open confirmation after a prior run exists. Name that it creates a new run and preserves previous cases and decisions. |
| Dialog | Cancel / Confirm replay | Secondary / primary | End of replay confirmation | Initial focus on Cancel and return focus to Replay. Confirm once, show pending progress, and show conflict/error inline with refreshed state. |
| Shared | Retry / Back to cases | Secondary or link | In the failed or unknown-route region | Keep the original input and route context where available. |

**Dependencies.** Keep React, TypeScript, Tailwind, TanStack Query, React Router, and Lucide. Use native HTML for forms, selects, fieldsets, dialogs, and disclosures. The font package replaces the existing Inter package. The test setup adds two development packages. Use `@playwright/test` for keyboard, request-shape, and responsive regression tests with installed Chrome locally. Use `oxlint` for React, TypeScript, and accessibility lint checks. Bundle Geist Sans through its Fontsource package in place of Inter and use static official provider artwork. Check the INR glyph and tabular figures in the rendered font. [Playwright browser channels](https://playwright.dev/docs/browsers#google-chrome--microsoft-edge) · [Oxlint](https://oxc.rs/docs/guide/usage/linter.html) · [Geist font and license](https://github.com/vercel/geist-font)

## 6. Page wireframes

| Route or surface | Proposed composition from top to bottom | Change from baseline |
| --- | --- | --- |
| `/login` | `Inquest · Theme → Sign in to Inquest → OAuth error when present → GitHub / Google → Create workspace → synthetic-data notice` | Bring the form to the same left alignment as its narrow content rail. Restore provider identity and group retry with its cause. |
| `/signup` | `Inquest · Theme → Create an analyst workspace → what the first sign-in creates → GitHub / Google → notice → Sign in` | Keep the signup purpose and the required notice distinct and close to the actions. |
| `/` | `Cases → inline counts → Search + Filters → applied chips → case list → visible count + page controls` | Counts occupy one strip. Toolbar and table share edges. Identity and status remain legible on tablet and empty/error states retain the table frame. |
| `/cases/:caseId` | `Back to cases → Case ID + status + Start investigation when queued → transaction facts / risk drivers → timeline / report and decision → recorded outcome` | Label the agent recommendation and the recorded analyst decision as separate outcomes. Keep the timeline first in DOM order and stack with report and decision at 768 px. Provide a keyboard-operable link from the case header to the decision when ready. |
| `/explorer` | `Transaction Explorer → customer search/results → selected customer → history list / selected-attempt comparison → page controls` | Make selected state explicit. Move transaction ID, location, and flags into stable columns. Put the selected comparison next to its attempt at 768 px and give flags a matching-case link. |
| `/evaluation` | `Evaluation → scorer cohort + dates → one metric strip → Chart / Table + scenario recall → agent cohort + comparison` | Tie metrics and samples to their cohorts, move chart/table into the panel header, and keep the scenario and ablation denominators visible. |
| Unknown route | `Workspace shell → Page unavailable → Back to cases` | Use the shared empty-state treatment and give the recovery link a clear target. |
| Simulator and replay dialog | `Header: Simulator + state → cursor/total + progress + replay ID → Start/Pause/Resume + Replay → confirmation` | Keep status in the shell and keep replay consequence and busy/error feedback in the relevant dialog. |

## 7. Verification and build sequence

1. After approval, make one commit per step. Start with tokens and base components, then app shell, auth pages, case queue, case detail, explorer, evaluation, and simulator and dialogs. Finish with polish. Each commit keeps its routes operable and includes relevant tests.
2. Use the validated screenshot matrix from the audit. Capture the same routes and states at 1440 × 900, 1024 × 768, and 768 × 1024, in both themes. Save the after frames alongside the baseline. Inspect aligned edges, table scroll and focus, event updates, error placement, evidence overflow, and the state transitions. Run a reduced-motion pass and a 390 px overflow spot check.
3. Keyboard-only walkthrough from queue to report to decision. Verify skip link, focus visibility and order, sort direction, filter reset, pagination, citation focus, timeline disclosures, decision controls, Escape, dialog focus return, and any action that visibly changes state.
4. Check rendered contrast against WCAG 2.2 AA. Measure labels, outlines, focus rings, chart marks, badges, and errors in both themes. Emulate protanopia, deuteranopia and tritanopia. Confirm statuses retain icon and text in every case.
5. Run frontend lint, TypeScript, production build, and browser tests. Test provider buttons and intent form paths without external sign-in, URL hydration and back navigation, API call shapes and methods, simulation and replay, reconnect with last event ID, idempotent decisions, and the preserved synthetic-data notices. Use the dedicated frontend lint, type check, build, and test commands.
6. During review, check the frontend diff and pinned OpenAPI checksum, and compare response fixtures against current contracts. Report any visual or state gap with a screenshot reference.

### Future questions

- Should a later API extension support workspace-wide amount ranges, transaction-time ranges, and an exact merchant filter? The current queue accepts search, status, channel, and minimum risk. Amount and time are sortable today, and merchant is searchable.
- If one transaction produced cases across several replays, which case should an Explorer deep link prefer? The current history response carries an alert flag. The proposed link opens matching cases through the queue. A replay-specific direct link would need an agreed tie-breaker and a case ID in the response or an exact lookup endpoint.
- Which investigation states, if any, should support cancellation? A cancel action would require an API contract and a defined cancellation outcome.
- Does Evaluation need a download format later? This proposal uses the chart and table over the published dataset already returned by the API.

## 8. Verification results

- The [before captures](ui-before-after/before/) cover 36 scenarios. The [after captures](ui-before-after/after/) cover the same 36 plus the account popover and analyst decision confirmation, for 228 images. Each scenario was captured in light and dark at 1440 × 900, 1024 × 768, and 768 × 1024.
- The after matrix uses the existing synthetic audit workspace, recorded investigation frames, and controlled responses for loading, errors, and reconnection. It measures browser presentation of those states.
- Ten Chrome tests cover the OAuth forms, keyboard navigation and queue URL, evidence focus and decision submission, SSE reconnection with the last event ID, replay confirmation, Explorer links, chart tabs, contrast, color-vision simulation, and reduced motion at 390 px.
- Frontend lint, type checking, and the production build passed. The running Compose proxy serves the rebuilt app with both OAuth options available. The frontend tests verify the sign-in form targets and intent values. Provider-side sign-in is outside this redesign verification.
- The compact queue and evaluation tables still need local horizontal scrolling to keep all columns available. Explorer links open matching cases because one transaction can belong to multiple replays.
