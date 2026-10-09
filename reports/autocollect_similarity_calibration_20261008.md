# Autocollect similarity calibration (2026-10-08)

Breadth is now measured on the bytes rather than judged from names. This report records how the rule was calibrated. The tool is `tools/autocollect/zlsim.py`; raw measurements are under `.data/zlsim/` (not committed).

## Definition

A candidate series is redundant when one existing family of the same width is both:

- **compression-equivalent**: the existing family's trained OpenZL compressor compresses the candidate's held-out samples within **3%** of the ratio of the candidate's own trained compressor (the downstream near-duplicate test of `zl_classifier/scripts/group_compressors.py`, which uses 1.2%);
- **statistically close**: the mean per-feature percentile distance is at most **0.05**. Fingerprints use the Transformer's numeric features (`libfeature_extract.so`, `NumericFeaturesV2`) plus order-0, order-1 conditional, delta and byte-lane entropies, made scale-free and taken as the median over samples. Features that barely vary across the corpus are dropped.

A recipe is redundant (`WEAK`) when all its primary series are. Otherwise it is `OK`, or `STRONG` when its nearest family is at least 0.12 away (the 5th percentile of unrelated pairs). Each family's compressor is trained (`zli train --pareto-frontier`) on half the samples and scored on the other half.

## Library

2329 trained families: 8-bit 278, 16-bit 385, 32-bit 954, 64-bit 712. These cover every downstream family (`training_data/numeric_datasets/<N>bit/datasets`), every local baseline primary series, and the autocollect acceptances. 184 hard families exceeded the Pareto time limit and used a single greedy compressor trained on a 4 MB half. The pre-existing downstream grouping files were not usable: they date from 2025-12 and cover only early particle-physics families (11 compressors at 8-bit, 1 at 16-bit).

## Finding 1: compression equivalence alone barely filters

Against a library of 250-930 compressors per width, the best existing compressor matched or beat the candidate's own held-out compressor for most acceptances: the median best loss was 0.0%, ranging from -26% to +22%. A few dozen compressors serve hundreds of families, which is also what the downstream grouping found. Compression equivalence is necessary but not sufficient.

## Finding 2: the fingerprint separates copies of the same material from unrelated material

The calibration anchor was 282 local/downstream mirror pairs, which hold the same material, against 11,755 random pairs of unrelated families:

| Pairs | p01 | p05 | p50 | p75 | p90 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| Same material (mirrors) | | | 0.000 | 0.023 | 0.056 | 0.090 |
| Unrelated (random) | 0.067 | 0.120 | 0.304 | | | |

A threshold of 0.05 means "as close as two copies of the same material". It catches about 85-90% of mirror pairs and well under 1% of unrelated pairs.

## Finding 3: byte-level similarity does not track semantic modality

Nearest statistical neighbours are often from other domains:

- Magellan SAR is nearest to the Parkes radio filterbank, not Cassini SAR.
- The Well's neutron-star-merger density is nearest to rat fUS and ERA5 humidity.
- MODIS FPAR is nearest to AlphaEarth embeddings.
- Scalp EEG float32 is nearest to GPT-2 MLP weights.

Under rank-normalised features, the nearest-neighbour distance was the same (0.063-0.066) for families the semantic audit rated STRONG, OK and WEAK.

## Threshold grid (96 series of the 85 acceptances, 10 nearest neighbours each)

Share flagged redundant:

| T \ X | 1.2% | 3.0% | 5.0% | 10.0% |
|---|---:|---:|---:|---:|
| 0.03 | 4% | 5% | 5% | 5% |
| 0.05 | 10% | 11% | 14% | 18% |
| 0.075 | 32% | 44% | 49% | 54% |
| 0.1 | 51% | 68% | 75% | 78% |
| 0.15 | 66% | 82% | 90% | 94% |

The flagged share grows smoothly with T, so the threshold is a policy choice. It is anchored on the mirror pairs above.

## Re-grade of the 85 acceptances (X = 3%, T = 0.05)

Measured verdicts: 2 STRONG, 75 OK, 8 WEAK (of 85). The semantic audit of 2026-10-06 had 6 / 38 / 41.

| Family | Width | Audit (semantic) | Measured |
|---|---:|---|---|
| `aind_bci_2p_scanimage_trials_i16` | 16 | OK | **OK** |
| `ceda_ukdale_iam_appliance_power_u16` | 16 | OK | **OK** |
| `empiar_10318_microed_diffraction_frames_u16` | 16 | OK | **OK** |
| `empiar_10994_sbfsem_bsed_slices_u16` | 16 | WEAK | **WEAK** |
| `figshare_oscgrid_comtrade_raw_adc_i16` | 16 | OK | **OK** |
| `figshare_rousettus_vocalizations_i16` | 16 | OK | **OK** |
| `mast_jwst_nircam_sw_uncal_ramps_u16` | 16 | OK | **OK** |
| `mpc_aster_l1t_tir_u16` | 16 | OK | **OK** |
| `mpc_goes18_abi_cmi_c13_fulldisk_u16` | 16 | STRONG | **STRONG** |
| `mpc_modis_mod13a1_ndvi_i16` | 16 | OK | **OK** |
| `nasa_heasarc_batse_cont_counts_i16` | 16 | OK | **OK** |
| `nasa_heliocloud_iris_l1_fuv_frames_i16` | 16 | OK | **OK** |
| `ncbi_geo_gpl5423_scanarray_cdna_scan_u16` | 16 | OK | **OK** |
| `ncbi_geo_mm285_methylation_idat_mean_u16` | 16 | OK | **OK** |
| `openneuro_ds003483_vectorview_meg_mag_i16` | 16 | OK | **OK** |
| `physionet_charis_icp_i16` | 16 | OK | **OK** |
| `physionet_circor_pcg_i16` | 16 | OK | **OK** |
| `physionet_grabmyo_semg_i16` | 16 | OK | **OK** |
| `physionet_tpehg_ehg_i16` | 16 | OK | **OK** |
| `tcia_covid19_ny_sbu_chest_cr_u16` | 16 | OK | **OK** |
| `tcia_ldct_siemens_ct_projections_u16` | 16 | OK | **OK** |
| `usgs_grandbay_klein3900_sidescan_xtf_u16` | 16 | OK | **OK** |
| `aalto_arni_room_impulse_response_f32` | 32 | OK | **OK** |
| `ahmedml_cfd_surface_mean_pressure_f32` | 32 | OK | **OK** |
| `aloft_uva_vpts_animal_reflectivity_f32` | 32 | OK | **OK** |
| `cartographer_backpack2d_hokuyo_ranges_f32` | 32 | OK | **OK** |
| `dandi_000020_patchseq_current_clamp_f32` | 32 | OK | **OK** |
| `dandi_001076_zebrafish_calcium_fluorescence_f32` | 32 | OK | **OK** |
| `diode_val_laser_depth_f32` | 32 | OK | **OK** |
| `fingrid_nordic_grid_frequency_10hz_f32` | 32 | OK | **OK** |
| `goose_vls128_lidar_scan_xyz_f32` | 32 | OK | **OK** |
| `gwa_v4_country_wind_speed_100m_f32` | 32 | OK | **OK** |
| `icraf_afsis1_soil_mir_spectra_f32` | 32 | OK | **OK** |
| `luh_lumo_tower_acceleration_f32` | 32 | OK | **OK** |
| `openneuro_ds003097_aomic_cortical_thickness_f32` | 32 | OK | **OK** |
| `openneuro_ds003097_aomic_dti_tensor_f32` | 32 | OK | **OK** |
| `openneuro_ds004212_things_meg_ctf_i32` | 32 | OK | **OK** |
| `openneuro_ds004584_pd_rest_eeg_f32` | 32 | WEAK | **WEAK** |
| `pdebench_2d_cfd_turb_m1_density_f32` | 32 | OK | **OK** |
| `physionet_eit_thorax_images_f32` | 32 | OK | **OK** |
| `rgl_epfl_isotropic_spectral_brdf_f32` | 32 | OK | **OK** |
| `rwth_isea_home_storage_battery_voltage_f32` | 32 | OK | **OK** |
| `tartanair_optical_flow_f32` | 32 | OK | **OK** |
| `the_well_post_neutron_star_merger_density_f32` | 32 | OK | **OK** |
| `zenodo_gridgnosis_pmu_voltage_magnitude_f32` | 32 | OK | **OK** |
| `azure_vm2019_cpu_utilization_readings_f64` | 64 | OK | **OK** |
| `cesnet_ts24_institution_traffic_bytes_u64` | 64 | OK | **OK** |
| `comma2k19_global_pose_ecef_positions_f64` | 64 | OK | **OK** |
| `dandi_ibl_bwm_spike_amplitudes_f64` | 64 | OK | **OK** |
| `exomol_state_energy_levels_f64` | 64 | OK | **OK** |
| `fermi_gbm_tte_nai_photon_arrival_times_f64` | 64 | STRONG | **STRONG** |
| `gfz_gracefo_fgm_acal_bnec_f64` | 64 | OK | **OK** |
| `hamsci_grape1_wwv10_doppler_frequency_f64` | 64 | OK | **OK** |
| `igs_final_satellite_clock_bias_f64` | 64 | OK | **OK** |
| `jpl_gnssro_cosmic1_l1b_excess_phase_f64` | 64 | OK | **OK** |
| `kollmeyer_panasonic18650pf_drive_cycle_voltage_f64` | 64 | OK | **OK** |
| `leap_climsim_lowres_e3sm_mmf_state_fields_f64` | 64 | OK | **OK** |
| `mace_mp_foundation_model_weights_f64` | 64 | OK | **OK** |
| `monado_msd_valve_index_imu_f64` | 64 | OK | **OK** |
| `naif_mro_sc_bus_attitude_ck_f64` | 64 | OK | **OK** |
| `noaa_dcdb_csb_vessel_track_lonlat_f64` | 64 | OK | **OK** |
| `noaa_stofs2d_glo_adcirc_station_water_level_f64` | 64 | OK | **OK** |
| `nrel_resstock2021_state_enduse_load_profiles_f64` | 64 | OK | **OK** |
| `orex_ola_l2_lidar_point_xyz_f64` | 64 | OK | **OK** |
| `wiod2016_world_input_output_tables_f64` | 64 | OK | **OK** |
| `csiro_parkes_uwl_search_mode_u8` | 8 | OK | **OK** |
| `earthbigdata_s1_global_coherence_vv_coh12_u8` | 8 | OK | **OK** |
| `empiar_10511_k2_counting_movie_frames_u8` | 8 | WEAK | **WEAK** |
| `empiar_13192_sbfsem_vessel_slices_u8` | 8 | WEAK | **WEAK** |
| `fmi_radar_ppi_vrad_u8` | 8 | OK | **OK** |
| `mast_iue_swp_raw_image_u8` | 8 | OK | **OK** |
| `mpc_landsat_c2_l1_mss_dn_u8` | 8 | OK | **OK** |
| `mpc_modis_mod10a1_ndsi_snow_cover_u8` | 8 | OK | **OK** |
| `mpc_modis_mod15a2h_fpar_u8` | 8 | OK | **OK** |
| `nasa_pds_cassini_radar_bidr_sigma0_u8` | 8 | WEAK | **WEAK** |
| `nasa_pds_magellan_fmidr_sar_u8` | 8 | WEAK | **WEAK** |
| `nasa_pds_voyager_iss_saturn_raw_u8` | 8 | OK | **OK** |
| `noaa_cdr_seaice_conc_nh_daily_u8` | 8 | OK | **OK** |
| `noaa_rstn_sagamore_hill_srs_spectra_u8` | 8 | OK | **OK** |
| `noaa_wcsd_em302_water_column_i8` | 8 | OK | **OK** |
| `sevir_vil_storm_events_u8` | 8 | OK | **OK** |
| `zenodo_astar_niti_sped_patterns_u8` | 8 | OK | **OK** |
| `zenodo_esrf_mxene_aerogel_microct_slices_u8` | 8 | WEAK | **WEAK** |
| `zenodo_hc18_fetal_head_ultrasound_u8` | 8 | OK | **OK** |
| `zenodo_nordif_ebsd_kikuchi_patterns_u8` | 8 | WEAK | **WEAK** |

Redundant by measurement, with the matching existing family:

- `zenodo_nordif_ebsd_kikuchi_patterns_u8:ebsd_kikuchi_pattern_u8` ~ `local:blender_open_movies_yuv420_u8:video_luma_y_u8` (distance 0.0492, loss +0.000)
- `nasa_pds_magellan_fmidr_sar_u8:magellan_fmidr_sar_backscatter_u8` ~ `local:csiro_parkes_uwl_search_mode_u8:parkes_uwl_search_aa_u8` (distance 0.0256, loss +0.010)
- `empiar_13192_sbfsem_vessel_slices_u8:carotid2_sbfsem_bse_u8` ~ `local:csiro_parkes_uwl_search_mode_u8:parkes_uwl_search_aa_u8` (distance 0.0315, loss -0.074)
- `nasa_pds_cassini_radar_bidr_sigma0_u8:cassini_radar_bidr_sigma0_db_u8` ~ `local:covertype_uci:cov_col_23` (distance 0.0, loss -0.041)
- `zenodo_esrf_mxene_aerogel_microct_slices_u8:mxene_aerogel_microct_slice_u8` ~ `local:empiar_13192_sbfsem_vessel_slices_u8:carotid2_sbfsem_bse_u8` (distance 0.0251, loss +0.003)
- `empiar_10511_k2_counting_movie_frames_u8:k2_counting_frame_u8` ~ `downstream:cms__collection22._0.Tau_genPartFlav` (distance 0.0297, loss +0.000)
- `empiar_10994_sbfsem_bsed_slices_u16:hela_sbfsem_bsed_u16` ~ `downstream:susy_met_mag` (distance 0.0185, loss +0.023)
- `openneuro_ds004584_pd_rest_eeg_f32:ds004584_rest_eeg_63ch_f32` ~ `downstream:gpt2_mlp_proj` (distance 0.0321, loss +0.005)

## Caveats

- The fingerprint uses 1-D sequence statistics. It does not capture 2-D image structure or long-range correlation. The user described it as a proxy and a start.
- Byte-level comparison is per width. The same material at another width is a different byte stream, and source-file reuse is caught by `novelty.py`.
- Whole-value entropies saturate for wide, high-cardinality data on feasible sample sizes. The byte-lane entropies carry the signal there.
- Single-value dominance (fill or no-data) is reported as a warning. `nasa_pds_cassini_radar_bidr_sigma0_u8` matched a one-hot covertype column at distance 0.000, which suggests its samples are mostly fill.

## Addendum (2026-10-08 evening): sampling fix

Fingerprints and the single-value share were computed on the first 256K
values of each sample, and compression splits took file prefixes. For images
or volumes with uniform borders (no-data around a swath, background around an
ultrasound cone, radiograph margins), the prefix is fill, so the fingerprint
described the border. `nasa_pds_cassini_radar_bidr_sigma0_u8` and the TCIA
ultrasound candidate both "matched" a one-hot column at distance 0.000.

Fix: fingerprints and mode share now use four windows centred at 1/8, 3/8,
5/8 and 7/8 of each sample. Compression splits take central chunks. All
library fingerprints were recomputed (`zlsim.py refeature`).

Re-derived anchor: same-material mirror pairs p50 0.000, p75 0.016, p90
0.047, p95 0.079; unrelated pairs p0.5 0.057, p01 0.068, p05 0.121. T = 0.05
catches 91% of mirror pairs and flags 0.37% of unrelated pairs, so the
thresholds stand.

Re-grade of the 101 accepted families: 2 STRONG, 90 OK, 9 WEAK. Six verdicts
changed: Cassini WEAK->OK (but genuinely fill-dominated, mode share 0.917),
NORDIF EBSD WEAK->OK, GOES-18 STRONG->OK, OLA lidar xyz OK->WEAK, LoRaIQ I/Q
OK->WEAK, ambientCG normal maps OK->WEAK. Byte-gate rejections made before the
fix were measured with the flawed sampling and need re-measurement.
