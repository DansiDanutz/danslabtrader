# DansLabTrader

Static dashboard deployed at https://danslabtrader.vercel.app.

## Deployment

Vercel project: `danslabtrader` in `irises-projects-ce549f63`.
Production branch: `main`. Open a pull request for changes; Vercel builds a preview. Merging into `main` deploys production through the GitHub integration.

The initial site files were recovered byte-for-byte from Vercel deployment `dpl_Aqv6fwFejTPfNwZnHe9zDJocKcXJ` on 2026-09-20 and verified against Vercel file SHA-1 hashes. No build or dependency installation is needed.

`data/` and `reports/` contain the deployed data snapshot. Updating those files in Git deploys new data; the Git integration does not itself fetch new trading data.

Preserve the Content Security Policy hashes in `vercel.json` when updating inline scripts or styles.

## Live snapshot mirror

The `live-snapshots` branch tracks completed production deployments every five minutes through a separate local LaunchAgent, `com.danslab.trader-git-sync`. The original trading publisher remains unchanged. Production deployments built from `main` are reported as `already_in_git`; only the independent publisher’s uploaded snapshots need mirroring. This is a one-way mirror from Vercel into Git; use `main` for reviewed site changes.

Only known public dashboard, data, report, and Vercel configuration files are copied. Each source file is checked against Vercel's SHA-1. `.snapshot.json` records the deployment and original hashes. The mirror changes only `git.deploymentEnabled` to `false` in `vercel.json` so snapshot commits do not trigger deployments. There are no credentials or private trading ledgers in this branch.

The job uses the existing local GitHub and Vercel CLI authentication. It runs a pinned copy of `.ops/sync_snapshots.py` installed as `/Users/davidai/Sandbox/grokbot/git-snapshot-sync/sync_snapshots.py`, with that directory passed as `--state`. When updating the sync code, copy the merged script to that installed path. Status is recorded in `status.json` in that directory; failures exit nonzero, preserve the previous branch head, and retry on the next scheduled run. The computer must be awake for scheduled synchronization.

Validation: `python3 -m unittest discover -s tests`.
