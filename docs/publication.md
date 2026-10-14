# Publishing Version Commits and Tags

Both CI adapters call `python -m git_tools.generators.publish` from the selected
remote git-tools engine ref. That ref must contain the publisher module as well
as the required strategy support. Local changes do not update the remote clone.

```text
Validate branch and expected version tag (tag must point to HEAD)
                         |
                         v
Dry-run atomic push of exact branch + expected tag refs
                         |
          +--------------+----------------+
          |              |                |
       Accepted      Unsupported       Other failure
          |              |                |
          v              v                v
Log atomic mode    Log non-atomic mode   Stop; no fallback
Atomic push        Branch push -> tag push
          |              |
          v              v
Success or fail    Success or explicit partial-publication error
```

Only the expected version tag is sent, never all local tags. Authentication,
connectivity, ref conflicts, or other dry-run failures do not trigger fallback.
If the actual atomic push fails, the helper stops rather than retrying
non-atomically. A dry run checks capability and preflight state, not a guarantee
that hooks, permissions, or concurrent changes will allow the actual push.
Logs identify the branch, tag, selected mode, and successful publication stages.

## Recover a Missing Tag

The unsupported-server fallback still has two operations. If branch publication
succeeds but tag publication fails, the pipeline fails with recovery instructions.
A normal fresh strategy run may skip the already-generated bump commit: it is
not automatic missing-tag recovery.

1. Inspect the failed job and remote refs; fix the permission/conflict/network cause.
2. Preserve the checkout containing the original signed tag when possible. Hosted
   runners may discard it after the job, so do not assume it can be recovered later.
3. Ensure local HEAD equals the remote target branch tip, the configured version
   matches the published bump, and its exact local tag points to HEAD.
4. From that application checkout, with the supported git-tools engine available:

   ```bash
   python -m git_tools.generators.publish --branch develop --recover-tag
   ```

   Substitute the actual branch; use `--remote <name>` if it is not `origin`.
   In CI clones, set `PYTHONPATH` to the cloned git-tools directory as the adapter does.

Recovery publishes only the tag: no new version bump, commit, or branch update.
It refuses if the remote branch has moved or the local tag targets another commit.
If the original local tag is lost, an authorized release operator must reconstruct
and verify the intended signed tag using the repository's signing policy before
running recovery. Do not blindly tag the newest branch tip or force-replace a
conflicting remote tag. This is explicit operator-assisted recovery, not a claim
of automatic recovery after a fresh runner loses the tag.

## Shell Data Boundary and Trust

All supplied templates pass decision values through environment variables, not
inline shell-source interpolation. Diagnostic text is JSON-escaped so embedded
newlines do not introduce CI logging commands. Bump arguments are parsed with
`shlex.split` and sent as a subprocess argument list, never `eval` or `shell=True`.
Azure logging-command values escape percent signs and line breaks; GitHub output
records flatten line breaks so values cannot add records.

These boundaries stop commit text from becoming shell code; they do not make
arbitrary pipeline YAML trustworthy. Restrict changes to credentialed workflows,
Secure File permissions, and signing/push identities. Validate the published
engine ref and target CI behavior offsite before activation.
