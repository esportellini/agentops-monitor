# AgentOps Monitor Design System

## Product visual concept

**AI Operations Console** is a dark-first, graphite control surface for people responsible for live AI agents. The visual world borrows the discipline of runbooks and instrumentation panels: quiet frames, strong alignment, dense tables, exact numbers, and a restrained violet signal for selection and action. Semantic colors appear only for health, risk, and workflow state. Decoration never competes with telemetry.

## Navigation architecture

The desktop sidebar is 240px and groups routes by operator intent:

- **Overview:** Overview (`/dashboard`)
- **Observe:** Traces (`/traces`), Costs (`/costs`)
- **Govern:** Security (`/security`), Approvals (`/approvals`), Alerts (`/alerts`)
- **Evaluate:** Evaluations (`/evaluations` and child routes)
- **Build:** Projects (`/projects`), Agents (`/agents`), API Keys (`/api-keys`)
- **Organization:** Members (`/members`), Audit Logs (`/audit-logs`), Privacy (`/privacy`), Settings (`/settings`)

Profile remains in the user menu. On tablet and mobile the sidebar becomes an accessible drawer and closes after navigation. The 52px topbar contains the drawer trigger, breadcrumb context, organization switcher, command trigger, and user menu.

## Page anatomy

Every product route uses the same reading order: compact page header with title, useful context and primary action; controls and filters; then full-width operational content. Observability pages use the available viewport. Focused forms and simple settings use a narrower readable column. Detail pages place identity and status first, key facts second, then investigation or configuration content.

## Tokens

Tokens live as CSS custom properties and Tailwind semantic aliases.

- Canvas `#0b0d10`; sidebar `#0d1014`; surface `#101318`; elevated surface `#15191f`; hover `#1a1f27`.
- Subtle border `rgba(255,255,255,.07)`; strong border `rgba(255,255,255,.12)`.
- Primary text `#f2f4f7`; secondary `#a4abb8`; muted `#6f7785`.
- Brand `#7c6ff2`; hover `#9187ff`; soft selection uses a low-alpha brand tint.
- Success `#39b980`; warning `#e0a94f`; danger `#e0646c`; info `#6098e8`.
- Radius: 6px controls, 10px panels, full radius only for compact badges and avatars.
- Motion: 140ms for hover, menus, dialogs, and drawers; disabled under reduced-motion preference.

## Typography and spacing

The interface uses an offline-safe `ui-sans-serif` stack. `ui-monospace` is reserved for identifiers, timestamps, models, tokens, latency, and cost. Page titles are 24px, section titles 14–16px, body 13–14px, tables 12–13px, and metadata 11–12px. Numerals are tabular. The spacing scale uses 4, 6, 8, 12, 16, 20, 24, and 32px; related controls stay tight while sections receive clear separation.

## Surfaces and elevation

Canvas, sidebar, panels, and floating layers use distinct graphite values. Standard panels use one subtle border. Menus, dialogs, and drawers use the elevated surface with a soft offset shadow. Nested cards are avoided; internal hierarchy comes from dividers, spacing, columns, and typography.

## Status semantics

- Green: success, healthy, approved, priced.
- Amber: pending, warning, medium risk, incomplete data.
- Red: error, blocked, rejected, critical/high risk.
- Blue: informational and running.
- Violet: current selection and primary actions.
- Gray: neutral, inactive, acknowledged, or resolved.

Status and risk badges share one centralized mapping across every page. `UNPRICED` is amber and always displayed as incomplete rather than `$0`.

## Components

The shared system includes `AppShell`, grouped `Sidebar`, `Topbar`, `PageHeader`, breadcrumbs, `Panel`, section headers, metrics, centralized status/risk badges, table frames, filter bars, search input, tabs, buttons and icon buttons, form controls, dialog/drawer/dropdown layers, empty/error/loading states, inline alerts, JSON/code display, and chart primitives. Components encode repeated visual and interaction rules while domain pages keep their own data contracts.

## Tables, forms, and charts

Tables use sticky-feeling quiet headers, compact 44px rows, aligned actions, tabular numeric columns, horizontal overflow, row hover, and explicit loading/empty/error content. Forms have persistent labels, optional helper text, visible validation, consistent disabled/loading states, and four button intents: primary, secondary, ghost, danger. Charts use Recharts with one violet series, semantic secondary series only when meaningful, muted axes/grid, a shared dark tooltip, responsive containers, and honest empty states.

## Responsive behavior

Desktop layouts are tuned at 1440 and 1280px; 1024px retains dense tables with controlled horizontal scrolling. At 768px the sidebar moves into a drawer and multi-column panels stack. At 390px headers wrap, actions remain reachable, metrics use compact two-column layouts, dialogs fit within the viewport, and trace timelines scroll horizontally without shrinking labels into illegibility.

## Loading, error, and empty states

Skeleton rows and blocks preserve layout during queries. Empty states name what is missing and suggest only real next actions. Query errors use a concise message and retry where possible. Mutations show inline or toast confirmation and failure feedback; native `alert()` is not used.

## Accessibility

All actions use semantic buttons or links. Interactive controls have accessible names, keyboard behavior, visible `:focus-visible` rings, and at least 44px touch targets where space permits. Menus and dialogs manage escape/close behavior and focus. Text and status treatments meet contrast targets without relying on color alone. Reduced-motion preferences remove transitions.

## Route-by-route redesign plan

| Route | Operational role | Redesign focus |
| --- | --- | --- |
| `/` | Entry redirect | Preserve immediate routing. |
| `/login` | Authentication | Split product context and restrained form; no credentials in UI. |
| `/select-organization` | Workspace choice | Focused selection surface with clear organization metadata. |
| `/dashboard` | Operations overview | Primary health, needs attention, execution/cost trends, recent traces, drivers. |
| `/traces` | Trace explorer | Dense linked table, useful filters, consistent status/risk/cost formatting. |
| `/traces/[id]` | Investigation center | Trace hero, proportional waterfall, selectable span details, calls and sanitized JSON. |
| `/costs` | AI FinOps | Known spend, projection context, unpriced volume, trend and breakdowns. |
| `/security` | Risk queue | Severity overview, focused filters, scan-friendly findings table. |
| `/security/findings/[id]` | Finding investigation | Evidence, linked context, lifecycle, safe resolution workflow. |
| `/approvals` | Action inbox | Pending-first master/detail review with unequivocal approve/reject actions. |
| `/alerts` | Incident operations | Incidents and rules tabs with lifecycle prominence and consistent forms. |
| `/evaluations` | Quality overview | Runs, datasets, pass rate, provider status, and regressions. |
| `/evaluations/datasets` | Dataset inventory | Dense inventory with case counts and run paths. |
| `/evaluations/datasets/[id]` | Dataset workbench | Cases, expectations, tags, and run action. |
| `/evaluations/runs` | Run inventory | Status, model, score, cost completeness, and latency. |
| `/evaluations/runs/[id]` | Run analysis | Outcome summary and result table with evaluator details. |
| `/evaluations/compare` | A/B comparison | Baseline/candidate deltas and regression-first case review. |
| `/projects` | Project inventory | Efficient list with ownership context and linked agents/environments. |
| `/projects/new` | Project creation | Focused labeled form with clear success/error states. |
| `/projects/[id]` | Project context | Identity, agents, environments, and available activity metrics. |
| `/agents` | Agent inventory | Runtime identity, model, project, status, and policy/budget signals. |
| `/agents/new` | Agent creation | Structured identity and runtime setup. |
| `/agents/[id]` | Agent control | Runtime configuration, policy, recent activity, and cost context. |
| `/api-keys` | Credential governance | Prefix/scope/status table and one-time secret reveal. |
| `/members` | Access management | Compact role-aware member table. |
| `/audit-logs` | Change history | Dense filterable log with monospace actions and identifiers. |
| `/privacy` | Data governance | Retention, requests, and handling as distinct sections. |
| `/settings` | Organization settings | Small real settings grouped by purpose. |
| `/profile` | Personal account | Simple polished identity and account details. |

## Inventory findings

The original shell used a flat 14-item sidebar, hand-authored inline chevrons, an exposed hard-coded version, and desktop-only behavior. Pages repeated panel, button, input, table, heading, loading, and empty-state classes with inconsistent spacing. Status colors and formatting were implemented locally, mutations lacked one feedback pattern, and large pages mixed fetching, formatting, domain logic, and presentation. Dashboard metrics had equal visual weight, while high-value investigative pages did not receive stronger hierarchy. This redesign moves shared semantics into tokens and primitives, then uses domain composition to preserve dense workflows.
