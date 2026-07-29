# Institutional Calm design QA

## Source truth

- Dashboard reference: `/Users/linsuchang/.codex/generated_images/019fa442-a186-77b2-979a-59a589ef0f7b/call_v3Wa2TWI3K3z8T4nap30u3Sa.png`
- Login reference: `/Users/linsuchang/.codex/generated_images/019fa442-a186-77b2-979a-59a589ef0f7b/call_eUdNPtcz6OhkMrQddZzMzYKQ.png`
- Reference viewport and pixel size: 1487 × 1058
- Reference state: signed-in finance dashboard and signed-out phone verification

## Implementation evidence

- Desktop dashboard: `/private/tmp/finance-os-dashboard-1487-v2.png`
- Desktop login: `/private/tmp/finance-os-login-desktop.png`
- Mobile login, 390 × 844: `/private/tmp/finance-os-login-mobile.png`
- Mobile dashboard, 390 × 844: `/private/tmp/finance-os-dashboard-mobile-top.png`
- Mobile AI entry, 390 × 844: `/private/tmp/finance-os-ai-mobile-final.png`
- Mobile ledger, 390 × 844: `/private/tmp/finance-os-ledger-mobile.png`
- Mobile receipts, 390 × 844: `/private/tmp/finance-os-receipts-mobile.png`
- Dashboard comparison: `/private/tmp/finance-os-dashboard-comparison.png`
- Login comparison: `/private/tmp/finance-os-login-comparison.png`

## Comparison history

### Iteration 1

- Desktop composition matched the reference palette and hierarchy, but the page was 1215 px tall at the 1058 px viewport.
- The top greeting and module title consumed too much vertical space.
- The category chart still used the previous purple and cyan palette.
- Mobile login exposed the desktop trust row.
- Result: failed; P1 mobile crowding and P2 density and palette mismatches.

### Iteration 2

- Reduced the topbar and title spacing, reduced chart height, and moved all chart colors to forest green, sage, muted brass, and cool gray.
- Desktop document height reduced to 1137 px while retaining five recent transactions and the AI insight panel.
- Mobile trust row is hidden and the login layout has no horizontal overflow.
- A 390 px AI chat check found a min-content overflow that clipped the voice and send controls.
- Result: failed; P1 mobile composer overflow.

### Iteration 3

- Added an explicit zero minimum width for the chat panel and composer textarea.
- At 390 px the page scroll width equals the viewport width.
- The chat panel ends at x=374, the composer ends at x=356, and the send button ends at x=356; all controls are fully visible.
- Dashboard, login, ledger, receipts, and AI entry screenshots show consistent spacing, borders, typography, and responsive behavior.
- Browser console errors: none.

### Iteration 4

- Request: remove the browser-shaped inner focus pill from the phone field and keep every desktop sidebar control fixed in the viewport.
- Same-state focus comparison at 1280 × 720: `/private/tmp/finance-phone-focus-comparison.png`.
- Before: the focused native telephone input rendered a second rounded outline inside the designed field.
- After: the native input has `appearance: none`, zero radius, no outline, and no shadow; only the accessible outer field focus treatment remains.
- Desktop scroll evidence: `/private/tmp/finance-sidebar-fixed-after-scroll.png`.
- At page scroll Y=416, the sidebar remains at Y=0 with height 720; its footer ends at Y=696 and is fully visible.
- Mobile regression check at 390 × 844: the sidebar remains an off-canvas fixed drawer, the main content remains 390 px wide, and page scroll width remains 390 px.
- Automated verification: 45 backend tests, 6 frontend tests, and 16 desktop/mobile E2E tests passed.

## Final visual judgment

- Palette: matches the selected private-banking direction with deep navy, warm ivory, forest green, muted brass, and soft gray.
- Hierarchy: large module titles, restrained supporting copy, thin rules, and tabular financial figures follow the reference.
- Density: the desktop dashboard preserves the source's information-rich composition without card-heavy SaaS styling.
- Login: the approved copy is synchronized with the product and uses the same split-screen visual language.
- Responsive behavior: the desktop rail becomes an off-canvas menu; metrics stack cleanly; ledger rows become editable cards; receipt and AI flows remain usable.
- Intentional product differences: the implementation keeps the real application data and controls instead of adding nonfunctional spark lines, settings, or account widgets shown only in the visual reference.

final result: passed
