Status: blocked

Dataset ID: `interpro_protein2ipr`

Summary:
- attempted as a bulk flat-file source in `source_variety_batch_20260609_20z`
- the raw upstream artifact exceeded the repository size cap before completion
- no deterministic, domain-coherent subset rule was defined during this pass

Observed state:
- partial temp download reached roughly `2.8G`
- the source is a monolithic gzip dump, so transport-level truncation would produce an invalid artifact

Why blocked:
- full-source acquisition violates the repository size cap
- arbitrary byte truncation is not acceptable
- a future retry would need a documented subset rule, such as a stable protein partition or another coherent upstream slice

What would unblock it:
- a deterministic subset plan that keeps both raw staged files and generated samples under the `1 GB` limit
