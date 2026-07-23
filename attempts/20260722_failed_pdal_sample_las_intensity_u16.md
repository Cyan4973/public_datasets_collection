# Failed: pdal_sample_las_intensity_u16 — Git LFS pointers not real LAS

- Date: 2026-07-23
- Candidate: `staging/pdal_sample_las_intensity_u16`
- Domain: LiDAR intensity uint16

## Attempt

Downloaded `https://github.com/PDAL/data/archive/refs/heads/main.zip` 185 MB.

Build: `no native 16-bit samples accepted`

Inspection:

```
data-main/*.las → 130-133 bytes, Git LFS pointer files, not real LAS
data-main/autzen/*.laz → 133 bytes LFS pointers
```

All LAS/LAZ in archive are LFS pointer text files, not binary LAS.

## Reason

GitHub archive ZIP does not include Git LFS objects. PDAL test data uses LFS for large LAS/LAZ. Without LFS, we get tiny pointer files that parser rejects (size < floor, not valid LAS header).

## Retry

- Use direct raw GitHub LFS URLs via `https://media.githubusercontent.com/media/PDAL/data/main/...` or via Hugging Face LFS, or
- Pin exact small LAS files from alternative host not using LFS, e.g., `https://usgs-lidar-public.s3.amazonaws.com/` with S3 XML parser for .las, or
- Use OpenTopography bulk download with exact tile URLs.

