# Production security cutover

These repository artifacts are locally testable preparation. They do not
authorize or claim a live production change. The existing deployment remains
available through a compatibility path until every cutover check below passes.

## Administrator actions

1. Take a fresh DigitalOcean backup or snapshot. Do not continue without a
   restorable copy of the Droplet.
2. In the GitHub `production` Environment, require an administrator approval
   before deployment and restrict deployment branches to `main`. Move the
   existing deployment values into that Environment, then delete their
   repository-level copies. Add `SERVER_SSH_KNOWN_HOSTS` using the Droplet's
   **public** SSH host-key line verified through the DigitalOcean console or
   another trusted channel. Do not obtain the key from the same network
   connection the workflow will trust. Rebuilding the Droplet changes this key:
   update `SERVER_SSH_KNOWN_HOSTS` through the same trusted process; deployments
   fail closed until it is updated.
3. On the Droplet, create non-login `jaspen-app` and `jaspen-migrate` identities
   and a restricted `jaspen-deploy` SSH identity. Do not add any of them to a
   general administrative group.
4. Install `deploy/production/jaspen-deploy`, `jaspen-migrate`,
   `jaspen-env-check`, and `jaspen-ssh-dispatch` as root-owned mode `0755` files
   in `/usr/local/sbin`.
   Install `deploy.conf` as root-owned
   mode `0644` in `/etc/jaspen`, setting the existing checkout's absolute path
   and actual deployment account. The file contains no credentials.
5. Create `/etc/jaspen/runtime.env` as `root:jaspen-app` mode `0640` and
   `/etc/jaspen/migration.env` as `root:jaspen-migrate` mode `0640`. Preserve the
   currently required application variable names without printing values. The
   runtime file references only the runtime database credential. The migration
   file references only the separate migration credential and supplies
   `JASPEN_APP_DB_ROLE`, `JASPEN_APP_DB_HOST`, `JASPEN_APP_DB_PORT`, and
   `JASPEN_APP_DB_NAME` as non-secret target metadata. Database URL credential
   files themselves are mode `0600` and owned by the service identity that reads
   each one.
6. Preserve the existing customer files before changing ownership. Set
   `DEPLOY_ROOT` to the exact absolute value in `/etc/jaspen/deploy.conf`; do not
   use an unresolved variable or glob. Use this fixed order for the four paths:
   `backend/data/user_uploads`, `backend/data/reports`,
   `backend/connectors_data`, and `backend/admin_audit_data` (the audit path is
   relative to the application's `backend` working directory).

   As root, create a root-only temporary state directory. For each numbered
   path, record its pre-change file count and total byte size without printing
   names or contents, and privately record its single existing numeric
   owner/group. Stop if a path is missing or a tree has mixed ownership:

   ```sh
   install -d -m 0700 /root/jaspen-cutover-state
   i=0
   for rel in backend/data/user_uploads backend/data/reports backend/connectors_data backend/admin_audit_data; do
     i=$((i + 1)); path="${DEPLOY_ROOT}/${rel}"; test -d "${path}" || exit 1
     find "${path}" -type f -printf '%s\n' | awk '{n+=1;b+=$1} END {print n+0, b+0}' > "/root/jaspen-cutover-state/${i}.before"
     test "$(find "${path}" -printf '%U:%G\n' | sort -u | wc -l)" -eq 1 || exit 1
     find "${path}" -printf '%U:%G\n' | sort -u > "/root/jaspen-cutover-state/${i}.owner"
     printf '%s ' "${i}"; sed -n '1p' "/root/jaspen-cutover-state/${i}.before"
   done
   ```

   Give `jaspen-app` ownership without moving, copying, renaming, replacing, or
   deleting anything. Grant only traversal on checkout parents that do not
   already permit it, recording each ACL change in the root-only state:

   ```sh
   : > /root/jaspen-cutover-state/parents-acl-added
   for parent in "$(dirname "${DEPLOY_ROOT}")" "${DEPLOY_ROOT}" "${DEPLOY_ROOT}/backend" "${DEPLOY_ROOT}/backend/data"; do
     if ! runuser -u jaspen-app -- test -x "${parent}"; then
       setfacl -m u:jaspen-app:--x "${parent}" || exit 1
       printf '%s\n' "${parent}" >> /root/jaspen-cutover-state/parents-acl-added
     fi
   done
   for rel in backend/data/user_uploads backend/data/reports backend/connectors_data backend/admin_audit_data; do
     chown -R jaspen-app:jaspen-app "${DEPLOY_ROOT}/${rel}" || exit 1
   done
   ```

   Run the post-change checks below. They print only a numeric path index, file
   count, and total byte size; they do not print names or contents:

   ```bash
   i=0
   for rel in backend/data/user_uploads backend/data/reports backend/connectors_data backend/admin_audit_data; do
     i=$((i + 1)); path="${DEPLOY_ROOT}/${rel}"
     find "${path}" -type f -printf '%s\n' | awk '{n+=1;b+=$1} END {print n+0, b+0}' > "/root/jaspen-cutover-state/${i}.after"
     cmp -s "/root/jaspen-cutover-state/${i}.before" "/root/jaspen-cutover-state/${i}.after" || exit 1
     printf '%s ' "${i}"; sed -n '1p' "/root/jaspen-cutover-state/${i}.after"
     current="${path}"
     while :; do
       runuser -u jaspen-app -- test -x "${current}" || exit 1
       test "${current}" = / && break
       current="$(dirname "${current}")"
     done
     runuser -u jaspen-app -- test -r "${path}" || exit 1
     runuser -u jaspen-app -- test -w "${path}" || exit 1
   done
   ```

   Any mismatch or failed permission check stops the cutover. Restore ownership
   using the corresponding recorded numeric owner/group and remove only the ACL
   entries recorded above before investigating.
7. Replace `@DEPLOY_ROOT@` in `gunicorn-sekki-security.conf` with the same exact
   absolute path. Remove all inline secret assignments from the base
   `gunicorn-sekki.service`; the drop-in's empty `Environment=` reset prevents
   inherited inline values. Install `jaspen-migrate.service` and the drop-in in
   `/etc/systemd/system`. Validate both with `systemd-analyze verify`, then run
   `systemctl daemon-reload`. Run `/usr/local/sbin/jaspen-env-check`; proceed
   only when it prints `PASS`. It compares secret names and protected-file
   values in memory and never reports values, fragments, or hashes.
8. Restrict the GitHub deployment public key in the deployment identity's
   `authorized_keys` with `restrict,command="/usr/local/sbin/jaspen-ssh-dispatch"`.
   This makes every SSH command except a validated release SHA fail closed.
   Validate the sudoers file with `visudo -cf` before installing it root-owned,
   mode `0440`, in `/etc/sudoers.d`. Remove every older deployment-account sudo
   grant after verifying the new rule is the only remaining grant.
9. Run the wrapper's `--check` as the deployment identity. Perform one approved
   release while watching administrator-only logs. Verify migration finishes
   before restart, the service becomes active, and deployment output contains
   no environment values.
10. After that release succeeds, remove the workflow's compatibility block and
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

## Rollback

Stop at the first failed cutover check. Use the snapshot if file counts or byte
totals differ. Otherwise, reverse only the stages already applied:

1. Restore the saved ownership and only the ACL entries added during cutover,
   then repeat the non-disclosing count/size checks:

   ```bash
   i=0
   for rel in backend/data/user_uploads backend/data/reports backend/connectors_data backend/admin_audit_data; do
     i=$((i + 1)); owner="$(sed -n '1p' "/root/jaspen-cutover-state/${i}.owner")"
     [[ "${owner}" =~ ^[0-9]+:[0-9]+$ ]] || exit 1
     chown -R "${owner}" "${DEPLOY_ROOT}/${rel}" || exit 1
   done
   while IFS= read -r parent; do
     test -n "${parent}" && setfacl -x u:jaspen-app "${parent}"
   done < /root/jaspen-cutover-state/parents-acl-added
   ```
2. Remove `/etc/systemd/system/gunicorn-sekki.service.d/10-security.conf`, run
   `systemctl daemon-reload`, and restart `gunicorn-sekki.service`.
3. Restore the exact previous deployment-key line in the deployment identity's
   `authorized_keys` from the administrator's backup.
4. Remove `/etc/sudoers.d/jaspen-deploy`, restore the previous sudo grant from
   the administrator's backup, and validate it with `visudo -cf` before use.
5. Run `systemctl disable --now jaspen-migrate.service`.

The workflow compatibility path resumes automatically when `jaspen-deploy
--check` fails, but it can connect only while the deployment key is
unrestricted. Once the forced-command key restriction is installed, rollback
must restore the previous `authorized_keys` entry before relying on that path.
