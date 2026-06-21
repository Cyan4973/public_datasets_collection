# chembl_molecule_properties

- Date: 2026-06-20
- Status: blocked (recipe parked in staging/, upstream API bug)
- Candidate dataset: ChEMBL molecule physicochemical properties
- Source:
  - `https://www.ebi.ac.uk/chembl/api/data/molecule.json?only=molecule_chembl_id,molecule_properties&limit=1000`
- Why it looked promising:
  - ~2.9M molecules (total_count confirmed), rich homogeneous numeric families
    (mw_freebase, alogp, psa, qed_weighted, hba, hbd, rtb, aromatic_rings, heavy_atoms)
  - field design verified correct on page 0 (all 9 properties present)
- Failure class:
  - upstream API defect: `only=` field projection + pagination offset
- What happened:
  - Page 0 (offset 0) with `only=molecule_chembl_id,molecule_properties` returns
    1000 molecules with all expected properties.
  - Every subsequent page (offset>0, via page_meta.next) returns HTTP 500
    deterministically (all retries 500). This is a known ChEMBL limitation:
    `only=` does not work with pagination offsets.
  - Without `only=`, full molecule records are too heavy for a >1M single-column
    pull; ChEMBL offers no keyset cursor and no uniform shard filter, so there is
    no clean in-pattern workaround.
- Retry path (future):
  - Use the ChEMBL bulk flat-file / database dump release instead of the REST API,
    or revisit if ChEMBL fixes only=+offset pagination.
  - Recipe preserved at `staging/chembl_molecule_properties/` (field design is correct).
