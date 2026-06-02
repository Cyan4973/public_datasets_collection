# SEC Companyfacts Revenues Quarterly

Status: `rejected`

## Summary

Rejected from the batch because the selected five-company subset did not consistently expose a usable quarterly `Revenues` fact across the downloaded companyfacts payloads.

## Dataset Idea

- source family: SEC companyfacts
- source shape: per-company JSON XBRL facts
- intended output: one quarterly `Revenues` sample per company plus aligned fiscal year and quarter arrays

## What Was Tried

- fixed company subset: `apple`, `microsoft`, `alphabet`, `amazon`, `meta`
- direct SEC companyfacts JSON fetches by CIK
- selected fact: `us-gaap -> Revenues -> units -> USD`

## Failure

- at least one chosen company did not expose the expected `Revenues` fact even though related revenue facts were present
- `build.sh` failed with `KeyError: 'Revenues'`

## Evidence

- build log: `.data/logs/sec_companyfacts_revenues_quarterly/build.latest.log`

## Reason For Non-Acceptance

- the recipe’s documented company subset was not actually supported by the chosen fact family
- accepting it would require narrowing the company subset or redefining the fact selection, both of which are material recipe changes

## Retry Conditions

- choose a supported company subset for the `Revenues` fact, or
- redefine the recipe around a different revenue fact family with better cross-company coverage
- rerun `download.sh` after the subset or fact selection changes before reconsidering acceptance
