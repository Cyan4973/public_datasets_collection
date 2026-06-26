# pascal_voc2012_segmentation_masks_u8

- Date: 2026-06-26
- Status: rejected before scripting
- Candidate dataset: PASCAL VOC 2012 segmentation masks
- Source: http://host.robots.ox.ac.uk/pascal/VOC/voc2012/
- Why it looked promising: indexed `uint8` semantic/object segmentation masks, one natural sample per mask, with large spatial regions and boundary structure unlike RGB image pixels.
- Failure class: license_not_permissive_enough_for_repo_policy
- What happened: The technical shape is strong, but the PASCAL VOC distribution is historically research-oriented and not clearly permissive for the repository's accepted-recipes rule.
- Decision: Do not add a recipe unless the license/terms are explicitly approved for this collection.
- Retry conditions: Retry only if the current upstream terms are reviewed and judged compatible with the repository requirement that accepted recipes be public and permissively licensed.
