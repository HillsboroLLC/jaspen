# Production security cutover

These repository artifacts are locally testable preparation. They do not
authorize or claim a live production change. The existing deployment remains
available through a compatibility path until every cutover check below passes.

## Administrator actions

1. In the GitHub `production` Environment, require an administrator approval
   before deployment. Move the existing deployment values into that Environment.
   Add `SERVER_SSH_KNOWN_HOSTS` using the Droplet's **public** SSH host-key line
   verified through the DigitalOcean console or another trusted channel. Do not
   obtain the key from the same network connection the workflow will trust.
2. On the Droplet, create non-login `jaspen-app` and `jaspen-migrate` identities
   and a restricted `jaspen-deploy` SSH identity. Do not add any of them to a
   general administrative group.
3. Install `deploy/production/jaspen-deploy`, `jaspen-migrate`, and
   `jaspen-ssh-dispatch` as root-owned mode `0755` files in `/usr/local/sbin`.
   Install `deploy.conf` as root-owned
   mode `0644` in `/etc/jaspen`, setting the existing checkout's absolute path
   and actual deployment account. The file contains no credentials.
4. Create `/etc/jaspen/runtime.env` as `root:jaspen-app` mode `0640` and
   `/etc/jaspen/migration.env` as `root:jaspen-migrate` mode `0640`. Preserve the
   currently required application variable names without printing values. The
   runtime file references only the runtime database credential; the migration
   file references only the separate migration credential.
5. Install `jaspen-migrate.service` in `/etc/systemd/system`. First validate the
   `gunicorn-sekki-security.conf` drop-in with `systemd-analyze verify`, then
   confirm the `jaspen-app` identity can traverse the checkout and execute the
   venv before installing the drop-in. Run `systemctl daemon-reload`.
6. Restrict the GitHub deployment public key in the deployment identity's
   `authorized_keys` with `restrict,command="/usr/local/sbin/jaspen-ssh-dispatch"`.
   This makes every SSH command except a validated release SHA fail closed.
   Validate the sudoers file with `visudo -cf` before installing it root-owned,
   mode `0440`, in `/etc/sudoers.d`. Remove every older deployment-account sudo
   grant after verifying the new rule is the only remaining grant.
7. Run the wrapper's `--check` as the deployment identity. Perform one approved
   release while watching administrator-only logs. Verify migration finishes
   before restart, the service becomes active, and deployment output contains
   no environment values.
8. After that release succeeds, remove the workflow's compatibility block and
   `ssh-keyscan` fallback in a separate reviewed commit. Then rotate credentials
   with evidence of prior exposure and revoke the previous values.

## Fail-closed verification

- An invalid or non-fast-forward revision is refused before migration.
- A migration failure leaves the currently running service untouched.
- The deployment process cannot read either environment file.
- The deployment SSH key cannot obtain a shell, forward ports/agents, allocate a
  terminal, or invoke any command other than the fixed deployment wrapper.
- The runtime identity cannot read the migration environment.
- The migration identity cannot log in or control services.
- `systemctl show gunicorn-sekki.service -p Environment` exposes no secret
  values because secrets come from the protected `EnvironmentFile`.
