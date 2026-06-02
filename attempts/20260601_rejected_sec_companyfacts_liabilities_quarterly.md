# SEC Companyfacts Liabilities Quarterly

Status: `rejected`

## Summary

Rejected from the exploratory batch because the selected five-company subset did not consistently expose a usable quarterly `Liabilities` fact across the downloaded companyfacts payloads.

## Dataset Idea

- source family: SEC companyfacts
- source shape: per-company JSON XBRL facts
- intended output: one quarterly `Liabilities` sample per company plus aligned fiscal year and quarter arrays

## What Was Tried

- fixed company subset: `apple`, `microsoft`, `alphabet`, `amazon`, `meta`
- direct SEC companyfacts JSON fetches by CIK
- selected fact: `us-gaap -> Liabilities -> units -> USD`

## Failure

- at least one chosen company, `amazon`, did not expose the expected `Liabilities` fact even though related liability facts were present
- `build.sh` failed with `KeyError: 'Liabilities'`

## Evidence

- build log: `.data/logs/sec_companyfacts_liabilities_quarterly/build.latest.log`

## Reason For Non-Acceptance

- the recipe’s documented company subset was not actually supported by the chosen fact family
- accepting it would require narrowing the company subset and then rerunning the materially changed downloader

## Retry Conditions

- choose a supported company subset for the `Liabilities` fact, or
- redefine the recipe around a different liability fact family with better cross-company coverage
- rerun `download.sh` after the subset or fact selection changes before reconsidering acceptance
