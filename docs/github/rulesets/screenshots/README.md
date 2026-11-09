# Screenshot provenance

These are real GitHub browser captures illustrating repository settings. They are UI examples, not account-specific instructions or evidence that git-tools installs these policies. Use your own repository and accounts. GitHub labels and layout can change.

| File | What it shows | Interpretation |
| --- | --- | --- |
| `01-rulesets-overview.png` | PR-only, history-protection, and allowed-merger rulesets | Saved example of the solo preset: policies 1, 2, and 4 |
| `02-pr-targets-and-bot.png` | Automation bypass and exact develop/master targets | Saved example; substitute your own automation account |
| `03-pr-merge-methods.png` | Optional review flags and Merge-only selector | Saved PR-only example; zero approvals is confirmed separately, outside the frame |
| `04-history-protection.png` | Deletion and force-push restrictions | Saved example; verify empty bypasses and exact targets separately |
| `05-merge-message-default.png` | General → Pull Requests with the message default selected | Saved setting: **Pull request title and description** |
| `06-review-options-example.png` | One approval, stale-approval dismissal, Code Owner review | Partial **unsaved example** of optional policy 3, not an active review rule |
| `07-merger-bypass-example.png` | One human PR-only bypass and one automation Always allow bypass | Saved UI example; the displayed identities are not required configuration |
| `08-merger-update-rule.png` | Restrict updates without other branch rules | Saved example of policy 4's separate update restriction |
| `09-merge-message-options.png` | Expanded Default commit message menu | Saved selection shown without changing it; demonstrates the available title/body choices |

Images 05 and 09 show message settings, not a completed merge. The PR title becomes the default merge commit subject, and the PR description becomes its default body. The merger can still edit the message.

Image 06 is deliberately an unsaved draft. No screenshot proves a successful or rejected push/merge, credential isolation, or an end-to-end review test.

The automation **Always allow** exception is identity-wide: it can permit bot PR merges as well as direct publication pushes. History protection remains a separate no-bypass policy.
