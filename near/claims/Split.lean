/-
Knos claim: splitting a job's bid between two helpers never pays out more than the bid.

`pay bid a b` pays helper A up to `a` and helper B up to `b`, from one bid. The theorem below says the two payouts
together never exceed the bid, for every bid and every ask. Its market on NEAR testnet settles Yes only when this file
compiles in GitHub Actions (.github/workflows/lean-claim.yml) and that run's own token releases the claim's milestone,
whose criteria hash is this file's sha256, locked when it was funded.
-/

def pay (bid a b : Nat) : Nat × Nat :=
  let x := min a bid
  (x, min b (bid - x))

theorem pay_never_exceeds_bid (bid a b : Nat) : (pay bid a b).1 + (pay bid a b).2 ≤ bid := by
  unfold pay
  simp only
  have h1 : min a bid ≤ bid := Nat.min_le_right a bid
  have h2 : min b (bid - min a bid) ≤ bid - min a bid := Nat.min_le_right _ _
  omega
