# QCArchive OpenFF Gen2 Hessian Dataset Protomers v1.1 (Psi4 B3LYP-D3BJ/DZVP): Native Float64 Molecular Cartesian Hessian Matrices

- Candidate id: `qcarchive_openff_gen2_protomer_hessian_f64`
- Width: float64
- Quantity: Full Cartesian Hessian (second derivative of the total energy, Hartree/Bohr^2) of each optimized drug-like molecule, a (3N x 3N) row-major matrix taken from the record property 'return_hessian'. These are full-precision doubles serialized as shortest-repr JSON floats.
- Source: https://api.qcarchive.molssi.org/api/v1/datasets/403
- Resources: https://api.qcarchive.molssi.org/api/v1/datasets/singlepoint/403/entry_names, https://api.qcarchive.molssi.org/api/v1/datasets/singlepoint/403/records/bulkFetch, https://api.qcarchive.molssi.org/api/v1/records/singlepoint/bulkGet, https://raw.githubusercontent.com/openforcefield/qca-dataset-submission/master/LICENSE
- License: CC-BY-4.0
- License evidence: https://raw.githubusercontent.com/openforcefield/qca-dataset-submission/master/LICENSE
- License quote: Licensing of software and datasets in qca-dataset-submission ... All software in this repository is licensed under BSD-3. All datasets in this repository are licensed under the CC-BY-4.0 license.
- Natural record: One molecule's Hessian matrix (one QCArchive singlepoint record, driver=hessian), with 9N^2 values (38,025 for the 65-atom probe record).
- Estimated samples: 597
- Estimated primary values: 11,000,000
- Estimated download bytes: 1,300,000,000
- Estimated primary bytes: 88,000,000
- Decode path: Stdlib only. Call GET entry_names, then POST datasets/singlepoint/403/records/bulkFetch with specification 'default' to get the record ids. Then POST records/singlepoint/bulkGet {ids:[...<=1000], include:['properties']} in chunks (all done with curl in download.sh). Parse with json and take properties['return_hessian']. Check that its length equals (3*calcinfo_natom)^2, the values are finite, the matrix is symmetric, and status is complete. Pack with struct '<Nd'.
- Novelty kind: new_quantity
- Measurement type: molecular_hessian
- Instrument line: psi4_b3lyp_d3bj_dzvp
- Archive collection: api.qcarchive.molssi.org
- Novelty evidence: novelty.py --url on the QCArchive dataset and terms qcarchive/hessian/psi4/openff give no matches anywhere, and --type molecular_hessian returns 0. Existing chemistry f64 material is rMD17 coordinates/forces (molecular_dynamics_frames), ExoMol energy levels, MACE weights and GEOS-Chem fields. None is a second-derivative force-constant matrix with symmetric block structure.
- Homogeneity: One QCArchive dataset (id 403, 597 records, status {'default': {'complete': 597}}), with a single specification: psi4, b3lyp-d3bj, dzvp, driver hessian. Same unit and generation process throughout. Do not use the much larger dataset 425: it is still computing (93,468 complete and 204,466 waiting), so its scope drifts.
- Risks: (1) Rights. The explicit CC-BY-4.0 grant is in the OpenFF qca-dataset-submission repository LICENSE ('All datasets in this repository'), and the computed results are served from the MolSSI QCArchive API, which shows no license on the record itself. OpenFF's Zenodo releases of sibling QC datasets (e.g. 18436107, 15801401) are also cc-by-4.0. A judge applying the Kubric precedent may want a grant attached to the API data, so the screener should weigh this. (2) Extraction ratio. include=['properties'] returns about 3.8 MB of JSON for 304 KB of kept Hessian, because the Hessian is repeated four times plus dipole gradients, so 597 records means about 1.3 GB transferred. Cap at about 300 records if the byte cap requires it. (3) Live API, not a pinned file: pin the record ids and the per-record modified_on, and reject changes. (4) Symmetric matrices carry about 2x redundancy, which is natural content.
- Probe evidence: GET /api/v1/information gives QCFractal 0.71 with anonymous reads OK. The dataset 403 status endpoint returns {'default': {'complete': 597}}, and entry_names returns 597. bulkFetch mapped entry to record id 138851179. bulkGet with include properties returned 3,828,208 bytes for record 138851179: status complete, natom 65, return_hessian of 38,025 values, 0 f32-exact, 35,599 distinct. Provenance: Psi4 1.9.1, qcengine v0.30.0.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_231914.jsonl`).
