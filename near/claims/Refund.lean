/-
Knos claim: what the two helpers are paid plus what goes back to the payer is always exactly the bid.

Same split as Split.lean: helper A gets up to `a`, helper B up to `b`, the rest is refunded. Its market on NEAR
testnet settles Yes only when this file compiles in GitHub Actions (.github/workflows/lean-claim.yml) and that run's
own token releases the claim's milestone, whose criteria hash is this file's sha256, locked when it was funded.
-/

def pay (bid a b : Nat) : Nat × Nat :=
  let x := min a bid
  (x, min b (bid - x))

def refund (bid a b : Nat) : Nat :=
  bid - (pay bid a b).1 - (pay bid a b).2

theorem paid_plus_refund_is_the_bid (bid a b : Nat) :
    (pay bid a b).1 + (pay bid a b).2 + refund bid a b = bid := by
  unfold refund pay
  simp only
  have h1 : min a bid ≤ bid := Nat.min_le_right a bid
  have h2 : min b (bid - min a bid) ≤ bid - min a bid := Nat.min_le_right _ _
  omega
