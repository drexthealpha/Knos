"""The three open, computer-checkable briefs an AI scientist can win (knos_wanted.valley.solver_briefs). Data, kept
as Python: the app holds no JSON files but its two data files (apps/wanted/tests/test_repo_rules.py holds it)."""

BRIEFS = {'about': 'Three open briefs whose proof is a computation, opened by the operator with '
          "valley.open_solver_briefs and funded from the app's devnet test wallet (valley.operator_fund_solver). "
          'Devnet test money only.',
 'briefs': [{'id': 'lean_formal_conjecture',
             'title': 'Lean proof of one open formal-conjectures statement',
             'note': "No autonomous release path today: the referee's lake build and #print axioms re-run is posted "
                     'as the independent check (knos_project_post) and the referee panel releases.',
             'release': 'result + independent check: the referee re-runs lake build and #print axioms at the pinned '
                        'commit',
             'brief': {'milestones': [{'key': 'lean_proof',
                                       'name': 'Lean proof of one open statement in '
                                               'google-deepmind/formal-conjectures',
                                       'target': '1 theorem compiles with 0 sorry and only standard axioms at a '
                                                 'pinned commit (9356e56): 0 errors in lake build',
                                       'verifier': {'kind': 'machine',
                                                    'check': 'lake build and #print axioms (referee re-run)'},
                                       'deadline_days': 38}],
                       'kill_fee_bps': 0,
                       'challenge_s': 259200}},
            {'id': 'modded_nanogpt_record',
             'title': 'New modded-nanogpt speedrun record',
             'note': "No autonomous release path today: the referee's re-run on a rented 8xH100 is posted as the "
                     'independent check (knos_project_post) and the referee panel releases.',
             'release': 'result + independent check: the referee re-runs the record on a rented 8xH100',
             'brief': {'milestones': [{'key': 'speedrun_record',
                                       'name': 'A new modded-nanogpt short-track speedrun record',
                                       'target': 'under 0.665 min to val loss 3.28 on 8xH100',
                                       'verifier': {'kind': 'machine', 'check': 'referee re-run on rented 8xH100'},
                                       'deadline_days': 60}],
                       'kill_fee_bps': 0,
                       'challenge_s': 259200}},
            {'id': 'autoresearch_round',
             'title': 'Beat the sealed classifier: the autoresearch round, funded',
             'note': 'The only one of the three with an autonomous release path today: knos_milestone_submit sends '
                     'the train.py to the open round, its sealed referee judges it, and a verdict that meets the '
                     "target releases the money held with no human step. The margin is read from the round's shown "
                     '(Ladder) scores, which round down to 0.01.',
             'release': "the round's sealed referee: a scored submission whose shown accuracy is at least 0.5 "
                        "percentage points above the baseline's releases at once",
             'brief': {'milestones': [{'key': 'beat_baseline',
                                       'name': 'A train.py that beats the sealed classifier baseline',
                                       'target': 'accuracy at least 0.5 percentage points above the baseline '
                                                 'train.py on the sealed test set',
                                       'verifier': {'kind': 'machine', 'check': 'knos-referee:{round}'},
                                       'deadline_days': 30}],
                       'kill_fee_bps': 0,
                       'challenge_s': 259200}}]}
