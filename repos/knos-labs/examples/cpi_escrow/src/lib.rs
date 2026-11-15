//! An on-chain agent that takes Knos escrow jobs: it CPIs into the escrow's `claim` (tag 2) and `deliver` (tag 3).
//!
//! The agent is a PDA of this program, ["agent"]; it is the job's worker and signs the escrow calls with
//! invoke_signed. Its token account (owned by the agent PDA, same mint as the escrow config) pays the claim stake and
//! gets it back on delivery. Account metas follow programs/knos_escrow/idl.json.
//!
//! Instructions of this program (one-byte tag, like the escrow):
//!   0 TakeJob:    agent, job(w), agent_token(w), vault_token(w), config2, token_program, escrow_program
//!   1 DeliverJob: agent, job(w), agent_token(w), vault_token(w), vault_auth, token_program, escrow_program
//!                 data: result_hash[32]
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    entrypoint::ProgramResult,
    instruction::{AccountMeta, Instruction},
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
};

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

/// The Knos escrow on devnet (pass another id for a local validator: the escrow_program account is checked against
/// the job account's owner, not hard-coded).
pub const KNOS_ESCROW: Pubkey = solana_program::pubkey!("GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq");
const CLAIM: u8 = 2;
const DELIVER: u8 = 3;

/// The escrow's Claim: worker(s), job(w), worker_token(w), vault_token(w), config2, token_program.
pub fn claim_ix(escrow: &Pubkey, worker: &Pubkey, job: &Pubkey, worker_token: &Pubkey, vault_token: &Pubkey,
                config: &Pubkey, token_program: &Pubkey) -> Instruction {
    Instruction {
        program_id: *escrow,
        accounts: vec![
            AccountMeta::new_readonly(*worker, true),
            AccountMeta::new(*job, false),
            AccountMeta::new(*worker_token, false),
            AccountMeta::new(*vault_token, false),
            AccountMeta::new_readonly(*config, false),
            AccountMeta::new_readonly(*token_program, false),
        ],
        data: vec![CLAIM],
    }
}

/// The escrow's Deliver: worker(s), job(w), worker_token(w), vault_token(w), vault_auth, token_program;
/// data result_hash[32].
#[allow(clippy::too_many_arguments)]
pub fn deliver_ix(escrow: &Pubkey, worker: &Pubkey, job: &Pubkey, worker_token: &Pubkey, vault_token: &Pubkey,
                  vault_auth: &Pubkey, token_program: &Pubkey, result_hash: &[u8; 32]) -> Instruction {
    let mut data = vec![DELIVER];
    data.extend_from_slice(result_hash);
    Instruction {
        program_id: *escrow,
        accounts: vec![
            AccountMeta::new_readonly(*worker, true),
            AccountMeta::new(*job, false),
            AccountMeta::new(*worker_token, false),
            AccountMeta::new(*vault_token, false),
            AccountMeta::new_readonly(*vault_auth, false),
            AccountMeta::new_readonly(*token_program, false),
        ],
        data,
    }
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let it = &mut accounts.iter();
    let agent = next_account_info(it)?;
    let job = next_account_info(it)?;
    let agent_tok = next_account_info(it)?;
    let vault_tok = next_account_info(it)?;
    let fifth = next_account_info(it)?; // config2 (claim) or vault_auth (deliver)
    let token = next_account_info(it)?;
    let escrow = next_account_info(it)?;

    let (agent_key, bump) = Pubkey::find_program_address(&[b"agent"], program_id);
    if *agent.key != agent_key { return Err(ProgramError::InvalidSeeds); }
    // The job must belong to the escrow program we are calling.
    if job.owner != escrow.key || !escrow.executable { return Err(ProgramError::IncorrectProgramId); }
    let seeds: &[&[u8]] = &[b"agent", &[bump]];

    let ix = match tag {
        0 => claim_ix(escrow.key, agent.key, job.key, agent_tok.key, vault_tok.key, fifth.key, token.key),
        1 => {
            let result: [u8; 32] = rest.get(..32).ok_or(ProgramError::InvalidInstructionData)?.try_into().unwrap();
            deliver_ix(escrow.key, agent.key, job.key, agent_tok.key, vault_tok.key, fifth.key, token.key, &result)
        }
        _ => return Err(ProgramError::InvalidInstructionData),
    };
    invoke_signed(&ix, &[agent.clone(), job.clone(), agent_tok.clone(), vault_tok.clone(), fifth.clone(), token.clone(),
                         escrow.clone()], &[seeds])
}
