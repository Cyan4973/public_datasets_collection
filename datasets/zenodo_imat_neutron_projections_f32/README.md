# IMAT Neutron Tomography Projections Float32

This recipe decodes the complete white-beam neutron-tomography projection set
from Zenodo record `4273969`, released under CC BY 4.0. The acquisition used a
512-by-512 MCP time-of-flight detector at the IMAT beamline of the ISIS Neutron
and Muon Source and contains 186 golden-ratio angular projections.

Run:

```bash
bash datasets/zenodo_imat_neutron_projections_f32/download.sh
bash datasets/zenodo_imat_neutron_projections_f32/inspect.sh
bash datasets/zenodo_imat_neutron_projections_f32/build.sh
bash datasets/zenodo_imat_neutron_projections_f32/verify.sh
```

Each source TIFF declares one uncompressed IEEE float32 sample per pixel. The
recipe emits one fixed-size, row-major, little-endian float32 sample per
projection. TIFF headers and ZIP framing are excluded; detector values are
copied byte-for-byte without scaling, normalization, or conversion.
