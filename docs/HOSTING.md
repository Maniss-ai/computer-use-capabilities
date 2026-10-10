# Sharing the demo

The repository and PDF can be shared immediately. The running Python applications need a server runtime: **GitHub Pages is static hosting and cannot run FastAPI or Chromium** ([GitHub documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)).

## GitHub-based option: a private Codespace

[Open the repository in GitHub Codespaces](https://codespaces.new/Maniss-ai/computer-use-capabilities?quickstart=1).

1. Sign in to GitHub and review your Codespaces allowance/billing before creating the environment. Creation and running time belong to the reviewer’s account. No paid instance is provisioned by this repository.
2. Wait for the dev-container setup to finish. It installs the locked Python dependencies and Chromium with its Linux libraries.
3. Run `uv run capabilities web --codespaces` in the Codespaces terminal.
4. In **Ports**, keep **8766** and **8767** set to **Private**. Open port **8766** in the browser. Port **8767** is the separate manual banking sandbox.
5. Follow the no-key replay in [the reviewer guide](REVIEWER_GUIDE.md). The engine still reaches the bank through internal loopback, not through GitHub’s external proxy.
6. Optional discovery: configure your own `GEMINI_API_KEY` as a Codespaces secret or in the ignored `.env`, then restart the command. No maintainer key is included.
7. Stop the command and stop the Codespace when finished; delete it when you no longer need its files. Save any new capabilities/evidence you want to keep first.

The `--codespaces` flag accepts only the current Codespace’s exact generated HTTPS origin. It does not trust arbitrary forwarded headers, permit a wildcard origin, or bind the server to a public interface. GitHub’s private-port authentication is the access boundary. **Do not make the dashboard port public:** this prototype has no application login, and an unauthenticated visitor could control its browser or consume a configured model key’s quota.

The regular `uv run capabilities web` command remains local-only. The standalone headed CLI operator console is intended for a local desktop; use the dashboard preview for human takeover in Codespaces.

Verification status: the Codespaces origin, CSRF, internal-bank routing, and actual replay are covered by local integration tests. The dev-container configuration is prepared; a real GitHub Codespace has not been provisioned or verified in this submission. This is a launch option, not a permanent public deployment.

Official references: [port forwarding and visibility](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace), [Codespaces environment variables](https://docs.github.com/en/codespaces/developing-in-a-codespace/default-environment-variables-for-your-codespace).

## A permanent public URL

For a persistent public demonstration, use a Linux container/VM host capable of running Python and Chromium, with authenticated access in front of the dashboard. It needs HTTPS, one isolated browser worker per operator, persistent artifact storage, explicit origin configuration, and resource limits. The current single-user console should not be exposed anonymously. A hosting provider/account and access model must be selected before this can be deployed.

No always-on public server or GitHub Pages site is currently claimed. The public repo, PDF, and evidence are the shareable deliverables; the default demo runs locally or in the reviewer’s private development environment.
