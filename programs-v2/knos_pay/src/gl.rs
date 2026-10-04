//! Reading a GitLab CI ID token that knos-oidc verified under a gitlab.com key, as the claims every instruction
//! already judges (`Gh`). gh.rs hands a token over (`order_token` and `token_of`: a work order's funding and its
//! payment, nothing else) when the verifier says its issuer is GitLab; the account, its freshness and its key have
//! been checked there. What GitLab signs is documented at
//! https://docs.gitlab.com/ci/secrets/id_token_authentication/ (read 4 Oct 2026).
//!
//! WHAT A GITLAB TOKEN MAY DO: fund an order from a Balance (audience knos3:fund:...) and pay an order (audience
//! knos3:pay:...). Every other audience is refused here (E_AUD), so no other instruction takes one: no 2.0 job, no
//! Bind, no faucet, no Reserve, Cancel, Revert or ruling.
//!
//! IDS. GitHub has one id space for accounts (owners and actors) and one for repositories. GitLab has three: users,
//! namespaces (a group, a subgroup, or a user's own namespace: never the user's id) and projects. They are moved
//! into ranges no GitHub id is read from, in decimal so that an audience can still carry them (18 digits at most):
//!   project_id   -> GL_ID + project_id     `repo_id`
//!   user_id      -> GL_ID + user_id        `actor_id`: a payee, a spender, a funder
//!   namespace_id -> GL_NS + namespace_id   `owner_id`: whose Balance pays
//! A raw id is 1..=GL_MAX. gh.rs refuses a GitHub token whose repository, owner or actor id is GL_NS or more
//! (`not_ours`), so no token of GitHub's and no token under a private key names a GitLab project, user or namespace,
//! and no GitLab token names a GitHub one. A namespace is never equal to a user, so every rule that asks "the actor
//! owns the repository" (a neutral run, a ruling, a Balance spent by its owner without being listed) refuses a GitLab
//! token: GitLab signs nothing that says a namespace is that user's own. A Balance for a GitLab namespace lists its
//! spenders, as GL_ID + user id.
//!
//! THE PIN. `ci_config_ref_uri` ("gitlab.com/<project path>//<file>@<ref path>") says which file defined the
//! pipeline and on which ref; `ci_config_sha` is the commit that fixes its content. Both are null when the file is
//! in another project, and such a token is refused. An order pins sha256 of the whole URI and the commit, in the
//! fields that hold a GitHub order's workflows repository and commit; the hash of a URI that starts "gitlab.com/"
//! and has "//" in it is never the hash of a GitHub "owner/name". GitLab has no claim like `job_workflow_sha` for a
//! file kept apart from the code: `ci_config_sha` is the commit the pipeline ran on. So the pinned file lives on a
//! protected branch that does not move (the example calls it `knos`), and a pipeline of any other commit, the
//! default branch after a merge included, is refused with E_WORKFLOW. The merge's own pipeline triggers the pinned
//! one (`trigger:` with `branch: knos`), and the pinned job reads the merge request from GitLab's API before it asks
//! for a token: the claims do not say what was merged, nor which branch is the default one.
//!
//! WHICH PIPELINE. Always: `runner_environment` gitlab-hosted, `ref_type` branch, `ref_protected` "true" (only
//! people the project allows start a pipeline on a protected branch, and a merge request from a fork never runs on
//! one), the URI is of the token's own project and ref. Then by audience:
//!   knos3:fund  `pipeline_source` web: a person ran the pipeline by hand, and `user_id` is that person. Read as the
//!               program's fund.yml answering an issue event, so a public order is funded.
//!   knos3:pay   `pipeline_source` pipeline: a pipeline of the project started it, the merge's. Read as prove.yml.
//!
//! WHAT GITLAB DOES NOT SIGN. No attempt number: a retried job is a new job of the user who retried it, so the
//! token names who asked, which is what `run_attempt` protects on GitHub, and `first_attempt` is set. No default
//! branch, no merge request, no workflow commit apart from the pipeline's (above).
use crate::{err, gh::Gh, E_AUD, E_CLAIMS, E_TOKEN, TOKEN_AHEAD, TOKEN_LIFE};
use knos_oidc::claims::{self, fields, number, text};
use solana_program::{hash::hashv, program_error::ProgramError};

/// Where GitLab's namespace ids start, and its project and user ids. No GitHub id is read at or above GL_NS.
pub const GL_NS: u64 = 800_000_000_000_000_000;
pub const GL_ID: u64 = 900_000_000_000_000_000;
/// The largest id GitLab may sign: GL_ID + GL_MAX is still 18 digits, which is what an audience can carry.
pub const GL_MAX: u64 = 99_999_999_999_999_999;
/// `ci_config_ref_uri` starts with the host of the one GitLab issuer knos-oidc numbers (pins::ISSUERS[1]).
pub const HOST: &[u8] = b"gitlab.com/";

/// A GitHub id is below every GitLab range. Called by gh.rs on the ids of every token that is not GitLab's.
pub fn not_ours(id: u64) -> Result<u64, ProgramError> { if id < GL_NS { Ok(id) } else { Err(err(E_CLAIMS)) } }

fn id(raw: u64, base: u64) -> Result<u64, ProgramError> { if (1..=GL_MAX).contains(&raw) { Ok(base + raw) } else { Err(err(E_CLAIMS)) } }

/// The claims of a GitLab token, as the module documentation maps them. `payload`: the token's JSON, verified.
pub fn read(payload: &[u8], exp: i64, now: i64) -> Result<Gh, ProgramError> {
    let [project, namespace, user, iat, uri, sha, runner, aud, source, ref_type, ref_path, protected, path] = fields(payload,
        [b"project_id", b"namespace_id", b"user_id", b"iat", b"ci_config_ref_uri", b"ci_config_sha", b"runner_environment", b"aud", b"pipeline_source",
         b"ref_type", b"ref_path", b"ref_protected", b"project_path"])?;
    let iat = number(iat)? as i64;
    if iat > now.saturating_add(TOKEN_AHEAD) || exp.saturating_sub(iat) > TOKEN_LIFE { return Err(err(E_TOKEN)); }
    if text(runner)? != b"gitlab-hosted" || text(ref_type)? != b"branch" || text(protected)? != b"true" { return Err(err(E_CLAIMS)); }
    // the pin: the file is in the token's own project (null otherwise: `text` refuses it) on the ref the pipeline ran on
    let (uri, sha) = (text(uri)?, text(sha)?);
    let (head, tail) = ([HOST, &text(path)?, b"//"].concat(), [b"@", &text(ref_path)?[..]].concat());
    let file = uri.len() > head.len() + tail.len() && uri.starts_with(&head) && uri.ends_with(&tail);
    if !file || !claims::is_hex(&sha, 40) { return Err(err(E_CLAIMS)); }
    let (aud, source) = (text(aud)?, text(source)?);
    let (wants, wf_file, event): (&[u8], &[u8], &[u8]) = if aud.starts_with(b"knos3:fund:") { (b"web", crate::order_judge::FUND, b"issues") }
        else if aud.starts_with(b"knos3:pay:") { (b"pipeline", crate::order_judge::PROVE, b"pipeline") }
        else { return Err(err(E_AUD)) };
    if source != wants { return Err(err(E_CLAIMS)); }
    Ok(Gh { repo_id: id(number(project)?, GL_ID)?, owner_id: id(number(namespace)?, GL_NS)?, actor_id: id(number(user)?, GL_ID)?, iat,
            wf_repo: hashv(&[&uri]).to_bytes(), wf_file: wf_file.to_vec(), wf_sha: sha, aud, event: event.to_vec(), repository: None,
            first_attempt: true, wf_ref: uri })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn token(over: &[(&str, &str)]) -> Vec<u8> {
        let mut c = vec![("project_id", "\"20\""), ("namespace_id", "\"72\""), ("user_id", "\"1\""), ("iat", "1000"), ("project_path", "\"g/p\""),
                         ("ci_config_ref_uri", "\"gitlab.com/g/p//.gitlab-ci.yml@refs/heads/knos\""), ("ci_config_sha", "\"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\""),
                         ("runner_environment", "\"gitlab-hosted\""), ("aud", "\"knos3:fund:x\""), ("pipeline_source", "\"web\""), ("ref_type", "\"branch\""),
                         ("ref_path", "\"refs/heads/knos\""), ("ref_protected", "\"true\"")];
        for (k, v) in over { c.iter_mut().find(|e| e.0 == *k).unwrap().1 = v; }
        format!("{{{}}}", c.iter().map(|(k, v)| format!("\"{k}\":{v}")).collect::<Vec<_>>().join(",")).into_bytes()
    }
    fn code(over: &[(&str, &str)]) -> Option<u32> {
        match read(&token(over), 1300, 1000) { Ok(_) => None, Err(ProgramError::Custom(c)) => Some(c), Err(_) => Some(0) }
    }

    #[test]
    fn a_gitlab_token_is_read_into_ranges_of_its_own_and_two_roles() {
        let g = read(&token(&[]), 1300, 1000).ok().unwrap();
        assert_eq!((g.repo_id, g.owner_id, g.actor_id), (GL_ID + 20, GL_NS + 72, GL_ID + 1));
        assert!(g.wf_file == b"fund.yml" && g.event == b"issues" && g.first_attempt && g.wf_sha == [b'e'; 40]);
        assert_eq!(g.wf_repo, hashv(&[b"gitlab.com/g/p//.gitlab-ci.yml@refs/heads/knos"]).to_bytes());
        let p = read(&token(&[("aud", "\"knos3:pay:x\""), ("pipeline_source", "\"pipeline\"")]), 1300, 1000).ok().unwrap();
        assert!(p.wf_file == b"prove.yml" && p.wf_repo == g.wf_repo);
        // a namespace is never a user, whatever their numbers; the ranges do not meet and stay within 18 digits
        assert_ne!(read(&token(&[("namespace_id", "\"1\"")]), 1300, 1000).ok().unwrap().owner_id, g.actor_id);
        const { assert!(GL_NS + GL_MAX < GL_ID && GL_ID + GL_MAX < 1_000_000_000_000_000_000) };
        assert!(not_ours(GL_NS - 1).is_ok() && not_ours(GL_NS).is_err() && not_ours(GL_ID + 20).is_err());
    }

    #[test]
    fn everything_else_is_refused() {
        for (k, v, want) in [("ref_protected", "\"false\"", E_CLAIMS), ("ref_protected", "true", 63), ("ref_type", "\"tag\"", E_CLAIMS),
                             ("runner_environment", "\"self-hosted\"", E_CLAIMS), ("pipeline_source", "\"push\"", E_CLAIMS),
                             ("pipeline_source", "\"pipeline\"", E_CLAIMS), ("ci_config_ref_uri", "null", 63), ("ci_config_sha", "null", 63),
                             ("ci_config_ref_uri", "\"gitlab.com/g/other//.gitlab-ci.yml@refs/heads/knos\"", E_CLAIMS),
                             ("ci_config_ref_uri", "\"gitlab.com/g/p//.gitlab-ci.yml@refs/heads/main\"", E_CLAIMS),
                             ("ci_config_ref_uri", "\"gitlab.com/g/p//@refs/heads/knos\"", E_CLAIMS),
                             ("ci_config_ref_uri", "\"gitlab.example.com/g/p//.gitlab-ci.yml@refs/heads/knos\"", E_CLAIMS),
                             ("ci_config_sha", "\"abc\"", E_CLAIMS), ("project_id", "\"0\"", E_CLAIMS), ("user_id", "\"100000000000000000\"", E_CLAIMS),
                             ("namespace_id", "\"900000000000000001\"", E_CLAIMS), ("aud", "\"knos2:fund:x\"", E_AUD), ("aud", "\"knos3:take:x\"", E_AUD),
                             ("aud", "\"knos3:rule:x\"", E_AUD), ("aud", "\"knos3:bind:x\"", E_AUD), ("iat", "1301", E_TOKEN)] {
            assert_eq!(code(&[(k, v)]), Some(want), "{k} {v}");
        }
        assert_eq!(code(&[("aud", "\"knos3:pay:x\"")]), Some(E_CLAIMS));          // a pipeline run by hand pays nothing
        assert!(read(&token(&[]), 1000 + TOKEN_LIFE + 1, 1000).is_err());
    }
}
