/**
 * Types for the two packages the bot loads at run time.
 *
 * `x402-fetch` ships no declarations, and viem's are only needed where the
 * bot touches an account. Both are loaded with `await import(...)` inside
 * the paying path, so a checkout without them installed still typechecks and
 * still runs — `/brief` says x402 is not configured instead of crashing.
 */

declare module "x402-fetch" {
  export function wrapFetchWithPayment(
    fetcher: typeof fetch,
    account: unknown,
    ...rest: unknown[]
  ): typeof fetch;
}
