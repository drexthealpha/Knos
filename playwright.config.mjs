// The phone sizes every screen is tested at (LAWS\UX\U3.md Rule 13: StatCounter's mobile screen sizes, October 2026).
// tests/web/law_checks.mjs reads its test viewports from these three projects, so the law checks of U3 run in all three.
// A plain object: the repository's browser tests run on the playwright package, not on Playwright's test runner.
export default {
  projects: [
    { name: "phone 360", use: { viewport: { width: 360, height: 780 } } },
    { name: "phone 390", use: { viewport: { width: 390, height: 844 } } },
    { name: "phone 414", use: { viewport: { width: 414, height: 896 } } },
  ],
};
