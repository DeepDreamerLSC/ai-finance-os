# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-28
- Primary product surfaces: 手机号登录、Dashboard、AI 对话、智能账本、图片凭证、交易详情、设备会话
- Evidence reviewed: parent workspace product concept deck and authentication goal brief; `README.md`; `web/index.html`; `web/styles.css`; `web/app.js`; chiralium SMS/session implementation; container screenshots at 1440×900 and 390×844

## Brand
- Personality: calm, intelligent, precise, premium, and trustworthy
- Trust signals: 30-day device-session copy, masked phone identity, authenticated receipt access, explicit demo-provider labeling, visible data provenance, editable AI output, receipt-to-transaction traceability, and restrained financial visuals
- Avoid: decorative clutter, cheap gradients, template-card overload, ambiguous automation, and claims that deterministic demo logic is a live AI service

## Product goals
- Goals: reduce bookkeeping friction, turn natural language into confirmable records, keep financial evidence traceable, and make personal finance data understandable
- Non-goals: bank synchronization, investment management, complex budgeting, or production-grade financial advice in the MVP
- Success signals: a user verifies a phone once, returns without repeated login for 30 days, and can record, verify, find, edit, and understand only their own transactions on desktop or mobile

## Personas and jobs
- Primary personas: individuals who want lightweight bookkeeping, freelancers, and small-business owners separating personal and project finances
- User jobs: quickly capture a transaction, retain its evidence, review cash flow, and ask why spending changed
- Key contexts of use: rapid mobile capture and deeper desktop review

## Information architecture
- Primary navigation: 总览、AI 对话、智能账本、图片凭证
- Core routes/screens: a responsive phone verification screen followed by one authenticated application shell with four stateful views and a transaction-detail modal
- Content hierarchy: headline insight, key metrics, trends and categories, recent activity, then record-level detail and actions

## Design principles
- Expression before forms: natural-language input should precede structured confirmation
- Explain before optimize: show the data and its provenance before offering advice
- Trust before data: restore or establish identity before rendering any financial record or protected receipt
- Mobile actions stay visible: narrow layouts must not hide amounts or record actions behind horizontal scrolling
- Tradeoffs: the MVP favors a compact local runtime and deterministic interactions over framework-heavy animation or abstraction

## Visual language
- Color: ink black, cool white, cyan, violet, green, amber, and semantic red
- Typography: system sans-serif with strong display hierarchy and compact financial numerals
- Spacing/layout rhythm: generous page whitespace, 10–18px component gaps, and 16–24px card padding
- Shape/radius/elevation: 8–20px radii with quiet borders and low-opacity shadows
- Motion: short state transitions only; no decorative motion
- Imagery/iconography: compact geometric status symbols and real receipt previews

## Components
- Existing components to reuse: application shell, sidebar navigation, metric cards, chart surfaces, chat composer, ledger rows, receipt rows, modal, and toast
- New/changed components: authentication loading gate, phone/code login card, resend countdown, optional Turnstile challenge, masked account footer, logout action, and authenticated receipt previews
- Variants and states: desktop/mobile, income/expense, selected/unselected, loading, empty, success, and error
- Token/component ownership: color and spacing tokens remain in `web/styles.css`; behavior remains in `web/app.js`

## Accessibility
- Target standard: practical WCAG 2.1 AA behavior for the MVP
- Keyboard/focus behavior: native buttons, form controls, table semantics, dialog labeling, and unique accessible names
- Contrast/readability: dark ink on cool white; colored accents are not the only carrier of meaning
- Screen-reader semantics: retain headings, landmarks, table structure, labels, status, and dialog attributes
- Reduced motion and sensory considerations: transitions are brief and nonessential; no flashing content

## Responsive behavior
- Supported breakpoints/devices: desktop at 1020px and above, compact desktop/tablet below 1020px, and mobile at 740px and below
- Layout adaptations: sidebar becomes an off-canvas menu; dashboard and chat grids stack; metric cards become single-column; ledger rows become cards with visible amount and actions
- Touch/hover differences: primary controls use full-width mobile targets; hover styling is supplementary

## Interaction states
- Loading: authentication resolves behind a dedicated quiet loading gate before financial UI renders; financial data and uploads expose progress or status text
- Empty: ledgers and recognition results show explicit empty states
- Error: authentication errors remain generic and non-enumerating; API and upload errors appear in chat, status copy, or toast feedback
- Success: writes, uploads, edits, and refreshes produce visible confirmation
- Disabled: unavailable voice capture explains that the provider integration is reserved
- Offline/slow network, if applicable: the local demo remains usable without external AI credentials

## Content voice
- Tone: concise, calm, explanatory, and nonjudgmental
- Terminology: 账本、交易、凭证、现金流、洞察、AI 财务助手
- Microcopy rules: state what happened, preserve user control, and label simulated/provider-ready behavior honestly

## Implementation constraints
- Framework/styling system: dependency-light HTML, CSS, and browser JavaScript served by FastAPI; SQLAlchemy/PostgreSQL and Redis own persistent identity and finance state
- Design-token constraints: extend existing CSS variables and component classes; do not add a second design-system layer
- Performance constraints: no heavy frontend dependency; Turnstile is loaded only when an abuse threshold requires it
- Compatibility constraints: standard modern mobile and desktop browsers; no document-level horizontal overflow
- Test/screenshot expectations: verify 1440×900 and 390×844 layouts, visible mobile record actions, zero browser console errors, and container-hosted runtime behavior

## Open questions
- [ ] Select the real AI/OCR provider before production integration / product owner / affects consent, latency, and error-state design
- [ ] Select and publish final user-agreement and privacy-policy destinations / product owner / affects login-page legal links
