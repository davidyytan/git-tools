# Publishing Version Commits and Tags

Version bumping and publication are separate operations. [`git-tools bump`](usage.md#bump) updates and commits managed version files and normally creates a local tag; it never pushes. The GitHub and Azure DevOps CI adapters then call the shared publisher:

```bash
python -m git_tools.generators.publish --branch develop --create-tag true
```

Run the publisher from the **application repository checkout**, with the git-tools engine available on Python's import path. CI templates set `PYTHONPATH` to their cloned engine directory. Both adapters use the selected remote git-tools engine ref: that ref must contain the publisher and required strategy implementation. Editing a local git-tools checkout does not update the remote engine clone.

For installation/configuration, see the [project README](../README.md) and [configuration guide](configuration.md). For pipeline activation, credentials, signing, and branch policy, use the [GitHub](github/README.md) or [Azure DevOps](azure-devops/README.md) guides rather than treating this helper as a full release workflow.

## Publisher interface

This is a Python module entry point, **not** a `git-tools publish` subcommand.

| Argument | Behavior |
| --- | --- |
| `--branch NAME` | Required destination branch; pushes local `HEAD` to `refs/heads/NAME` |
| `--remote NAME` | Remote name or URL; default `origin`. Empty values and values starting with `-` are rejected |
| `--create-tag true\|false` | Default `false`: publish only the branch. `true` also publishes the exact configured version tag |
| `--recover-tag` | Publish only the expected version tag after checking the remote branch tip equals local `HEAD`; implies tag validation regardless of `--create-tag` |

`--create-tag true` is a literal argument value, not a standalone Boolean flag. The publisher does not compute a version, create a commit/tag, choose a CI strategy, or call hosting APIs. It returns a nonzero exit status on failure.

### Preconditions and scope

Before normal publication, the helper validates the destination branch ref and resolves local `HEAD`. When publishing a tag, it loads the bump configuration, derives the expected tag from its current version and tag format, validates the tag ref, and requires that the local tag's peeled commit equals `HEAD`.

It sends these exact refspecs:

```text
HEAD:refs/heads/<branch>
refs/tags/<expected-tag>:refs/tags/<expected-tag>   # Only when requested
```

It never sends all local tags and does not force updates. Normal Git permission, non-fast-forward, and existing-tag rules still apply. The `--branch` value is the **destination**; the helper does not require the checked-out branch name to match it. Verify the checkout and intended destination before running it.

The publisher checks tag identity/target, not cryptographic signatures or the cleanliness of the working tree. Signing policy must already have been enforced during tag creation. Branch-only publication does not require a version tag or load the version configuration.

## Atomic publication and fallback

```text
Validate destination branch and HEAD
Validate expected tag points to HEAD, if requested
                         |
                         v
Dry-run atomic push of exact requested refs
                         |
          +--------------+----------------+
          |              |                |
       Accepted      Unsupported       Other failure
          |              |                |
          v              v                v
Log atomic mode    Log non-atomic mode   Stop; no fallback
Atomic push        Branch push -> tag push (if requested)
          |              |
          v              v
Success or fail    Success or explicit partial-publication error
```

The fallback is deliberately narrow: the failed dry run must report that the receiving end `does not support --atomic push`. Authentication, connectivity, ref conflicts, and other dry-run failures stop publication. If the **actual** atomic push fails after a successful dry run, the helper stops rather than retrying non-atomically.

A dry run checks capability and preflight state, not a guarantee that hooks, permissions, or concurrent changes will allow the actual push. Logs identify the branch, optional tag, selected mode, and successful publication stages. On a server supporting atomic pushes, the requested branch/tag updates succeed or fail together. On an unsupported server, the branch is pushed first, then the tag; failure of the second operation can leave the branch published without its tag.

## Recover a missing tag

If fallback branch publication succeeds but tag publication fails, the job fails and prints a recovery command. A fresh strategy run may skip the already-generated bump commit; **rerunning the pipeline is not automatic missing-tag recovery**.

1. Inspect the failed job and remote refs. Fix the underlying permission, conflict, or connectivity issue first.
2. Preserve the checkout containing the original tag, particularly a signed tag. Hosted runners may discard it after the job; do not assume a fresh clone can recover an unpublished tag object.
3. Verify that local `HEAD` equals the remote destination branch tip, the configured version matches the published bump, and its exact local version tag points to `HEAD`.
4. From that application checkout, with the supported engine on the import path, run:

   ```bash
   python -m git_tools.generators.publish --branch develop --recover-tag
   ```

   Substitute the actual destination branch and use `--remote <name>` if it is not `origin`. In CI-style clones, set `PYTHONPATH` to the cloned git-tools directory as the adapter does.

Recovery performs a remote-tip check and then pushes **only the expected tag**. It does not bump the version, create a tag/commit, or update the branch. It refuses if the checked remote branch tip differs from local `HEAD`, or if the local tag targets another commit. This check is a point-in-time check, not a lock on concurrent branch movement.

If the original local tag is lost, an authorized release operator must reconstruct and verify the intended tag using repository signing policy before running recovery. Do not blindly tag the newest branch tip or force-replace a conflicting remote tag. A newly created signature/tag object is not recovery of the original unpublished signed object; document any reconstruction according to release policy.

## Shell data boundary and trust

The supplied GitHub and Azure templates pass strategy decision values through environment variables rather than interpolating them into shell source. Diagnostic decision text is JSON-escaped so embedded newlines cannot become separate CI logging commands. Bump arguments are parsed with `shlex.split` and sent as a subprocess argument list, never `eval` or `shell=True`. Azure logging-command output values escape percent signs and line breaks; GitHub output records flatten line breaks so a value cannot add records.

These boundaries keep commit-derived text from becoming shell code; they do **not** make arbitrary pipeline YAML or a remote engine ref trustworthy. Restrict changes to credentialed workflows, CI secret settings, and signing/push identities. Pin and review the engine ref according to repository policy, and validate the selected CI template on a disposable repository before production activation.

The offline tests in `tests/test_publish.py` cover exact refs, expected-tag target validation, fallback restrictions, real local atomic rejection, and non-atomic partial publication/recovery. `tests/test_pipeline_safety.py` checks decision logging, argument-list execution, and CI output escaping. They are not evidence of production permissions, signing credentials, or hosting-server behavior.
