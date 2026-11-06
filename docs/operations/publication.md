# Publication checklist

This candidate contains reusable source and example configuration. It does not
include the original Git history, private overlays, runtime configuration,
backups, kubeconfig or Secret values.

Before publishing:

- Review every file, including bootstrap defaults, incident reports and custom app source.
- Review all URLs, identifiers and example settings for unintended disclosure.
- Run a credential scanner and inspect findings; scanner success is not a security guarantee.
- Initialize a fresh repository here. Do not add the private deployment repository as history.
- Choose the public GitHub repository name and replace `REPLACE_ME` repository URLs.
- Review author identity, licensing/attribution and GitHub visibility before the first push.
- Keep private overlays and actual secrets outside this repository.

Current checks (2026-11-06): public Kustomize entry points render; private overlays
restore the original rendered objects. Gitleaks identified one reviewed false
positive: the `UN_SONARR_0_API_KEY` Secret reference in Unpackerr, not a credential
value. Human review remains required. The assistant has not committed, pushed or
published this directory.

A private deployment repository may still contain historical credentials. Moving
to Secret references does not rotate those credentials. Resolve that separately;
do not publish the old history. Domain redaction reduces casual discovery, but
public DNS and certificates are discoverable and access control remains necessary.
