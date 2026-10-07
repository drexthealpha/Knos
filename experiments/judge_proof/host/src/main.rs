//! judge-host image <guest elf> <program out>             wrap the guest with the kernel, print the image id
//! judge-host plain <checks> <submission>                 run the same judge with no proof, print the journal
//! judge-host prove <program> <submission> <receipt out> [composite|succinct|groth16]
//! judge-host verify <receipt> <image id hex>             verify, print the journal the proof commits to
#[path = "../../guest/src/judge.rs"]
mod judge;

use anyhow::{bail, Context, Result};
use risc0_binfmt::ProgramBinary;
use risc0_zkvm::sha::Digest;
use risc0_zkvm::{default_prover, ExecutorEnv, ProverOpts, Receipt};
use sha2::{Digest as _, Sha256};
use std::fs;
use std::time::Instant;

fn sha(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn show(journal: &[u8]) -> Result<()> {
    if journal.len() != judge::JOURNAL_LEN || journal[0] != judge::VERSION {
        bail!("not a judge journal: {} bytes", journal.len());
    }
    println!("journal {}", hex::encode(journal));
    println!("submission_sha256 {}", hex::encode(&journal[1..33]));
    println!("checks_sha256 {}", hex::encode(&journal[33..65]));
    println!("verdict {}", if journal[65] == 1 { "passed" } else { "failed" });
    println!(
        "cases {} of {}",
        u16::from_le_bytes([journal[66], journal[67]]),
        u16::from_le_bytes([journal[68], journal[69]])
    );
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let arg = |i: usize| args.get(i).map(String::as_str).context("missing argument; see the top of host/src/main.rs");
    match arg(0)? {
        "image" => {
            let elf = fs::read(arg(1)?)?;
            let program = ProgramBinary::new(&elf, risc0_zkos_v1compat::V1COMPAT_ELF);
            fs::write(arg(2)?, program.encode())?;
            println!("image_id {}", hex::encode(program.compute_image_id()?.as_bytes()));
        }
        "plain" => {
            let (checks, submission) = (fs::read(arg(1)?)?, fs::read(arg(2)?)?);
            let verdict = judge::judge(&checks, &submission);
            show(&judge::journal(&sha(&submission), &sha(&checks), &verdict))?;
        }
        "prove" => {
            let (program, submission) = (fs::read(arg(1)?)?, fs::read(arg(2)?)?);
            let opts = match args.get(4).map(String::as_str).unwrap_or("succinct") {
                "composite" => ProverOpts::composite(),
                "succinct" => ProverOpts::succinct(),
                "groth16" => ProverOpts::groth16(),
                other => bail!("unknown kind of receipt: {other}"),
            };
            let env = ExecutorEnv::builder().write_slice(&submission).build()?;
            let started = Instant::now();
            let info = default_prover().prove_with_opts(env, &program, &opts)?;
            let seconds = started.elapsed().as_secs_f64();
            let bytes = bincode::serialize(&info.receipt)?;
            fs::write(arg(3)?, &bytes)?;
            println!("prove_seconds {seconds:.2}");
            println!("receipt_bytes {}", bytes.len());
            println!("seal_bytes {}", info.receipt.seal_size());
            println!("user_cycles {}", info.stats.user_cycles);
            println!("total_cycles {}", info.stats.total_cycles);
            println!("segments {}", info.stats.segments);
            show(&info.receipt.journal.bytes)?;
        }
        "verify" => {
            let receipt: Receipt = bincode::deserialize(&fs::read(arg(1)?)?)?;
            let mut id = [0u8; 32];
            hex::decode_to_slice(arg(2)?, &mut id).context("the image id is 64 hex characters")?;
            let started = Instant::now();
            receipt.verify(Digest::from(id)).context("the receipt does not verify against this image id")?;
            println!("verify_seconds {:.3}", started.elapsed().as_secs_f64());
            println!("verified true");
            show(&receipt.journal.bytes)?;
        }
        other => bail!("unknown command: {other}"),
    }
    Ok(())
}
