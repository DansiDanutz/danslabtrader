# DansLabTrader

Static dashboard deployed at https://danslabtrader.vercel.app.

## Deployment

Vercel project: `danslabtrader` in `irises-projects-ce549f63`.
Production branch: `main`. Open a pull request for changes; Vercel builds a preview. Merging into `main` deploys production through the GitHub integration.

The initial site files were recovered byte-for-byte from Vercel deployment `dpl_Aqv6fwFejTPfNwZnHe9zDJocKcXJ` on 2026-09-20 and verified against Vercel file SHA-1 hashes. No build or dependency installation is needed.

`data/` and `reports/` contain the deployed data snapshot. Updating those files in Git deploys new data; the Git integration does not itself fetch new trading data.

Preserve the Content Security Policy hashes in `vercel.json` when updating inline scripts or styles.
