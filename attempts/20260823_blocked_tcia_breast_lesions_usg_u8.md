# Blocked: TCIA Breast-Lesions-USG Uint8 — 2026-08-23

## Intended material

The attempt targeted native unsigned 8-bit B-mode ultrasound Pixel Data from
the purported TCIA collection `Breast-Lesions-USG`, with `BrEaST` treated as a
possible catalog alias. The intended natural sample was one decoded DICOM
image or cine frame. This would have added clinical B-mode speckle imagery,
distinct from the accepted float32 functional-ultrasound time volume.

## Bounded discovery

The user ran a license-first discovery script against TCIA's official NBIA
REST API. The first direct `getSeries` request for
`Collection=Breast-Lesions-USG&Modality=US` returned an empty response rather
than JSON. The corrected probe then fetched the live `getCollectionValues`
catalog and required an exact match for either `Breast-Lesions-USG` or
`BrEaST` before requesting any series payload.

Neither identifier was present. The only catalog entries matching breast,
ultrasound, or USG terms were breast MRI and digital breast tomosynthesis
collections:

- `ACRIN-Contralateral-Breast-MR`
- `ACRIN-FLT-Breast`
- `Advanced-MRI-Breast-Lesions`
- `BREAST-DIAGNOSIS`
- `Breast-Cancer-Screening-DBT`
- `Breast-MRI-NACT-Pilot`
- `Duke-Breast-Cancer-MRI`
- `QIN Breast DCE-MRI`
- `QIN-BREAST`
- `QIN-BREAST-02`
- `RIDER Breast MRI`

No ultrasound series metadata, DICOM archive, or image payload was downloaded.

## Decision

Block the candidate because the proposed collection is not exposed through
the live official NBIA catalog. The attempt did not establish an official,
bounded acquisition route, so its license metadata, transfer syntax, pixel
width, and natural-sample coverage could not be validated.

Do not retry the same NBIA collection names. Revisit only with an exact
official TCIA/IDC collection identifier and documented API or object-storage
route known to expose the ultrasound DICOM objects, plus collection-specific
rights permitting training use.

Ephemeral evidence:

- `.data/logs/tcia_breast_lesions_usg_u8/discover.latest.log`
- `.data/discovery/tcia_breast_lesions_usg_u8/collections.json`
- `.data/discovery/tcia_breast_lesions_usg_u8/series_metadata.json`
