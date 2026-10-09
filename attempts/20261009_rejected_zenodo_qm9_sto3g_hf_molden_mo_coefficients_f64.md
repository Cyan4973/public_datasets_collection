# zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64

- Date: 2026-10-09
- Status: rejected
- Candidate dataset: QM9@STO-3G Hartree-Fock Molecular-Orbital Coefficient Matrices (PySCF Molden Files, King/Grzenda/Zhu 2025) Float64
- Source: https://zenodo.org/records/16934625
- Why it looked promising: see `pipeline/cards/zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: qm9_sto3g_rhf_mo_coefficients_f64 ~ local:mace_mp_foundation_model_weights_f64:mace_radial_mlp_weight_f64 (distance 0.0463, loss +0.004)
- Evidence:
  - 2026-10-09T10:10:18 proposed: {"log": ".data/pipeline/logs/scout_64bit/scout.20261009_095410.jsonl"}
  - 2026-10-09T10:13:23 screened: {"decision": "approve", "reason": "New quantity: dense MO coefficient matrices. No recipe, registry or downstream match, and no orbital/wavefunction family exists. The Zenodo API confirms cc-by-4.0 on record 16934625 (King et al.). The qm9_hfmoldens.zip range GET returned 206. Values are PySCF doubl
  - 2026-10-09T10:35:42 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64/builder.20261009_101730.jsonl", "cost": 1.7407819999999998}
  - 2026-10-09T10:49:59 download: {"rc": 0, "reason": "", "bytes": 225144392, "log": ".data/pipeline/logs/zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64/download.20261009_103558.log"}
  - 2026-10-09T10:57:26 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64/builder.20261009_105523.jsonl", "cost": 0.2680982}
  - 2026-10-09T11:11:12 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64/`, `.data/logs/zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
