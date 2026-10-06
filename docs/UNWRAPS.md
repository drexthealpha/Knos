# Where a program can panic

Written by `python tests/test_unwraps.py --write` from the programs' source; `tests/test_unwraps.py` fails when this page is not what that command
writes. Do not edit it by hand: the reasons are in that file.

A panic in a Solana program aborts the instruction and with it the whole transaction. The runtime keeps none of the transaction's account
changes: no state is written and no token moves. What a panic costs is the transaction fee and an error that names no cause. So the question for
each place below is whether it can be reached, and the answer wanted is no.

The four programs' source holds 101 `unwrap()` calls. 39 are in program code, on the 34 lines listed below; the other 62 are in unit tests and proof harnesses
(`#[cfg(test)]` at the end of each file, and `knos_pay/src/proofs.rs`, which is compiled only for tests and for the Kani model checker), which are in
no build of a program. No program code holds an `expect(`, an `unreachable!`, a `panic!`, a `todo!` or an `assert!`; one `debug_assert_eq!` is listed.
`knos_oidc` is the one program Knos 0.3.16 changes, and its places were read line by line: none can be reached, so none was replaced. For the three
programs 0.3.16 does not change (`knos_pay`, `knos_meter`, `knos_passkey`: their builds must stay byte for byte) a reason names the guard where it is
on the lines just before, and says so where the guard is a caller's.

## Every written panic in program code

| Place | The line | Why it cannot fail, or what happens if it does |
| --- | --- | --- |
| `knos_meter/src/gh.rs:124` | `Ok(EvalAud { buyer, seller, order: unhex32(order).ok_or_else(bad)?, artifact: artifact.try_into().unwrap(), policy: unhex32(policy).ok_or_else(bad)?,` | Two lines above, the audience is refused unless `is_hex(artifact, 40)`, which is false for any length but 40: the conversion to 40 bytes cannot fail. |
| `knos_meter/src/state.rs:87` | `pub fn u32_at(d: &[u8], o: usize) -> u32 { u32::from_le_bytes(d[o..o + 4].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The helper is called with constant offsets into an account or instruction data; this list does not re-derive each caller's length check for a program 0.3.16 does not change. Short data aborts the transaction. |
| `knos_meter/src/state.rs:88` | `pub fn u64_at(d: &[u8], o: usize) -> u64 { u64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. As `u32_at`. |
| `knos_meter/src/state.rs:89` | `pub fn i64_at(d: &[u8], o: usize) -> i64 { i64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. As `u32_at`. |
| `knos_meter/src/state.rs:90` | `pub fn key_at(d: &[u8], o: usize) -> Pubkey { Pubkey::new_from_array(d[o..o + 32].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. As `u32_at`. |
| `knos_meter/src/state.rs:145` (2 on the line) | `wf_repo: d[C_WF_REPO..C_WF_REPO + 32].try_into().unwrap(), wf_sha: d[C_WF_SHA..C_WF_SHA + 40].try_into().unwrap() })` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`: a constant offset into account data. This list does not re-derive the reader's length check for a program 0.3.16 does not change; short data aborts the transaction. |
| `knos_meter/src/state.rs:162` | `for (limb, c) in n.iter_mut().zip(k.chunks(4)) { *limb = u32::from_be_bytes(c.try_into().unwrap()); }` | `k` is a 32-byte public key, so every chunk is four bytes: the conversion cannot fail. |
| `knos_meter/src/token.rs:84` | `Some((by, size)) if by == *token.key && size.len() == 8 => Ok(u64::from_le_bytes(size.try_into().unwrap()) as usize),` | The same match arm requires `size.len() == 8`: the conversion of eight bytes cannot fail. |
| `knos_oidc/src/claims.rs:43` | `debug_assert_eq!(w - from, out_len);` | A debug assertion: it is not compiled into a release build, which is what `cargo build-sbf` makes. In a test build it says the decoder wrote as many bytes as `b64_len` promised. |
| `knos_oidc/src/lib.rs:265` | `fn i64_at(d: &[u8], at: usize) -> i64 { i64::from_le_bytes(d[at..at + 8].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. Every caller reads `K_ACTIVE` (8) or `K_EXPIRES` (16) of a key account after `key_limbs` accepted it, which requires its length to be `K_HDR` (40) plus the limbs: it is never shorter. |
| `knos_oidc/src/lib.rs:303` | `Ok(Key { issuer: d[K_ISSUER], l, n0inv: u32::from_le_bytes(d[K_N0INV..K_N0INV + 4].try_into().unwrap()), n, r2, tail })` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. `load_key` runs `key_limbs` first, so the account holds at least its 40-byte header: it is never shorter. |
| `knos_oidc/src/lib.rs:547` | `let n0inv = u32::from_le_bytes(rest[0..4].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The line before refuses instruction data whose length is not `4 + 4 * l`: it is never shorter. |
| `knos_oidc/src/lib.rs:575` | `pins::ISSUER_OTHER => ikey_audience(d[K_HDR + 8 * l..K_HDR + 8 * l + 32].try_into().unwrap(), &kh),` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. `key_limbs` accepted the account, and for an issuer number of ISSUER_OTHER or above that requires 64 bytes after the limbs: it is never shorter. |
| `knos_passkey/src/lib.rs:208` | `let key: [u8; webauthn::KEY_LEN] = d[W_KEY..W_KEY + webauthn::KEY_LEN].try_into().unwrap();` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. `wallet_key` refuses an account whose length is not `WALLET_LEN` first. |
| `knos_passkey/src/lib.rs:209` | `(key, d[W_BUMP], u64::from_le_bytes(d[W_NONCE..W_NONCE + 8].try_into().unwrap()))` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. `wallet_key` refuses an account whose length is not `WALLET_LEN` first. |
| `knos_passkey/src/lib.rs:243` | `let amount = u64::from_le_bytes(data[0..8].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The line before refuses instruction data shorter than 16 bytes (18 in `fund`). |
| `knos_passkey/src/lib.rs:244` | `let nonce = u64::from_le_bytes(data[8..16].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The line before refuses instruction data shorter than 16 bytes (18 in `fund`). |
| `knos_passkey/src/lib.rs:264` | `let expiry = u64::from_le_bytes(data[0..8].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The line before refuses instruction data shorter than 16 bytes (18 in `fund`). |
| `knos_passkey/src/lib.rs:265` | `let nonce = u64::from_le_bytes(data[8..16].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The line before refuses instruction data shorter than 16 bytes (18 in `fund`). |
| `knos_passkey/src/lib.rs:289` | `let amount = u64::from_le_bytes(fund_data[17..25].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. Data shorter than `FUND_MIN` (158 bytes) was refused before the wallet signed anything. |
| `knos_passkey/src/token.rs:58` | `let key = \|o: usize\| Pubkey::new_from_array(d[o..o + 32].try_into().unwrap());` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. `o` is 0 or 32, and the line before returns unless the account is at least `ACCOUNT_LEN` (165) bytes. |
| `knos_passkey/src/token.rs:65` | `d.get(64..72).map(\|b\| u64::from_le_bytes(b.try_into().unwrap())).ok_or(ProgramError::InvalidAccountData)` | `get(64..72)` gives eight bytes or nothing, and nothing is answered with InvalidAccountData: the conversion of eight bytes cannot fail. |
| `knos_pay/src/order.rs:71` | `repo: u64_at(&d, O_REPO), issue: u64_at(&d, O_ISSUE), scope: d[O_SCOPE..O_SCOPE + 32].try_into().unwrap(), seq: u32_at(&d, O_SEQ),` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`: a constant offset into account data. This list does not re-derive the reader's length check for a program 0.3.16 does not change; short data aborts the transaction. |
| `knos_pay/src/order.rs:78` (2 on the line) | `mint: key_at(&d, O_MINT), terms: d[O_TERMS..O_TERMS + 32].try_into().unwrap(), wf_repo: d[O_WF_REPO..O_WF_REPO + 32].try_into().unwrap(),` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`: a constant offset into account data. This list does not re-derive the reader's length check for a program 0.3.16 does not change; short data aborts the transaction. |
| `knos_pay/src/order.rs:79` | `wf_sha: d[O_WF_SHA..O_WF_SHA + 40].try_into().unwrap(),` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`: a constant offset into account data. This list does not re-derive the reader's length check for a program 0.3.16 does not change; short data aborts the transaction. |
| `knos_pay/src/order.rs:198` (2 on the line) | `(rest[..32].try_into().unwrap(), rest[32..].try_into().unwrap(), None)` | The line before refuses the instruction unless `rest.len() == 64`: both halves are 32 bytes, and neither conversion can fail. |
| `knos_pay/src/order_judge.rs:207` (2 on the line) | `Ok(Funded { repo: 0, issue: 0, scope: data[..32].try_into().unwrap(), terms: data[32..].try_into().unwrap(), json: None })` | Three lines above, the instruction is refused unless `data.len() == 64`: both halves are 32 bytes, and neither conversion can fail. |
| `knos_pay/src/state.rs:171` | `pub fn u32_at(d: &[u8], o: usize) -> u32 { u32::from_le_bytes(d[o..o + 4].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. The helper is called with constant offsets into an account or instruction data; this list does not re-derive each caller's length check for a program 0.3.16 does not change. Short data aborts the transaction. |
| `knos_pay/src/state.rs:172` | `pub fn u64_at(d: &[u8], o: usize) -> u64 { u64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. As `u32_at`. |
| `knos_pay/src/state.rs:173` | `pub fn i64_at(d: &[u8], o: usize) -> i64 { i64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. As `u32_at`. |
| `knos_pay/src/state.rs:174` | `pub fn key_at(d: &[u8], o: usize) -> Pubkey { Pubkey::new_from_array(d[o..o + 32].try_into().unwrap()) }` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`. As `u32_at`. |
| `knos_pay/src/state.rs:261` (2 on the line) | `terms: d[J_TERMS..J_TERMS + 32].try_into().unwrap(), wf_repo: d[J_WF_REPO..J_WF_REPO + 32].try_into().unwrap(),` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`: a constant offset into account data. This list does not re-derive the reader's length check for a program 0.3.16 does not change; short data aborts the transaction. |
| `knos_pay/src/state.rs:262` | `wf_sha: d[J_WF_SHA..J_WF_SHA + 40].try_into().unwrap(),` | A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. The slicing before it panics if the data is shorter than `o + N`: a constant offset into account data. This list does not re-derive the reader's length check for a program 0.3.16 does not change; short data aborts the transaction. |
| `knos_pay/src/state.rs:311` | `for (limb, c) in n.iter_mut().zip(k.chunks(4)) { *limb = u32::from_be_bytes(c.try_into().unwrap()); }` | `k` is a 32-byte public key, so every chunk is four bytes: the conversion cannot fail. |
| `knos_pay/src/token.rs:82` | `Some((by, size)) if by == *token.key && size.len() == 8 => Ok(u64::from_le_bytes(size.try_into().unwrap()) as usize),` | The same match arm requires `size.len() == 8`: the conversion of eight bytes cannot fail. |

## Indexing

`d[k]` and `d[a..b]` panic when the index is past the end. They are counted here by file (lines of program code that index a slice, an array or a
`Vec`; a line can index several times), not explained one by one. What keeps them in range, by kind: an account's data is read at constant offsets
after its owner and its length were checked (`key_limbs` and `T_JWT + len` in `knos_oidc`; the `*_LEN` checks of the other programs); instruction data
is measured before it is cut; the claim readers and the base64 decoders (`knos_oidc/src/strict.rs` and `claims.rs`) index inside loops bounded by the slice's length, and
are run on 1,560,000 random documents and by two fuzz targets ([ASSURANCE.md](ASSURANCE.md)); the RSA limbs (`rsa.rs`) are vectors sized from the key's
own limb count. An index that is out of range all the same aborts the transaction, as above.

| File | Written panics in program code | In tests and proofs | Lines of program code that index |
| --- | ---: | ---: | ---: |
| `knos_meter/src/gh.rs` | 1 | 20 | 6 |
| `knos_meter/src/lib.rs` | 0 | 12 | 0 |
| `knos_meter/src/meter.rs` | 0 | 0 | 16 |
| `knos_meter/src/state.rs` | 7 | 5 | 15 |
| `knos_meter/src/token.rs` | 1 | 17 | 8 |
| `knos_oidc/src/claims.rs` | 1 | 64 | 20 |
| `knos_oidc/src/es256.rs` | 0 | 23 | 44 |
| `knos_oidc/src/lib.rs` | 4 | 40 | 87 |
| `knos_oidc/src/pins.rs` | 0 | 0 | 2 |
| `knos_oidc/src/rsa.rs` | 0 | 0 | 51 |
| `knos_oidc/src/strict.rs` | 0 | 64 | 35 |
| `knos_passkey/src/lib.rs` | 7 | 9 | 17 |
| `knos_passkey/src/token.rs` | 2 | 25 | 9 |
| `knos_passkey/src/webauthn.rs` | 0 | 19 | 6 |
| `knos_pay/src/fund.rs` | 0 | 0 | 17 |
| `knos_pay/src/gh.rs` | 0 | 3 | 8 |
| `knos_pay/src/gl.rs` | 0 | 14 | 0 |
| `knos_pay/src/lib.rs` | 0 | 13 | 0 |
| `knos_pay/src/order.rs` | 6 | 10 | 22 |
| `knos_pay/src/order_judge.rs` | 2 | 67 | 5 |
| `knos_pay/src/order_pay.rs` | 0 | 7 | 10 |
| `knos_pay/src/order_terms.rs` | 0 | 11 | 19 |
| `knos_pay/src/pay.rs` | 0 | 0 | 2 |
| `knos_pay/src/proofs.rs` | 0 | 46 | 0 |
| `knos_pay/src/state.rs` | 8 | 10 | 22 |
| `knos_pay/src/token.rs` | 1 | 26 | 8 |
| all | 40 | 505 | 429 |
