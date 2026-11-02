//! The one Solana message the contract will have the MPC network sign for a released milestone: a legacy message whose
//! only instruction is SPL Token `TransferChecked` of exactly the milestone's amount, from an account the derived key
//! owns, in the mint locked at funding, to the payee's token account locked at funding. Anything else is refused.

/// SPL Token program, TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA
pub const TOKEN_PROGRAM: [u8; 32] = [
    6, 221, 246, 225, 215, 101, 161, 147, 217, 203, 225, 70, 206, 235, 121, 172, 28, 180, 133, 237, 95, 91, 55, 145, 58, 140, 245, 133, 126, 255, 0, 169,
];
const TRANSFER_CHECKED: u8 = 12;

const B58: &[u8] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/// A 32-byte Solana address from base58, or None
pub fn b58_32(s: &str) -> Option<[u8; 32]> {
    let mut out: Vec<u8> = Vec::with_capacity(32);
    for c in s.bytes() {
        let mut carry = B58.iter().position(|&x| x == c)? as u32;
        for b in out.iter_mut() {
            carry += (*b as u32) * 58;
            *b = (carry & 0xff) as u8;
            carry >>= 8;
        }
        while carry > 0 {
            out.push((carry & 0xff) as u8);
            carry >>= 8;
        }
    }
    let zeros = s.bytes().take_while(|&c| c == b'1').count();
    out.extend(std::iter::repeat(0).take(zeros));
    out.reverse();
    out.try_into().ok()
}

fn compact_u16(m: &[u8], at: &mut usize) -> Option<usize> {
    let mut v = 0usize;
    for shift in [0, 7, 14] {
        let b = *m.get(*at)? as usize;
        *at += 1;
        v |= (b & 0x7f) << shift;
        if b & 0x80 == 0 {
            return Some(v);
        }
    }
    None
}

/// What the message pays: (payer and owner key, source, mint, destination, amount)
pub struct Transfer {
    pub owner: [u8; 32],
    pub mint: [u8; 32],
    pub destination: [u8; 32],
    pub amount: u64,
}

pub fn parse_transfer(m: &[u8]) -> Result<Transfer, &'static str> {
    if m.len() < 3 || m[0] & 0x80 != 0 {
        return Err("the payout must be a legacy Solana message");
    }
    if m[0] != 1 {
        return Err("the payout must have one signer");
    }
    let mut at = 3;
    let n = compact_u16(m, &mut at).ok_or("message")?;
    let keys: Vec<[u8; 32]> = (0..n)
        .map(|i| m.get(at + 32 * i..at + 32 * (i + 1)).and_then(|s| s.try_into().ok()))
        .collect::<Option<_>>()
        .ok_or("message")?;
    at += 32 * n + 32; // the keys, then the recent blockhash
    let ixs = compact_u16(m, &mut at).ok_or("message")?;
    if ixs != 1 {
        return Err("the payout must be one instruction");
    }
    let program = *keys.get(*m.get(at).ok_or("message")? as usize).ok_or("message")?;
    at += 1;
    let na = compact_u16(m, &mut at).ok_or("message")?;
    let accts: Vec<usize> = m.get(at..at + na).ok_or("message")?.iter().map(|&x| x as usize).collect();
    at += na;
    let nd = compact_u16(m, &mut at).ok_or("message")?;
    let data = m.get(at..at + nd).ok_or("message")?;
    if at + nd != m.len() {
        return Err("message");
    }
    if program != TOKEN_PROGRAM {
        return Err("the payout must be an SPL Token transfer");
    }
    if na != 4 || nd != 10 || data[0] != TRANSFER_CHECKED {
        return Err("the payout must be TransferChecked");
    }
    let key = |i: usize| keys.get(accts[i]).copied().ok_or("message");
    // TransferChecked accounts: source, mint, destination, owner; the owner is the one signer (index 0)
    if accts[3] != 0 {
        return Err("the payout's owner must be its signer");
    }
    let amount = u64::from_le_bytes(data[1..9].try_into().unwrap());
    Ok(Transfer { owner: key(3)?, mint: key(1)?, destination: key(2)?, amount })
}
