# TCIA Lung-PET-CT-Dx PET UInt16

This candidate targets native 16-bit PET voxel volumes from TCIA's live
`Lung-PET-CT-Dx` collection. PET reconstructs positron-annihilation
radiotracer uptake and therefore differs physically and statistically from the
accepted CT attenuation, MRI intensity, and radiotherapy-dose families.

The intended natural sample is one complete ordered PET series from one study,
not individual slices. This should preserve through-plane correlations while
providing variable volume depths and scanner geometries.

Run the metadata-only discovery:

```bash
bash staging/tcia_lung_pet_ct_dx_u16/discover.sh
```

The script downloads no DICOM images. It queries TCIA's NBIA API for `PT`
series, requires a live CC BY 4.0 declaration, inventories the returned
series, and proposes up to twelve bounded series from distinct studies for a
later header preflight.

Results are written under
`.data/discovery/tcia_lung_pet_ct_dx_u16/`. A later acquisition stage must
inspect actual DICOM headers and keep only series that are uncompressed,
single-sample monochrome, native `BitsAllocated=16`, geometrically coherent,
and consistently signed or unsigned. Signed and unsigned PET pixels must not
be mixed in one series.

The live query found 133 distinct Siemens whole-body corrected PET studies,
all explicitly CC BY 4.0. The bounded preflight pins the three smallest series
from distinct studies (136, 145, and 171 slices; 38.1 MB advertised source
bytes):

```bash
bash datasets/tcia_lung_pet_ct_dx_u16/download.sh
bash datasets/tcia_lung_pet_ct_dx_u16/inspect.sh
bash datasets/tcia_lung_pet_ct_dx_u16/build.sh
bash datasets/tcia_lung_pet_ct_dx_u16/verify.sh
```

The downloader retrieves only these three TCIA-generated ZIP archives.
The inspector validates every DICOM object without extracting it to disk and
reports transfer syntax, stored width/signedness, geometry, scaling, slice
ordering, integer distributions, and compression ratios. It emits no training
samples.

The complete preflight found uncompressed Explicit VR Little Endian DICOM with
native unsigned 16-bit pixels in all 452 slices. The accepted target therefore
uses the width-correct `_u16` ID. Each complete ordered PET volume is one
sample; per-slice physical rescale slopes remain index metadata and are not
applied to the stored voxel values.
