# Inquest frontend audit

Step A · Baseline at revision `f6d0279` · 16 November 2026

## Scope and method

Ran the existing Inquest frontend and its unmodified production build. Captured Chromium screenshots at **1440 × 900**, **1024 × 768**, and **768 × 1024** in light and dark using the installed design-taste-frontend screenshot tool. Captures use the app’s own theme preference. The 216 verified screenshots cover 36 scenarios across all shipped pages, the simulator, and the main working and failure states.

A temporary loopback capture server served the built frontend with read-only responses from the existing synthetic audit workspace, recorded investigation events, and published evaluations. Controlled delays and error responses reproduce transient states. The streaming and reconnecting captures exercise the current browser event-stream UI with recorded frames and a controlled response. The simulator and decision states came from synthetic records or controlled responses. The baseline measures browser rendering. The live model and provider-side OAuth were outside the audit scope.

## Findings

| Priority | What the baseline shows | Why it matters |
| --- | --- | --- |
| High | Four separate count cards occupy a full row between the queue title and its working controls. The toolbar, table and footer have separate visual rhythms. | Counts read like a dashboard summary, while the primary task is scanning, filtering and opening cases. A shared frame would surface more rows and show which controls affect the list. |
| High | The queue has a long placeholder, three similar selects, and a clear action only once criteria are present. URL-backed criteria work, but there is no compact summary of the values in effect. | As filters and sort accumulate, analysts must read each control to explain which cases they are seeing. The search placeholder also truncates in compact widths. |
| High | At 768 px the 810 px queue table has a 666 px scroll region, with the timestamp column off the initial viewport. The 60 px navigation rail becomes icon-only at both 1024 and 768 px. The queue pins identity and status. | Tablet users must infer where to go from icons and discover horizontal scrolling for later columns. The pinned columns are useful and should carry through. |
| High | The case heading, transaction facts and score occupy separate blocks with equal visual emphasis. In the queued state the start button sits below both panels. In review the choices are short radio labels of similar weight. At 768 px the stacked summary and timeline put the action form below the first viewport. | Where to start and what “Approve” accepts are harder to understand at a glance. The action group needs the recommendation, the consequences of each choice, and a clear form endpoint. |
| High | Loading and failed requests use a spinner or a short alert. The queue count row and table disappear before results, and explorer and evaluation bodies offer little scaffold. The queue empty message refers back to the header Simulator. | Large jumps make the next step feel disconnected from the work area. Retaining the relevant controls and geometry would distinguish loading, an empty workspace, no matches, and a recoverable failure. |
| Medium | The live timeline puts connection state into small muted text and initially shows an empty report box. An expanded tool inspection shows a long payload alongside compact text elsewhere. The recorded state shows the action, analyst, timestamp, and note in a bordered subsection. | The investigation phase and the recorded outcome deserve distinct hierarchy. Evidence inputs and output need room to scan, while their labels and citation targets stay close. |
| Medium | Login and signup sit in a small centered card below a separate header. The two provider controls have equal size, but use the same arrow mark, and the card carries the same body paragraph on both routes. | The two choices could be recognized faster. A common left alignment and route-specific copy would remove the effect of a generic sign-in template. |
| Medium | The explorer makes the whole history row a button and places the selected comparison in a quiet separate panel. At 768 px the comparison is below the history list. The alert is plain subtext. | The selected attempt, comparison, and route back to its cases need a closer visual relationship. Stable columns would make scanning amount, device and location easier. |
| Medium | Evaluation repeats the count-card treatment. The precision–recall table is a disclosure below the chart, and the wide ablation table can scroll at tablet width. Partial and cache-only timing annotations sit within the rows. | The analyst should see the metric’s window and denominator before interpreting a value. An explicit chart/table switch and stronger column alignment would improve comparison. |
| Medium | The header puts Simulator, theme, and an icon-only sign-out side by side. Replay confirmation places both buttons near the start of the dialog. Control variants and icon sizing differ across links, sort controls, panels, and dialogs. | The shell needs clearer grouping and sign-out belongs with the account. One control system and consistent placement make consequential actions easier to recognize. |
| Low | Dark mode has its own palette. Several outlines and metadata treatments carry similar visual weight. Risk bars, active-state accents, and semantic labels all compete in the same dense areas. | Color should signal interaction or status consistently. Restore hierarchy with neutral dividers, higher-contrast metadata, and distinct semantic labels and icons. |

The current UI already provides a visible skip link and focus styles, keyboard-operable sort buttons, explicit case links, stored theme choice, URL-backed queue filters and sorting, evidence citations that open and focus their source, a reconnect indicator, and recorded decisions. These are design behaviours to preserve. The existing light and dark status hues warrant rendered contrast and color-vision checks in the redesign.

## Current button and action inventory

| Area | Existing action | Current presentation and states |
| --- | --- | --- |
| Workspace | Skip to content | Focus-visible link to the main region. |
| Workspace | Inquest brand, Case Queue, Transaction Explorer, Evaluation | Brand and labeled nav links on desktop. Compact rail keeps accessible link names. Cases is styled active on case detail. |
| Workspace and auth | System, Light, Dark | Icon plus native select. Selection persists locally and follows the OS in System mode. |
| Workspace | Sign out | Icon-only header button with accessible name and title. Disabled while sending. Shows retry on failure. |
| Auth | Continue with GitHub, Continue with Google | Same outlined button and generic sign-in icon in separate forms. Disable when the provider is unavailable or loading. |
| Auth | Sign in, Create a workspace | Inline link below provider choices. The proper intent is passed by the corresponding form. |
| Auth | Retry a failed sign-in or provider-options request | Callback error asks the user to pick a provider again. Provider-options request failures expose Try again. |
| Queue | Search cases | Text field for case, transaction, customer or merchant. The value lives in the URL. |
| Queue | Filter case status, channel, minimum risk | Three native selects. Risk presets are ≥1%, ≥10%, and ≥50%. |
| Queue | Clear filters | Text button appears once search or a filter is set. Sort survives and pagination resets. |
| Queue | Sort Status, Risk score, Amount, Merchant, Channel, Transaction time | Header buttons with up/down or unsorted indicator. Active header exposes `aria-sort`. |
| Queue | Open case | Underlined case ID link with an accessible name including the transaction. |
| Queue | First page, Next page | Footer buttons and count of cases shown. First page appears after navigation. Next page disables when unavailable or loading placeholder data. |
| Case | Back to Case Queue | Link restores the queue URL when entered from its list. |
| Case | Open synthetic customer history | Customer link opens Explorer at the case transaction cutoff. |
| Case | Start investigation | Primary below the summary panels. Disabled while submitting and shows failure feedback. |
| Case | Expand/collapse evidence, jump to a citation | Native timeline disclosures. Citation buttons open and focus matching observation summaries. They disable while the matching event is absent. |
| Case | Approve, Override, Escalate | Native radio group. Approve starts selected. Override reveals a disposition select. |
| Case | Add analyst notes, Record decision | Labeled optional textarea and primary form submission. Input and action are disabled while pending. Conflicts refresh the case. The recorded action is a read-only summary. |
| Explorer | Search, select customer | Text field and outlined result buttons. Matching result selection opens the history. |
| Explorer | Select attempt to compare distance | Clickable history rows with pressed state. Missing comparison data is explained. |
| Explorer | Latest attempts, Older attempts, Return to Case Queue | Two page controls and a queue link. A flagged attempt has a label and currently offers no case link. |
| Evaluation | Select scorer cohort, select agent cohort | Two native selectors. Section content follows the selected cohort. |
| Evaluation | View chart data | Native disclosure opens a table of precision/recall points. Scenario and ablation tables are separately visible. |
| Simulator | Open status, Start, Pause, Resume, Replay | Header disclosure, native progress bar and short replay ID. Actions reflect replay state and disable while submitting. Replay opens confirmation. |
| Replay dialog | Cancel, Start new replay | Native modal. Cancel starts focused. Confirmation explains that prior cases and decisions are preserved. |
| Shared | Try again, Back to case queue | Named recovery action in request error or unknown-route states. |

The API exposes workspace-wide search, status, channel, and minimum risk filters. Amount, merchant, and time are sortable. A merchant can be searched by name. Dedicated amount ranges, time ranges, and exact merchant filters are future contract questions. Customer history exposes an alert flag without an exact case ID. The proposal describes a frontend link to matching cases and asks for a future replay tie-breaker.

## Screenshot index

The baseline images are grouped by theme and viewport under [ui-before-after/before](ui-before-after/before/). Each matrix entry is named `<scenario>.png`. Images extend down the page when the content exceeds the viewport. Read the modal and its backdrop in the first viewport of replay-confirmation captures.

| Area | Captured scenarios | Sample |
| --- | --- | --- |
| Login and signup | Normal, OAuth callback error, and provider loading for both routes | [Login at 1440 light](ui-before-after/before/light/1440/login.png) |
| Case queue | Populated, loading, empty workspace, no matching filters, request error, filtered and sorted | [Queue at 768 dark](ui-before-after/before/dark/768/queue.png) |
| Case detail | Queued, loading, error, receiving events, reconnecting, review form, expanded evidence, decision recorded | [Streaming at 1024 light](ui-before-after/before/light/1024/case-streaming.png) · [Recorded decision at 1440 dark](ui-before-after/before/dark/1440/case-recorded.png) |
| Explorer | Initial empty state, search matches, no matches, selected customer and distance comparison, loading, error | [Explorer at 1024 dark](ui-before-after/before/dark/1024/explorer.png) |
| Evaluation | Published report, chart data expanded, no published runs, loading, error | [Evaluation at 1440 light](ui-before-after/before/light/1440/evaluation.png) |
| Simulator | Idle, running, paused, replay confirmation | [Replay dialog at 768 light](ui-before-after/before/light/768/simulator-confirm.png) |
| Unknown route | Page unavailable and queue recovery link | [Unknown route at 1024 light](ui-before-after/before/light/1024/unknown-route.png) |

[Read the Step B proposal](UI_REDESIGN.md).

[View the after captures](ui-before-after/after/).
