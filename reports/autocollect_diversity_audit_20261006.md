# Diversity audit of the 85 autocollect families accepted 2026-10-05/06

Independent, adversarial review. Ground truth: `pipeline/baseline.json` (326 recipes before the run; the brief said 329), `pipeline/candidates.tsv` (85 rows `accepted`), each family's `datasets/<id>/manifest.toml` and development report, and the downstream family lists from `tools/autocollect/novelty.py --list-width`. `.data/` was not used. Repository untouched; this file and `/tmp/autocollect/diversity_audit_work/` are the only outputs.

## Verdict scale

- **STRONG**: measurement type absent from baseline and downstream at every width before the run.
- **OK**: the broad domain exists, but the family brings a new generation process or clearly different statistics.
- **WEAK**: same instrument line, product family, archive pipeline or measurement type as a baseline family or one accepted earlier in the run; it differs only in content, region, date, width or a sibling quantity ("new content in a known modality"). `WEAK*` marks the most overlapping cases (a near-twin accepted minutes to hours earlier).
- **REDUNDANT**: byte-level near-duplicate (same source material or trivially different slice).

## Headline

- Overall: **STRONG 6, OK 38, WEAK 41, REDUNDANT 0** of 85. About half the night's output (41/85) is new content in a known modality. Nothing is a byte-level duplicate: the problem is clustering, not copying.
- The judge labelled **23 families `new_modality`**. Only 6 survive as STRONG, so `new_modality` was inflated about 3.8x.
- The judge never used the bottom two rungs of the criteria ladder ("new content in a known modality", "width/representation only"). The ledger vocabulary has `new_content_same_modality` (one *proposed* row uses it), but 0 of 85 accepted rows carry it. 40 families labelled new_source/new_quantity are WEAK here.
- criteria.md names two breadth anti-patterns: "raw camera frames from different space missions" and "SAR backscatter mosaics of different bodies". The run accepted both (IUE + Voyager raw vidicon frames; Cassini + Magellan SAR dB mosaics, 57 minutes apart), plus JWST and IRIS raw frames at 16-bit.
- Only 9 of 85 development reports mention breadth at all. Where they do, the note is acknowledged and then overridden (MODIS snow: "the fourth 8-bit '0-100 plus in-band flags' EO raster ... That lowers its priority. It is accepted because ...").
- Archive concentration: 6 Planetary Computer rasters (3 from the same `modis-061-cogs` container), 5 OpenNeuro, 5 PhysioNet, 4 EMPIAR, 3 DANDI, 3 NASA PDS asc-pds. Neuro, physiology and medical work makes up 17 of the 85 (C09-C12, the four medical families in C13, and the CirCor PCG); at 32-bit the first 7 acceptances were all neuro/medical.

## Per-width summary

| Width | Accepted | STRONG | OK | WEAK | REDUNDANT | WEAK share | Most saturated clusters (baseline + new at this width) |
|---|---|---|---|---|---|---|---|
| 8 | 20 | 1 | 7 | 12 | 0 | 60% | Satellite EO rasters C01 (7 base + 4 new); the 8-bit '0-100 + flag' percent-raster pile is now 5 (JRC base; S1 coherence, sea-ice CDR, MODIS FPAR, MODIS snow new); SAR C02 (3 new, all within 1 h); weather radar C03 (1 + 2); underwater acoustics C21 (2 + 1). Remote-sensing/space imagery (C01-C04) = 11 of the 20 new 8-bit families. |
| 16 | 22 | 1 | 9 | 12 | 0 | 55% | PhysioNet-style WFDB int16 waveforms (4 base + 4 new, from one archive and format); PCM16 audio C20 (6 base + 2 new); raw space frames C04 (2 base + 2 new); satellite rasters C01 (3 base + 3 new, all from Planetary Computer). |
| 32 | 23 | 2 | 11 | 10 | 0 | 43% | Neuro/medical (C09/C11/C12/C13): the first 7 32-bit acceptances, 7 of 23 overall; laser ranging C18 (3 new within 90 min); simulation fluid fields C22 (1 base + 3 new); power grid C14 (2 new). |
| 64 | 20 | 2 | 11 | 7 | 0 | 35% | GNSS/geodesy/space C16 (3 base + 5 new); trajectories/point geometry C17+C18 (3 new); simulation fields C22 (3 base + 2 new). 64-bit is the most genuinely diverse width. |
| **all** | **85** | **6** | **38** | **41** | **0** | **48%** | |

## Cluster map

Clusters were defined from the 85 new families and then populated with baseline (`base`) members. The "new" column gives width:verdict. Downstream families add little beyond mirrors of the baseline (exceptions: HEP tabular cms/h1/LHCb, clickbench/gharchive/loghub, extra model weights, quickdraw/MNIST).

| Cluster | New families (width:verdict) | Baseline members (widths) | Downstream equivalents | New per width (8/16/32/64) |
|---|---|---|---|---|
| **C01** Satellite EO rasters (optical/thermal radiance, land & cryosphere products, gridded geo rasters) | `noaa_cdr_seaice_conc_nh_daily_u8` (8:WEAK)<br>`mpc_modis_mod15a2h_fpar_u8` (8:WEAK*)<br>`mpc_modis_mod10a1_ndsi_snow_cover_u8` (8:WEAK)<br>`mpc_landsat_c2_l1_mss_dn_u8` (8:WEAK)<br>`mpc_goes18_abi_cmi_c13_fulldisk_u16` (16:OK)<br>`mpc_modis_mod13a1_ndvi_i16` (16:WEAK)<br>`mpc_aster_l1t_tir_u16` (16:WEAK)<br>`gwa_v4_country_wind_speed_100m_f32` (32:WEAK) | `sentinel2_l2a_reflectance_cogs_u16` (16)<br>`sentinel2_l2a_scene_classification_u8` (8)<br>`esa_worldcover_landcover_tiles_u8` (8)<br>`jrc_global_surface_water_occurrence_u8` (8)<br>`modis_active_fire_mask_u8` (8)<br>`noaa_ims_snow_ice_cover_u8` (8)<br>`statlog_landsat_satellite_u8` (8)<br>`google_alphaearth_satellite_embeddings_i8` (8)<br>`isric_soilgrids_clay_i16` (16)<br>`skadi_srtm_hgt` (16)<br>`usgs_shakemap_ground_motion_f32` (32)<br>`worldclim_tavg_10m` (?) | mirrors of S2 L2A/SCL, WorldCover, JRC, MODIS fire, IMS, statlog, SRTM, SoilGrids, ShakeMap | 4/3/1/0 |
| **C02** SAR / radar imaging (spaceborne, planetary, ground-penetrating) | `nasa_pds_cassini_radar_bidr_sigma0_u8` (8:OK)<br>`earthbigdata_s1_global_coherence_vv_coh12_u8` (8:OK)<br>`nasa_pds_magellan_fmidr_sar_u8` (8:WEAK) | `sentinel1_grd_measurement_u16` (16)<br>`nasa_pds_sharad_radargram_f32` (32)<br>`zenodo_gpr_rd3_i16` (16) | sentinel1_grd_hh_dn_u16, sharad_radargram_f32, svalbard_gpr_radargram_i16 | 3/0/0/0 |
| **C03** Weather radar products | `sevir_vil_storm_events_u8` (8:WEAK)<br>`fmi_radar_ppi_vrad_u8` (8:OK)<br>`aloft_uva_vpts_animal_reflectivity_f32` (32:OK) | `noaa_nexrad_level3_nids_radials_u8` (8)<br>`dwd_radolan_rw_precip_i16` (16) | noaa_nexrad_level3_radials_u8, dwd_radolan_rw_precip_words_u16 | 2/0/1/0 |
| **C04** Raw space-instrument detector frames (planetary/astronomy cameras, spectrographs) | `mast_iue_swp_raw_image_u8` (8:OK)<br>`nasa_pds_voyager_iss_saturn_raw_u8` (8:WEAK)<br>`mast_jwst_nircam_sw_uncal_ramps_u16` (16:OK)<br>`nasa_heliocloud_iris_l1_fuv_frames_i16` (16:WEAK) | `nasa_pds_mastcamz_raw_i16` (16)<br>`nasa_pds_cassini_vims_qube_i16` (16)<br>`nasa_sdo_aia_synoptic_i32` (32)<br>`nasa_fits_sample_image_planes` (32/64)<br>`nasa_pds_themis_ir_mosaic_u8` (8) | cassini_vims_core_i16, fits_scaled_image_pixels_f64, nasa_pds_themis_ir_mosaic_u8 | 2/2/0/0 |
| **C05** High-energy astrophysics photon / count data | `nasa_heasarc_batse_cont_counts_i16` (16:OK)<br>`fermi_gbm_tte_nai_photon_arrival_times_f64` (64:OK) | `nasa_heasarc_nicer_pi_i16` (16)<br>`nasa_heasarc_nicer_detector_u8` (8)<br>`magic_gamma_telescope_event_features_f64` (64) | nicer_xray_pi_channel_i16, nicer_detector_id_u8, nicer_rawx/rawy_u8 | 0/1/0/1 |
| **C06** Radio astronomy / radio dynamic spectra | `csiro_parkes_uwl_search_mode_u8` (8:STRONG)<br>`noaa_rstn_sagamore_hill_srs_spectra_u8` (8:WEAK) | `zenodo_crab_giant_pulse_sigmf_ci16` (16)<br>`eht_public_uvfits_visibilities_f32` (32) | crab_giant_pulse_iq_ci16, eht_visibility_*_f32 | 2/0/0/0 |
| **C07** Electron microscopy imaging (TEM/SEM/cryo-EM) | `empiar_13192_sbfsem_vessel_slices_u8` (8:OK)<br>`empiar_10511_k2_counting_movie_frames_u8` (8:OK)<br>`empiar_10994_sbfsem_bsed_slices_u16` (16:WEAK*) | `zenodo_tem_tilt_series_i16` (16)<br>`zenodo_vacv_core_segmentation_mrc_u16` (16) | sarscov2_tem_projection_i16, vacv_core_segmentation_volume_u16 | 2/1/0/0 |
| **C08** Diffraction-pattern detector frames (electron/X-ray diffraction) | `zenodo_nordif_ebsd_kikuchi_patterns_u8` (8:WEAK)<br>`zenodo_astar_niti_sped_patterns_u8` (8:WEAK)<br>`empiar_10318_microed_diffraction_frames_u16` (16:OK) | `zenodo_silicon_diffraction_tiff_u16` (16)<br>`zenodo_powder_xrd_patterns_f32` (32)<br>`wwpdb_structure_factors_f32` (32) | silicon_ebsd_detector_u16, zeolite_powder_xrd_intensity_f32, wwpdb_measured_structure_factor_* | 2/1/0/0 |
| **C09** Neural electrophysiology (EEG, MEG, intracellular, spike sorting) | `openneuro_ds003483_vectorview_meg_mag_i16` (16:WEAK)<br>`openneuro_ds004212_things_meg_ctf_i32` (32:OK)<br>`openneuro_ds004584_pd_rest_eeg_f32` (32:WEAK)<br>`dandi_000020_patchseq_current_clamp_f32` (32:OK)<br>`dandi_ibl_bwm_spike_amplitudes_f64` (64:WEAK) | `eeg_physionet` (16)<br>`chbmit_physionet` (16)<br>`zenodo_open_ephys_continuous_i16` (16)<br>`zenodo_npx_opto_templates_f32` (32) | eeg_c3/c4/cz, chbmit_*, mouse_extracellular_voltage_i16, npx_opto_kilosort_templates_f32 | 0/1/3/1 |
| **C10** Clinical physiological waveforms (PhysioNet-style biopotential / pressure) | `physionet_tpehg_ehg_i16` (16:WEAK)<br>`physionet_grabmyo_semg_i16` (16:WEAK)<br>`physionet_charis_icp_i16` (16:WEAK) | `mitbih_arrhythmia_physionet` (16)<br>`mitbih_arrhythmia_u8` (8)<br>`ptbxl_physionet` (32)<br>`physionet_bidmc_ppg_resp_i16` (16)<br>`uci_emg_gestures_i8` (8) | mitbih_*, bidmc_pleth/respiration_adc_i16, ptbxl_ecg_lr_12x1000_f32, semg_channel_i8 (registry) | 0/3/0/0 |
| **C11** Optical neurophysiology (two-photon calcium imaging) | `aind_bci_2p_scanimage_trials_i16` (16:OK)<br>`dandi_001076_zebrafish_calcium_fluorescence_f32` (32:OK) | none | none (nearest: BBBC fluorescence microscopy stills bbbc007/021/039) | 0/1/1/0 |
| **C12** Brain MRI and MRI derivatives | `openneuro_ds003097_aomic_cortical_thickness_f32` (32:OK)<br>`openneuro_ds003097_aomic_dti_tensor_f32` (32:WEAK) | `openneuro_ds000030_t1w_mri_f32` (32)<br>`openneuro_ds000030_fmri_bold_i16` (16)<br>`msd_hippocampus_segmentation_labels_u8` (8) | openneuro_t1w_mri_f32, openneuro_fmri_bold_i16, msd_hippocampus_labels_u8 | 0/0/2/0 |
| **C13** Medical & materials X-ray/CT/ultrasound/impedance imaging | `zenodo_hc18_fetal_head_ultrasound_u8` (8:OK)<br>`zenodo_esrf_mxene_aerogel_microct_slices_u8` (8:WEAK)<br>`tcia_covid19_ny_sbu_chest_cr_u16` (16:WEAK)<br>`tcia_ldct_siemens_ct_projections_u16` (16:OK)<br>`physionet_eit_thorax_images_f32` (32:STRONG) | `tcia_nsclc_radiomics_ct_i16` (16)<br>`tcia_cmmd_mammography_u16` (16)<br>`tcia_lung_pet_ct_dx_u16` (16)<br>`tcia_gamma_plan_rtdose_u16` (16)<br>`tcia_eclipse_rtdose_u32` (32)<br>`zenodo_lodopab_ct_sinograms_f32` (32)<br>`zenodo_imat_neutron_projections_f32` (32)<br>`zenodo_rat_fus_image_sequence_f32` (32)<br>`medmnist_pathmnist_images_u8` (8) | tcia_ct_slice_pixels_i16, cmmd_mammography_pixel_u16, whole_body_pet_activity_u16, lodopab..., imat..., rat_fus... | 2/2/1/0 |
| **C14** Power-grid & building electrical measurements | `figshare_oscgrid_comtrade_raw_adc_i16` (16:OK)<br>`ceda_ukdale_iam_appliance_power_u16` (16:WEAK)<br>`fingrid_nordic_grid_frequency_10hz_f32` (32:OK)<br>`zenodo_gridgnosis_pmu_voltage_magnitude_f32` (32:OK)<br>`nrel_resstock2021_state_enduse_load_profiles_f64` (64:OK) | `household_power_uci` (64/8)<br>`appliances_energy_uci` (64)<br>`electricity_load_diagrams_uci` (32)<br>`pglib_opf_matpower_cases_numeric` (64) | power_global_*/power_voltage, appl_*, elec_mt, pglib_opf_* | 0/2/2/1 |
| **C15** Battery cell / pack measurements | `rwth_isea_home_storage_battery_voltage_f32` (32:WEAK)<br>`kollmeyer_panasonic18650pf_drive_cycle_voltage_f64` (64:OK) | `zenodo_battery_eis_complex_f32` (32) | battery_eis_complex_history_f32 | 0/0/1/1 |
| **C16** GNSS, geodesy & space-physics time series (clocks, phase, attitude, magnetometer, ionosphere) | `naif_mro_sc_bus_attitude_ck_f64` (64:OK)<br>`gfz_gracefo_fgm_acal_bnec_f64` (64:OK)<br>`igs_final_satellite_clock_bias_f64` (64:OK)<br>`jpl_gnssro_cosmic1_l1b_excess_phase_f64` (64:WEAK)<br>`hamsci_grape1_wwv10_doppler_frequency_f64` (64:OK) | `noaa_cors_rinex_observations_f64` (64)<br>`usgs_geomag_observatory_minute_f32` (32)<br>`nasa_naif_de440s_spk_coefficients_f64` (64)<br>`nasa_pds_gravity_harmonics_f64` (64) | noaa_cors_carrier_phase/pseudorange/signal_strength_f64, usgs_geomag_xyz_minute_f32, nasa_de440s_spk_coeff_f64 | 0/0/0/5 |
| **C17** Trajectories & geodetic positions | `comma2k19_global_pose_ecef_positions_f64` (64:WEAK)<br>`noaa_dcdb_csb_vessel_track_lonlat_f64` (64:WEAK) | `tum_rgbd_groundtruth_pose_f64` (64)<br>`citibike_2024_trip_geocoords_f64` (64)<br>`noaa_marinecadastre_ais_2024_01_01_f32` (32)<br>`opensky_states` (32)<br>`gbif_occurrence_2024_coordinate_sample` (32/64)<br>`natural_earth_10m_geometry_xy_f64` (64)<br>`hsl_gtfs_static_schedule_numeric` (32/64) | tum_rgbd_pose_f64, citibike_*_f64, gtfs_shapes_lat_lon_f64, noaa_ais_f32, gbif_coords_f64 | 0/0/0/2 |
| **C18** LiDAR, laser ranging & depth | `goose_vls128_lidar_scan_xyz_f32` (32:OK)<br>`cartographer_backpack2d_hokuyo_ranges_f32` (32:WEAK)<br>`diode_val_laser_depth_f32` (32:WEAK)<br>`orex_ola_l2_lidar_point_xyz_f64` (64:WEAK) | `dc_lidar_2015_classification_u8` (8)<br>`dc_lidar_2015_intensity_u16` (16)<br>`dc_lidar_2015_gps_time_f64` (64)<br>`tum_rgbd_depth_u16` (16)<br>`nasa_pds_mola_megdr_i16` (16) | dc_lidar_*, tum_rgbd_depth_u16, mola_megdr_topography_i16 | 0/0/3/1 |
| **C19** Inertial & vibration sensors (IMU, accelerometers, DAS) | `luh_lumo_tower_acceleration_f32` (32:WEAK)<br>`monado_msd_valve_index_imu_f64` (64:WEAK) | `har_smartphone_uci` (?)<br>`zenodo_accelerometer_pcm16` (16)<br>`zenodo_spica_urban_das_f32` (32)<br>`seismic_waveform_i32` (?)<br>`zenodo_xsens_cymbal_landmarks_i16` (16)<br>`uci_hydraulic_system_cycles_f32` (32) | har_body_acc/body_gyro/total_acc (at 16/32/64), honeybee_accelerometer_pcm16, urban_das_channel_day_f32 | 0/0/1/1 |
| **C20** Airborne acoustics (PCM audio, bioacoustics, room impulse responses) | `physionet_circor_pcg_i16` (16:WEAK)<br>`figshare_rousettus_vocalizations_i16` (16:WEAK)<br>`aalto_arni_room_impulse_response_f32` (32:WEAK) | `esc50_environmental_audio_i16` (16)<br>`librispeech_dev_clean_i16` (16)<br>`nsynth_test_notes_i16` (16)<br>`fsdd_pcm_u8` (8)<br>`fsdd_spoken_digits` (?)<br>`asterisk_core_sounds_ulaw_u8` (8)<br>`openslr_rirs_noises_pcm16` (16) | librispeech_dev_clean_pcm16, esc50..., nsynth_test_note_pcm16, measured_room_impulse_response_i16, fsdd_* | 0/2/1/0 |
| **C21** Underwater acoustics / sonar | `noaa_wcsd_em302_water_column_i8` (8:WEAK)<br>`usgs_grandbay_klein3900_sidescan_xtf_u16` (16:OK) | `zenodo_polarfront_ek60_power_i16` (16)<br>`zenodo_polarfront_ek60_angles_i8` (8)<br>`zenodo_adcp_pd0_i16` (16)<br>`zenodo_adcp_pd0_backscatter_quality_u8` (8)<br>`zenodo_leconte_chirp_segy_f32` (32) | ek60_ping_channel_*, adcp_*, leconte_chirp_trace_f32 | 1/1/0/0 |
| **C22** Simulation / model physical fields (CFD, PDE, GRMHD, climate, ocean, FE) | `ahmedml_cfd_surface_mean_pressure_f32` (32:OK)<br>`pdebench_2d_cfd_turb_m1_density_f32` (32:WEAK)<br>`the_well_post_neutron_star_merger_density_f32` (32:WEAK*)<br>`noaa_stofs2d_glo_adcirc_station_water_level_f64` (64:OK)<br>`leap_climsim_lowres_e3sm_mmf_state_fields_f64` (64:WEAK) | `weatherbench2_era5_pressure_level_fields_f32` (32)<br>`zenodo_gia_stress_fields_f64` (64)<br>`zenodo_calochallenge_showers_f64` (64)<br>`figshare_rmd17_trajectories_f64` (64) | era5_*_pressure_levels_f32, gia_stress_component_f64, figshare_rmd17_*_f64 | 0/0/3/2 |
| **C23** Genomics instrument data (microarray, sequencing signals) | `ncbi_geo_mm285_methylation_idat_mean_u16` (16:STRONG)<br>`ncbi_geo_gpl5423_scanarray_cdna_scan_u16` (16:OK) | `encode_methylation_pct_u8` (8)<br>`bam_read_mapq_u8` (8)<br>`ena_fastq_quality_phred` (8)<br>`zenodo_nanopore_slow5_i16` (16)<br>`zenodo_sanger_abif_i16` (16) | encode_methylation_pct_u8, fastq_phred_u8/u16, nanopore_raw_signal_i16, sanger_processed_dye_trace_i16 | 0/2/0/0 |
| **C24** Spectroscopy & reflectance measurements | `icraf_afsis1_soil_mir_spectra_f32` (32:OK)<br>`rgl_epfl_isotropic_spectral_brdf_f32` (32:STRONG)<br>`exomol_state_energy_levels_f64` (64:OK) | `zenodo_marine_dom_positive_ms1_f32` (32)<br>`zenodo_venere_nir_hsi_u16` (16) | zenodo_marine_dom_mz/intensity_f32, venere_nir_hsi_detector_u16 | 0/0/2/1 |
| **C25** Dense 2-D vector fields (optical flow / PIV) | `tartanair_optical_flow_f32` (32:OK) | `zenodo_morphodunes_piv_f64` (64) | morphodunes_piv_uv_f64 | 0/0/1/0 |
| **C26** Neural-network weights | `mace_mp_foundation_model_weights_f64` (64:OK) | `hf_smolllm2_135m_safetensors_f16` (16)<br>`hf_timm_resnet18_conv_f32` (32)<br>`deepmind_gencast_checkpoint_f32` (32)<br>`smollm2_135m_q8_gguf_weights` (8) | smollm*, gpt2_*, dino_*, llama_q8_*, gencast_*, resnet18_convolution_kernel_f32, nn_weight_f64 (widened f32) | 0/0/0/1 |
| **C27** IT / network telemetry & economic tables | `wiod2016_world_input_output_tables_f64` (64:STRONG)<br>`azure_vm2019_cpu_utilization_readings_f64` (64:STRONG)<br>`cesnet_ts24_institution_traffic_bytes_u64` (64:OK) | `zenodo_zeroswarm_modbus_registers_u16` (16)<br>`zenodo_zeroswarm_tcp_sequence_u32` (32)<br>`ooni_measurements` (32)<br>`wikimedia_pageviews_daily` (32)<br>`nist_matrix_market_sparse_matrices` (32/64)<br>`sec_fsd_2015q1_2024q4_numeric_values_i64` (64) | clickbench_*, gharchive_*, loghub_*, wikimedia_pageviews_daily_u32, sec_fsd_* | 0/0/0/3 |

### Clusters ranked by new families added (saturation)

| Cluster | New | WEAK among new | Baseline | Comment |
|---|---|---|---|---|
| C01 Satellite EO rasters | 8 | 7 | 12 | 6 MPC rasters + sea-ice CDR + GWA; MODIS trio from one container; 8-bit percent+flag raster pile |
| C09 Neural electrophysiology | 5 | 3 | 4 | 2 MEG, float EEG, intracellular, spike amplitudes; only intracellular adds a new regime |
| C13 Medical & materials X-ray/CT/ultrasound/impedance imaging | 5 | 2 | 9 | EIT is STRONG; micro-CT and chest CR are content variants |
| C14 Power-grid & building electrical measurements | 5 | 1 | 4 | 5 grid/building series; PMU, frequency, point-on-wave genuinely new |
| C16 GNSS, geodesy & space-physics time series | 5 | 1 | 4 | 5 GNSS/space series at 64-bit; mostly distinct quantities |
| C22 Simulation / model physical fields | 5 | 3 | 4 | 3 fluid fields at 32-bit in 1 h; ClimSim is ERA5-like at 64-bit |
| C04 Raw space-instrument detector frames | 4 | 2 | 5 | criteria.md's named anti-pattern (raw camera frames from different missions) |
| C18 LiDAR, laser ranging & depth | 4 | 3 | 5 | 4 laser/range families; 3 at 32-bit within 90 min |
| C02 SAR / radar imaging | 3 | 1 | 3 | criteria.md's named anti-pattern (SAR mosaics of different bodies) |
| C03 Weather radar products | 3 | 1 | 2 | 3 new + 2 baseline; VRAD and VPTS add real statistics, SEVIR does not |
| C07 Electron microscopy imaging | 3 | 1 | 2 | 4 EMPIAR families counting C08's MicroED; SBF-SEM twice in 40 min |
| C08 Diffraction-pattern detector frames | 3 | 2 | 3 | EBSD duplicates baseline type; SPED duplicates MicroED's spot-pattern class |
| C10 Clinical physiological waveforms | 3 | 3 | 5 | PhysioNet WFDB int16 cluster now 8 families at 16-bit |
| C20 Airborne acoustics | 3 | 3 | 7 | PCM16 audio was already the most saturated 16-bit modality |
| C24 Spectroscopy & reflectance measurements | 3 | 0 | 2 |  |
| C27 IT / network telemetry & economic tables | 3 | 0 | 6 |  |
| C05 High-energy astrophysics photon / count data | 2 | 0 | 3 |  |
| C06 Radio astronomy / radio dynamic spectra | 2 | 1 | 2 |  |
| C11 Optical neurophysiology | 2 | 0 | 0 |  |
| C12 Brain MRI and MRI derivatives | 2 | 1 | 3 |  |
| C15 Battery cell / pack measurements | 2 | 1 | 1 |  |
| C17 Trajectories & geodetic positions | 2 | 2 | 7 |  |
| C19 Inertial & vibration sensors | 2 | 2 | 6 |  |
| C21 Underwater acoustics / sonar | 2 | 1 | 5 |  |
| C23 Genomics instrument data | 2 | 0 | 5 |  |
| C25 Dense 2-D vector fields | 1 | 0 | 1 |  |
| C26 Neural-network weights | 1 | 0 | 4 |  |

## Per-family verdicts

Ordered by width, then by acceptance time (`#` = acceptance order in the run). `judge` = the pipeline's `novelty_kind`; **disagree** marks rows where the verdict is below the judge's rung (new_modality rated below STRONG, or any judge label rated WEAK).

### 8-bit

| # | Family | Cluster | Judge | Verdict | Nearest existing | Justification |
|---|---|---|---|---|---|---|
| 3 | `mast_iue_swp_raw_image_u8` | C04 | new_source | **OK** | nasa_pds_mastcamz_raw_i16 (base) | First 8-bit raw space-detector frame (SEC-vidicon UV spectrograph, reseaux, cosmic rays); raw space-camera frames already exist at 16-bit. |
| 4 | `csiro_parkes_uwl_search_mode_u8` | C06 | new_modality | **STRONG** | zenodo_crab_giant_pulse_sigmf_ci16 (base) | First detected-power radio filterbank (4096 x 3328-channel 8-bit dynamic spectra, 4 coherency products); baseline radio data are complex IQ/visibilities. |
| 5 | `nasa_pds_cassini_radar_bidr_sigma0_u8` | C02 | new_source | **OK** | sentinel1_grd_measurement_u16 (base) | First dB-quantized, map-projected SAR (0.1 dB/DN) vs linear-amplitude S1 GRD u16; SAR backscatter itself is not new. |
| 6 | `earthbigdata_s1_global_coherence_vv_coh12_u8` | C02 | new_quantity | **OK** | sentinel1_grd_measurement_u16 (base) | InSAR coherence is a different quantity from backscatter, but it lands in the 8-bit 'percent + nodata' EO-raster pile. |
| 7 | `nasa_pds_magellan_fmidr_sar_u8` | C02 | new_source **disagree** | **WEAK** | nasa_pds_cassini_radar_bidr_sigma0_u8 (run, -57 min) | Second planetary SAR dB mosaic from the same PDS/AWS pipeline within the hour: criteria.md's own breadth example ('SAR backscatter mosaics of different bodies'). |
| 8 | `nasa_pds_voyager_iss_saturn_raw_u8` | C04 | new_source **disagree** | **WEAK** | mast_iue_swp_raw_image_u8 (run) | Second 8-bit raw vidicon frame family in the run: criteria.md's other named example ('raw camera frames from different space missions'). Judge: 'new source in a known modality'. |
| 26 | `noaa_wcsd_em302_water_column_i8` | C21 | new_source **disagree** | **WEAK** | zenodo_polarfront_ek60_power_i16, zenodo_adcp_pd0_backscatter_quality_u8 (base) | Water-column echo amplitude is already held (EK60 power, ADCP echo intensity); the 288-beam fan geometry is the only new axis. 5 sonar families pre-existed. |
| 27 | `sevir_vil_storm_events_u8` | C03 | new_source **disagree** | **WEAK** | noaa_nexrad_level3_nids_radials_u8 (base) | NEXRAD-derived 8-bit log-scaled precipitation code again (VIL mosaic vs N0Q radials): same radar network and width; adds a time axis, not a modality. |
| 28 | `noaa_cdr_seaice_conc_nh_daily_u8` | C01 | new_source **disagree** | **WEAK** | noaa_ims_snow_ice_cover_u8, jrc_global_surface_water_occurrence_u8 (base) | Another 8-bit NH polar-grid cryosphere product (0-100 + flag codes), same shape class as IMS/JRC; small 448x304 grids. |
| 29 | `fmi_radar_ppi_vrad_u8` | C03 | new_source | **OK** | noaa_nexrad_level3_nids_radials_u8 (base); sevir (run) | Doppler radial velocity (signed, Nyquist-folded) has genuinely different statistics from reflectivity/VIL; still the 3rd 8-bit weather-radar family. |
| 47 | `empiar_13192_sbfsem_vessel_slices_u8` | C07 | new_modality **disagree** | **OK** | zenodo_tem_tilt_series_i16 (base) | First SEM block-face backscatter imaging; electron microscopy already present (TEM tilt series), so not new_modality. |
| 50 | `mpc_modis_mod15a2h_fpar_u8` | C01 | new_quantity **disagree** | **WEAK*** | mpc_modis_mod13a1_ndvi_i16 (run); modis_active_fire_mask_u8 (base) | Same sensor/year/container as the NDVI recipe, 16 of 24 tiles overlap, back-up algorithm is an NDVI relation; percent+flag 8-bit raster class already held. Near-redundant. |
| 53 | `mpc_modis_mod10a1_ndsi_snow_cover_u8` | C01 | new_quantity **disagree** | **WEAK** | mpc_modis_mod15a2h_fpar_u8 (run, -15 min); noaa_ims_snow_ice_cover_u8 (base) | 3rd MODIS C6.1 product from the same MPC container and grid; judge's own note: 4th 8-bit '0-100 + flags' EO raster of the round; snow already covered by IMS. |
| 54 | `mpc_landsat_c2_l1_mss_dn_u8` | C01 | new_source **disagree** | **WEAK** | statlog_landsat_satellite_u8 (base); sentinel2_l2a_reflectance_cogs_u16 | Same instrument, quantity and width (Landsat MSS 8-bit DN) as statlog, optical multispectral already in S2; 4th Planetary Computer raster of the run. |
| 65 | `zenodo_nordif_ebsd_kikuchi_patterns_u8` | C08 | new_source **disagree** | **WEAK** | zenodo_silicon_diffraction_tiff_u16 (base) | EBSD Kikuchi patterns already a baseline family (only width/deposit differ). Mitigation: the baseline family is a single pattern, so this adds real EBSD volume. |
| 70 | `zenodo_hc18_fetal_head_ultrasound_u8` | C13 | new_modality **disagree** | **OK** | zenodo_rat_fus_image_sequence_f32 (base) | First clinical B-mode speckle imagery; ultrasound imaging already existed (functional ultrasound f32), so not new_modality. |
| 77 | `zenodo_astar_niti_sped_patterns_u8` | C08 | new_source **disagree** | **WEAK** | empiar_10318_microed_diffraction_frames_u16 (run); nordif (run) | Sparse Bragg-spot electron diffraction around a direct beam: same statistical class as the MicroED frames 2 h earlier; 2nd 8-bit electron-diffraction family of the run. |
| 78 | `noaa_rstn_sagamore_hill_srs_spectra_u8` | C06 | new_source **disagree** | **WEAK** | csiro_parkes_uwl_search_mode_u8 (run) | Second 8-bit radio dynamic-spectrum (time x frequency log power) family of the run; the judge noted it itself. |
| 79 | `zenodo_esrf_mxene_aerogel_microct_slices_u8` | C13 | new_modality **disagree** | **WEAK** | tcia_nsclc_radiomics_ct_i16 (base) | Reconstructed X-ray CT slices already exist (clinical CT); one specimen at 11 strain states, author-rescaled 8-bit. 'new_modality' was width-relative. |
| 81 | `empiar_10511_k2_counting_movie_frames_u8` | C07 | new_modality **disagree** | **OK** | zenodo_tem_tilt_series_i16 (base); EMPIAR x3 (run) | Sparse near-Poisson electron counts (~0.9 e/px) are statistically distinct from dense EM images; but it is the 4th EMPIAR family of the night. |

### 16-bit

| # | Family | Cluster | Judge | Verdict | Nearest existing | Justification |
|---|---|---|---|---|---|---|
| 1 | `mpc_goes18_abi_cmi_c13_fulldisk_u16` | C01 | new_modality **disagree** | **OK** | sentinel2_l2a_reflectance_cogs_u16 (base) | First geostationary thermal-IR full disk (cloud-dominated, off-disk fill); satellite radiance rasters exist, so new source, not new modality. |
| 2 | `mpc_modis_mod13a1_ndvi_i16` | C01 | new_quantity **disagree** | **WEAK** | modis_active_fire_mask_u8 (base); sentinel2_l2a_reflectance_cogs_u16 (base) | MODIS C6.1 land product from the same MPC container as the baseline fire mask; derived index raster where S2 reflectance already sits. Least-weak of the MODIS trio. |
| 11 | `mpc_aster_l1t_tir_u16` | C01 | new_source **disagree** | **WEAK** | mpc_goes18_abi_cmi_c13_fulldisk_u16 (run) | Second 12-bit-in-u16 thermal-IR satellite radiance raster of the run, same Planetary Computer pipeline as GOES-18. |
| 14 | `nasa_heasarc_batse_cont_counts_i16` | C05 | new_quantity | **OK** | nasa_heasarc_nicer_pi_i16 (base) | Binned multichannel gamma-ray count spectra (small Poisson integers, 8 det x 16 ch) vs per-photon PI events; same archive, different statistics. |
| 16 | `mast_jwst_nircam_sw_uncal_ramps_u16` | C04 | new_source | **OK** | nasa_pds_mastcamz_raw_i16 (base) | Up-the-ramp multi-read cubes (bias pedestal, accumulating ramp, jumps across 8 reads) are structurally distinct from single-read frames. |
| 18 | `ncbi_geo_mm285_methylation_idat_mean_u16` | C23 | new_modality | **STRONG** | encode_methylation_pct_u8 (base) | First bead-array/microarray scanner intensities (per-probe mean fluorescence, 361k probes x 2 channels); nothing comparable pre-existed. |
| 20 | `ncbi_geo_gpl5423_scanarray_cdna_scan_u16` | C23 | new_source | **OK** | bbbc021/039 microscopy u16 (base); mm285 (run) | Raw laser-scanner slide images (spot lattice, saturated cores) differ from widefield microscopy; 2nd microarray family 13 min after MM285, but a different representation. |
| 21 | `physionet_circor_pcg_i16` | C20 | new_source **disagree** | **WEAK** | esc50/librispeech/nsynth/openslr (base) | PCM16 audio is the most saturated 16-bit modality (6 baseline families); stethoscope heart sounds are new content. Also the 5th PhysioNet family of the run. |
| 22 | `nasa_heliocloud_iris_l1_fuv_frames_i16` | C04 | new_source **disagree** | **WEAK** | mast_iue_swp_raw_image_u8, mast_jwst (run); nasa_pds_mastcamz_raw_i16 (base) | UV-spectrograph raw detector frames again (IUE earlier in run); judge: 'second raw space-detector frame family at 16 bits'. |
| 31 | `aind_bci_2p_scanimage_trials_i16` | C11 | new_modality **disagree** | **OK** | dandi_001076 (run, traces); bbbc021 (base); fMRI BOLD i16 (base) | Raw two-photon PMT movies (shot noise, negative offsets, frame correlation) are a new representation; 2P calcium imaging was accepted 30 min earlier as traces. |
| 33 | `tcia_covid19_ny_sbu_chest_cr_u16` | C13 | new_source **disagree** | **WEAK** | tcia_cmmd_mammography_u16 (base) | Projection X-ray DICOM 12-in-16 from TCIA again (chest vs breast). Mitigation: CMMD holds only 2 planes. |
| 36 | `physionet_tpehg_ehg_i16` | C10 | new_quantity **disagree** | **WEAK** | uci_emg_gestures_i8, mitbih (base); grabmyo (run) | Surface biopotential via PhysioNet WFDB int16 (20 Hz uterine EMG); judge itself said 'new quantity within the known biopotential modality'. |
| 38 | `physionet_grabmyo_semg_i16` | C10 | new_source **disagree** | **WEAK** | uci_emg_gestures_i8 (base) | Surface EMG already exists (Myo armband i8); a 28-ch 2048 Hz lab amplifier is better material but the same measurement type. |
| 40 | `openneuro_ds003483_vectorview_meg_mag_i16` | C09 | new_source **disagree** | **WEAK** | openneuro_ds004212_things_meg_ctf_i32 (run); eeg_physionet/chbmit (base) | Second MEG family of the run; int16 multichannel neural streams exist; MaxFilter-processed codes, not raw. |
| 42 | `tcia_ldct_siemens_ct_projections_u16` | C13 | new_quantity | **OK** | zenodo_lodopab_ct_sinograms_f32 (base) | Measured helical-CT projections (vendor-corrected log line integrals) vs simulated parallel-beam f32 sinograms: same domain, different generation. |
| 48 | `physionet_charis_icp_i16` | C10 | new_quantity **disagree** | **WEAK** | physionet_bidmc_ppg_resp_i16 (base) | Another PhysioNet WFDB int16 clinical-monitor waveform (quasi-periodic, cardiac-modulated, 50 Hz); 9 records. |
| 55 | `empiar_10318_microed_diffraction_frames_u16` | C08 | new_modality **disagree** | **OK** | zenodo_silicon_diffraction_tiff_u16 (base) | First sparse spot-diffraction rotation frames; diffraction-pattern frames already existed (EBSD), so new source/quantity, not new modality. |
| 56 | `figshare_rousettus_vocalizations_i16` | C20 | new_source **disagree** | **WEAK** | esc50 etc. (base); circor (run) | PCM16 audio again (250 kHz ultrasonic content, same representation); judge's own note: 2nd 16-bit audio family of the run. |
| 59 | `empiar_10994_sbfsem_bsed_slices_u16` | C07 | new_source **disagree** | **WEAK*** | empiar_13192_sbfsem_vessel_slices_u8 (run, -40 min) | Same modality (SBF-SEM BSE block-face) and archive as EMPIAR-13192 accepted 40 min earlier; only width/lab/specimen differ. |
| 71 | `figshare_oscgrid_comtrade_raw_adc_i16` | C14 | new_modality **disagree** | **OK** | household_power_uci (base); nsynth (periodic tones) | First point-on-wave grid V/I waveforms (50 Hz at 1600 Hz, switching transients); power-grid domain exists, so OK not STRONG. |
| 73 | `ceda_ukdale_iam_appliance_power_u16` | C14 | new_source **disagree** | **WEAK** | household_power_uci (sub-metering), appliances_energy_uci (base) | Household electricity consumption series (incl. circuit sub-meters) already present; per-plug integer watts is new content. |
| 76 | `usgs_grandbay_klein3900_sidescan_xtf_u16` | C21 | new_source | **OK** | zenodo_polarfront_ek60_power_i16 (base); em302 (run) | Seafloor imaging sonar (textured bottom returns across range) differs from mostly-empty water-column echograms; but 7th underwater-acoustics family. |

### 32-bit

| # | Family | Cluster | Judge | Verdict | Nearest existing | Justification |
|---|---|---|---|---|---|---|
| 10 | `openneuro_ds003097_aomic_cortical_thickness_f32` | C12 | new_quantity | **OK** | openneuro_ds000030_t1w_mri_f32 (base) | Per-vertex mesh scalar field is a new structure (not a voxel grid), though another OpenNeuro MRI derivative in a neuro-heavy 32-bit. |
| 12 | `openneuro_ds004212_things_meg_ctf_i32` | C09 | new_modality **disagree** | **OK** | eeg_physionet/chbmit (base); seismic_waveform_i32 (downstream) | First MEG (raw SQUID int32 counts, large offsets); multichannel neural waveforms exist, so the cluster is known. |
| 13 | `openneuro_ds003097_aomic_dti_tensor_f32` | C12 | new_quantity **disagree** | **WEAK** | openneuro_ds000030_t1w_mri_f32 (base); aomic thickness (run, -4 min) | OpenNeuro brain volume float32 again; 2nd AOMIC derivative accepted 4 minutes after the first. |
| 15 | `openneuro_ds004584_pd_rest_eeg_f32` | C09 | new_source **disagree** | **WEAK** | eeg_physionet, chbmit_physionet (base) | Scalp EEG already exists twice; the float32 EEGLAB export is a representation change (judge: 'not a new modality'). |
| 23 | `physionet_eit_thorax_images_f32` | C13 | new_modality | **STRONG** | (none; nearest fMRI/CT) | Electrical impedance tomography absent before; 32x32 50 Hz conductivity-change image sequences. |
| 24 | `dandi_001076_zebrafish_calcium_fluorescence_f32` | C11 | new_modality **disagree** | **OK** | nasa_tess_lightcurves_f32 (statistical analogue) | Calcium ROI traces are a new measurement type, but as bytes they are slow positive multichannel float32 series much like light curves. |
| 32 | `dandi_000020_patchseq_current_clamp_f32` | C09 | new_modality **disagree** | **OK** | zenodo_open_ephys_continuous_i16 (base) | Intracellular membrane potential (stimulus steps, spikes, 50 kHz) differs from extracellular/EEG; electrophysiology cluster exists. |
| 44 | `icraf_afsis1_soil_mir_spectra_f32` | C24 | new_modality **disagree** | **OK** | zenodo_powder_xrd_patterns_f32, zenodo_marine_dom_positive_ms1_f32 (base) | First FTIR absorbance spectra; 1-D float32 spectral curves on fixed grids already exist (powder XRD), so OK, not STRONG. |
| 46 | `aloft_uva_vpts_animal_reflectivity_f32` | C03 | new_source | **OK** | dwd_radolan_rw_precip_i16 (base, same DWD radars) | Derived bio-scatterer vertical-profile time series (time x 25 height bins): different product and shape; 5th weather-radar family overall. |
| 51 | `goose_vls128_lidar_scan_xyz_f32` | C18 | new_modality **disagree** | **OK** | dc_lidar_2015_* (base); modelnet10 vertices f32 (base) | First ring-ordered spinning-LiDAR XYZ; LiDAR attributes and 3-D float32 coordinates exist, so new source, not new modality. |
| 57 | `gwa_v4_country_wind_speed_100m_f32` | C01 | new_quantity **disagree** | **WEAK** | usgs_shakemap_ground_motion_f32, weatherbench2 ERA5 winds (base) | Modelled geospatial float32 raster with NaN mask, same class as ShakeMap/WorldClim rasters; new quantity only. |
| 58 | `rwth_isea_home_storage_battery_voltage_f32` | C15 | new_source **disagree** | **WEAK** | kollmeyer_panasonic18650pf_drive_cycle_voltage_f64 (run) | Battery terminal voltage accepted 6 h earlier in the run; judge itself labelled it new_source (field pack vs lab cell). |
| 60 | `fingrid_nordic_grid_frequency_10hz_f32` | C14 | new_quantity | **OK** | (none) | Grid frequency at 10 Hz (tight band around 50 Hz, 10 uHz resolution) is a new quantity. |
| 61 | `tartanair_optical_flow_f32` | C25 | new_modality **disagree** | **OK** | zenodo_morphodunes_piv_f64 (base) | First optical flow (piecewise-smooth, motion boundaries); 2-component dense vector fields existed as PIV f64. Near-STRONG. |
| 62 | `zenodo_gridgnosis_pmu_voltage_magnitude_f32` | C14 | new_source | **OK** | power_voltage (downstream, 1-min household) | 50 fps synchrophasor magnitudes on a transmission grid: a new measurement process. |
| 63 | `luh_lumo_tower_acceleration_f32` | C19 | new_source **disagree** | **WEAK** | zenodo_accelerometer_pcm16, zenodo_spica_urban_das_f32, har (base) | Accelerometer/vibration waveforms already present (honeybee accel, DAS f32, HAR); structural modes are new content. |
| 64 | `cartographer_backpack2d_hokuyo_ranges_f32` | C18 | new_quantity **disagree** | **WEAK** | goose (run); tum_rgbd_depth_u16 (base) | Second laser-ranging family at 32-bit, 73 minutes after GOOSE (judge's own note); range in metres already present. |
| 67 | `diode_val_laser_depth_f32` | C18 | new_source **disagree** | **WEAK** | tum_rgbd_depth_u16 (base); goose + cartographer (run) | Dense depth maps exist (TUM u16); 3rd laser/range family at 32-bit within 90 minutes. Judge: 'Depth and laser distance in metres already exist'. |
| 72 | `ahmedml_cfd_surface_mean_pressure_f32` | C22 | new_modality **disagree** | **OK** | zenodo_gia_stress_fields_f64, weatherbench2 (base) | First CFD solution field (unstructured surface mesh); simulated physical fields existed (FE stress, reanalysis), so OK. |
| 74 | `rgl_epfl_isotropic_spectral_brdf_f32` | C24 | new_modality | **STRONG** | zenodo_venere_nir_hsi_u16 (spectral cube) | Goniometric spectral BRDF tensors (incident angle x outgoing grid x wavelength), absent before. |
| 82 | `aalto_arni_room_impulse_response_f32` | C20 | new_source **disagree** | **WEAK** | openslr_rirs_noises_pcm16 (base) | Measured RIRs are already a family; native float32 is a width/representation difference (judge: new source, not modality). |
| 83 | `pdebench_2d_cfd_turb_m1_density_f32` | C22 | new_source **disagree** | **WEAK** | ahmedml (run); weatherbench2 (base) | Second simulated fluid field at 32-bit within the hour; dense float32 physical grids already exist (ERA5, WMAP). |
| 85 | `the_well_post_neutron_star_merger_density_f32` | C22 | new_source **disagree** | **WEAK*** | pdebench_2d_cfd_turb_m1_density_f32 (run, -6 min) | Third simulated fluid-density field at 32-bit, 6 minutes after PDEBench density; judge itself downgraded it to new_source. |

### 64-bit

| # | Family | Cluster | Judge | Verdict | Nearest existing | Justification |
|---|---|---|---|---|---|---|
| 9 | `comma2k19_global_pose_ecef_positions_f64` | C17 | new_source **disagree** | **WEAK** | tum_rgbd_groundtruth_pose_f64 (base) | Estimated trajectory positions in f64 already exist; judge: 'The modality, coordinate trajectories, is already known'. |
| 17 | `kollmeyer_panasonic18650pf_drive_cycle_voltage_f64` | C15 | new_quantity | **OK** | zenodo_battery_eis_complex_f32 (base) | Cell voltage under drive cycles is a new quantity in the battery domain. Caveat: ~12-bit ADC lattice stored as double (thin 64-bit material). |
| 19 | `noaa_dcdb_csb_vessel_track_lonlat_f64` | C17 | new_source **disagree** | **WEAK** | citibike_2024_trip_geocoords_f64, noaa_marinecadastre_ais (base); comma2k19 (run) | Decimal-degree lat/lon f64 on a 1e-6 lattice, the commonest 64-bit coordinate representation; vessel positions already via AIS. |
| 25 | `naif_mro_sc_bus_attitude_ck_f64` | C16 | new_source | **OK** | tum_rgbd_groundtruth_pose_f64 (quaternions), nasa_naif_de440s_spk (base) | Spacecraft Kalman-filter attitude quaternions + gyro rates differ in generation from mocap pose. Borderline. |
| 30 | `monado_msd_valve_index_imu_f64` | C19 | new_source **disagree** | **WEAK** | har_smartphone_uci; har_* downstream at 16/32/64 | 3-axis gyro/accel streams already present at 64-bit downstream; 1 kHz full-mantissa is better material, same measurement type. |
| 34 | `mace_mp_foundation_model_weights_f64` | C26 | downstream_mirror_fill | **OK** | hf_timm_resnet18_conv_f32, gencast, smollm (base); nn_weight_f64 (downstream) | NN weights are a known modality; the value is genuinely f64-trained mantissas (honestly labelled downstream_mirror_fill). |
| 35 | `dandi_ibl_bwm_spike_amplitudes_f64` | C09 | new_quantity **disagree** | **WEAK** | zenodo_npx_opto_templates_f32 (base) | Neuropixels/Kilosort spike-sorting output again; values are float32 amplitudes x one per-unit scale (~24 bits of information in a 64-bit word). |
| 37 | `gfz_gracefo_fgm_acal_bnec_f64` | C16 | new_source | **OK** | usgs_geomag_observatory_minute_f32 (base) | Same quantity (B vector) but orbit-swept large-amplitude 1 Hz signal vs near-static ground observatory. Borderline. |
| 39 | `igs_final_satellite_clock_bias_f64` | C16 | new_quantity | **OK** | noaa_cors_rinex_observations_f64 (base) | Satellite clock offsets (smooth drift + ps noise): a new GNSS quantity. |
| 41 | `exomol_state_energy_levels_f64` | C24 | new_modality **disagree** | **OK** | (decimal-text f64 families abundant) | New domain (molecular term values), but F12.6 decimal-text -> f64 is the commonest 64-bit representation; not new_modality. |
| 43 | `jpl_gnssro_cosmic1_l1b_excess_phase_f64` | C16 | new_source **disagree** | **WEAK** | noaa_cors_rinex_observations_f64 (carrier phase, base); igs (run) | GNSS carrier-phase observable again (smooth ramps), 3rd GNSS family; LEO limb geometry is new content. |
| 45 | `noaa_stofs2d_glo_adcirc_station_water_level_f64` | C22 | new_source | **OK** | noaa_tides_water_level, noaa_coops_water_level (base) | Same quantity as observed gauges but simulated full-mantissa forecasts at 1,688 stations: different generation and statistics. |
| 49 | `leap_climsim_lowres_e3sm_mmf_state_fields_f64` | C22 | new_source **disagree** | **WEAK** | weatherbench2_era5_pressure_level_fields_f32; zenodo_gia_stress_fields_f64 (base) | Gridded model air temperature already exists (ERA5 f32) and 64-bit simulated fields exist (GIA); mostly the same quantity at another width. |
| 52 | `hamsci_grape1_wwv10_doppler_frequency_f64` | C16 | new_source | **OK** | fingrid (run, 32-bit frequency) | First HF ionospheric-Doppler series (1 mHz lattice around 10 MHz). |
| 66 | `wiod2016_world_input_output_tables_f64` | C27 | new_modality | **STRONG** | nist_matrix_market_sparse_matrices (base) | Dense multi-regional economic flow matrices (block structure, heavy tails, full mantissa) absent before. |
| 68 | `azure_vm2019_cpu_utilization_readings_f64` | C27 | new_modality | **STRONG** | loghub/clickbench (downstream; other quantities) | Cloud VM utilization telemetry absent before. |
| 69 | `cesnet_ts24_institution_traffic_bytes_u64` | C27 | new_modality **disagree** | **OK** | wikimedia_pageviews_daily (base) | Network traffic-volume counters (diurnal/weekly count series): new quantity; traffic-count time series exist (pageviews), so not new_modality. |
| 75 | `nrel_resstock2021_state_enduse_load_profiles_f64` | C14 | new_source | **OK** | electricity_load_diagrams_uci, household_power_uci (base); ukdale (run) | Simulated stock-weighted EnergyPlus profiles (full mantissa) vs metered decimal load series: different generation; 3rd energy-load addition. |
| 80 | `fermi_gbm_tte_nai_photon_arrival_times_f64` | C05 | new_quantity | **OK** | dc_lidar_2015_gps_time_f64 (time-tag repr.), nicer (base) | Photon arrival-time point process is new for astrophysics; sorted f64 time tags as a representation already exist. |
| 84 | `orex_ola_l2_lidar_point_xyz_f64` | C18 | new_source **disagree** | **WEAK** | goose_vls128_lidar_scan_xyz_f32 (run); nasa_pds_mola_megdr_i16 (base) | Lidar point XYZ accepted earlier in the run at 32-bit; planetary laser altimetry exists (MOLA). Judge: 'The modality, lidar point xyz, already exists'. |

## Judge-label disagreements (label inflation)

- `new_modality`: 23 labelled; 6 STRONG here; **17 downgraded** (16 to OK, 1 to WEAK).
- `new_source`/`new_quantity`: 40 of 62 rated WEAK, i.e. the honest label was "new content in a known modality". The judge never used that rung.
- No upgrades: no family labelled below new_modality was rated STRONG here.

| Family | Width | Judge | Verdict | Why the label is inflated |
|---|---|---|---|---|
| `zenodo_esrf_mxene_aerogel_microct_slices_u8` | 8 | new_modality | WEAK | 'first 8-bit reconstructed tomography': width-qualified; clinical CT exists |
| `empiar_13192_sbfsem_vessel_slices_u8` | 8 | new_modality | OK | 'first EM family at 8-bit': a width-qualified claim; TEM existed |
| `zenodo_hc18_fetal_head_ultrasound_u8` | 8 | new_modality | OK | ultrasound imaging existed (rat fUS f32) |
| `empiar_10511_k2_counting_movie_frames_u8` | 8 | new_modality | OK | EM existed and this is the 4th EMPIAR family; statistically distinct though |
| `mpc_goes18_abi_cmi_c13_fulldisk_u16` | 16 | new_modality | OK | satellite radiance rasters exist (S2 u16); new platform, not modality |
| `aind_bci_2p_scanimage_trials_i16` | 16 | new_modality | OK | fluorescence microscopy and image time series exist; 2P traces accepted 30 min earlier |
| `empiar_10318_microed_diffraction_frames_u16` | 16 | new_modality | OK | diffraction-pattern frames existed (EBSD u16) |
| `figshare_oscgrid_comtrade_raw_adc_i16` | 16 | new_modality | OK | power-grid domain existed; PMU/frequency accepted earlier in run |
| `openneuro_ds004212_things_meg_ctf_i32` | 32 | new_modality | OK | multichannel neural waveforms exist (EEG, Open Ephys) |
| `dandi_001076_zebrafish_calcium_fluorescence_f32` | 32 | new_modality | OK | derived float32 traces, statistically like TESS light curves |
| `dandi_000020_patchseq_current_clamp_f32` | 32 | new_modality | OK | electrophysiology cluster exists |
| `icraf_afsis1_soil_mir_spectra_f32` | 32 | new_modality | OK | 1-D f32 spectral curves exist (powder XRD) |
| `goose_vls128_lidar_scan_xyz_f32` | 32 | new_modality | OK | LiDAR (DC LAS) and f32 3-D coordinates exist |
| `tartanair_optical_flow_f32` | 32 | new_modality | OK | dense vector fields existed (PIV f64) |
| `ahmedml_cfd_surface_mean_pressure_f32` | 32 | new_modality | OK | simulated physical fields existed (GIA FE, ERA5) |
| `exomol_state_energy_levels_f64` | 64 | new_modality | OK | decimal-text f64, the commonest 64-bit representation |
| `cesnet_ts24_institution_traffic_bytes_u64` | 64 | new_modality | OK | traffic-count time series exist (pageviews) |

Families labelled new_source/new_quantity but rated WEAK (label should have been new content in a known modality):

`nasa_pds_magellan_fmidr_sar_u8`, `nasa_pds_voyager_iss_saturn_raw_u8`, `noaa_wcsd_em302_water_column_i8`, `sevir_vil_storm_events_u8`, `noaa_cdr_seaice_conc_nh_daily_u8`, `mpc_modis_mod15a2h_fpar_u8`, `mpc_modis_mod10a1_ndsi_snow_cover_u8`, `mpc_landsat_c2_l1_mss_dn_u8`, `zenodo_nordif_ebsd_kikuchi_patterns_u8`, `zenodo_astar_niti_sped_patterns_u8`, `noaa_rstn_sagamore_hill_srs_spectra_u8`, `mpc_modis_mod13a1_ndvi_i16`, `mpc_aster_l1t_tir_u16`, `physionet_circor_pcg_i16`, `nasa_heliocloud_iris_l1_fuv_frames_i16`, `tcia_covid19_ny_sbu_chest_cr_u16`, `physionet_tpehg_ehg_i16`, `physionet_grabmyo_semg_i16`, `openneuro_ds003483_vectorview_meg_mag_i16`, `physionet_charis_icp_i16`, `figshare_rousettus_vocalizations_i16`, `empiar_10994_sbfsem_bsed_slices_u16`, `ceda_ukdale_iam_appliance_power_u16`, `openneuro_ds003097_aomic_dti_tensor_f32`, `openneuro_ds004584_pd_rest_eeg_f32`, `gwa_v4_country_wind_speed_100m_f32`, `rwth_isea_home_storage_battery_voltage_f32`, `luh_lumo_tower_acceleration_f32`, `cartographer_backpack2d_hokuyo_ranges_f32`, `diode_val_laser_depth_f32`, `aalto_arni_room_impulse_response_f32`, `pdebench_2d_cfd_turb_m1_density_f32`, `the_well_post_neutron_star_merger_density_f32`, `comma2k19_global_pose_ecef_positions_f64`, `noaa_dcdb_csb_vessel_track_lonlat_f64`, `monado_msd_valve_index_imu_f64`, `dandi_ibl_bwm_spike_amplitudes_f64`, `jpl_gnssro_cosmic1_l1b_excess_phase_f64`, `leap_climsim_lowres_e3sm_mmf_state_fields_f64`, `orex_ola_l2_lidar_point_xyz_f64`

## Worst offenders

Ranked by overlap with an existing family and by how plainly the pipeline's own criteria should have stopped them:

1. `mpc_modis_mod15a2h_fpar_u8` + `mpc_modis_mod10a1_ndsi_snow_cover_u8` (+ `mpc_modis_mod13a1_ndvi_i16`): Three MODIS C6.1 products from one MPC container, one grid and one year. FPAR shares 16/24 tiles with NDVI and its back-up algorithm is an NDVI relation. Snow was knowingly accepted as the '4th 0-100 + flags raster'.
2. `nasa_pds_magellan_fmidr_sar_u8`: criteria.md's literal example of a breadth violation, accepted 57 min after Cassini RADAR.
3. `nasa_pds_voyager_iss_saturn_raw_u8` (+ `nasa_heliocloud_iris_l1_fuv_frames_i16`): criteria.md's other literal example (raw camera frames from different missions); IRIS is the 2nd UV-spectrograph raw frame family after IUE.
4. `mpc_landsat_c2_l1_mss_dn_u8`: Same instrument, quantity, width and representation as baseline `statlog_landsat_satellite_u8`; 4th Planetary Computer raster of the night.
5. `empiar_10994_sbfsem_bsed_slices_u16`: SBF-SEM BSE again, 40 minutes after EMPIAR-13192, separated only by width and specimen.
6. `the_well_post_neutron_star_merger_density_f32` / `pdebench_2d_cfd_turb_m1_density_f32`: Simulated fluid density twice at 32-bit, 6 minutes apart (3rd and 2nd fluid fields within the hour).
7. `cartographer_backpack2d_hokuyo_ranges_f32` / `diode_val_laser_depth_f32` (+ `orex_ola_l2_lidar_point_xyz_f64`): Three laser-ranging families at 32-bit within 90 minutes, then lidar XYZ again at 64-bit.
8. `openneuro_ds003483_vectorview_meg_mag_i16` / `openneuro_ds004584_pd_rest_eeg_f32`: Second MEG; float32 re-export of scalp EEG that already exists twice at 16-bit.
9. `physionet_charis_icp_i16`, `physionet_tpehg_ehg_i16`, `physionet_grabmyo_semg_i16`, `physionet_circor_pcg_i16`: Four more PhysioNet WFDB int16 waveforms, bringing that archive/format to 8 families at 16-bit.
10. `zenodo_astar_niti_sped_patterns_u8`, `noaa_rstn_sagamore_hill_srs_spectra_u8`, `rwth_isea_home_storage_battery_voltage_f32`: Each is the second of a pair accepted hours earlier (spot diffraction, radio dynamic spectra, battery voltage).

## Why the screener/judge let these through (evidence)

1. **The breadth rule is per width and run-only.** criteria.md: "Once a modality already has two or more new families *at a width in this collection effort*". It ignores baseline members and siblings at other widths. That is how SBF-SEM u8 then u16, MEG i32 then i16, EEG f32 (baseline i16), EBSD u8 (baseline u16), lidar f32 then f64 and battery f64 then f32 all passed.
2. **The first two per width are free, and the judge chooses the granularity.** It splits finely: EBSD vs SPED, VRAD vs VIL vs N0Q, '8-bit radio dynamic spectrum'. So the counter rarely reaches 2.
3. **Breadth is advisory.** Only 9/85 reports mention it. Every report that flags it still accepts (MODIS snow, FPAR, Landsat MSS, SPED, Rousettus, Cartographer, PDEBench, The Well).
4. **Novelty claims are qualified until they become true**: 'first per-pixel snow-index family', 'first 16-bit SBF-SEM family', 'first 64-bit lidar point family', 'first EEG family at 32 bits'. `novelty.py` is term/URL matching, so a narrow term returns no hit.
5. **Quota pressure.** `baseline.json` sets `target_new_per_width: 50`. That rewards filling a width with variants rather than leaving it short.
6. The screener *can* apply saturation: `zenodo_slac_ued_beam_camera_images_u8` was screened out as "weak and ambiguous material in an already-saturated modality". It did so once.

## Recommendations: a testable collection-level diversity check

- **Measurement-type key + cross-width, baseline-inclusive count (gate.py).** Every card declares `measurement_type` (fine-grained, e.g. `sar_backscatter`, `raw_space_frame`, `spot_diffraction`, `sem_bse_image`, `meg`, `laser_range`; not a broad domain), plus `instrument_line` and `archive_collection` (host + collection path prefix). The gate counts prior members over baseline + run at *all* widths. If the count is >=1, the family is presumed `new_content_same_modality` and can rise above that only with a *measured* statistical difference recorded in the card. Replay on this run (keys in the audit work dir):

  | Rule | Families flagged | WEAK flagged (of 41) | STRONG/OK flagged (of 44) |
  |---|---|---|---|
  | broad cluster, any width, >=2 incl. baseline | 81 | 41 | 40 |
  | CURRENT rule: >=2 same-type run acceptances at same width | 3 | 3 | 0 |
  | PROPOSED: same measurement type in baseline or earlier in run, any width | 52 | 41 | 11 |
  | PROPOSED cap: same measurement type accepted earlier in run, any width | 23 | 23 | 0 |

  The current rule fires on only 3 families: `mpc_modis_mod10a1_ndsi_snow_cover_u8`, `diode_val_laser_depth_f32` and `the_well_post_neutron_star_merger_density_f32`. All three were accepted anyway, and two of their reports acknowledge the saturation in writing.
  The proposed rule flags 41/41 WEAKs. Its 11 STRONG/OK hits (`mpc_goes18_abi_cmi_c13_fulldisk_u16`, `mast_iue_swp_raw_image_u8`, `nasa_pds_cassini_radar_bidr_sigma0_u8`, `mace_mp_foundation_model_weights_f64`, `tcia_ldct_siemens_ct_projections_u16`, `icraf_afsis1_soil_mir_spectra_f32`, `noaa_stofs2d_glo_adcirc_station_water_level_f64`, `goose_vls128_lidar_scan_xyz_f32`, `tartanair_optical_flow_f32`, `cesnet_ts24_institution_traffic_bytes_u64`, `zenodo_hc18_fetal_head_ultrasound_u8`) are exactly the cases that should carry a written statistical justification. Keying on broad domains flags 81/85, so the key must be the measurement type, not the domain. The key assignment is circular with this audit, so treat the replay as a demonstration of mechanism, not an independent validation.
- **Make the ladder binding.** When the measurement-type count is >=1, `novelty_kind` defaults to `new_content_same_modality`. `new_modality` needs a zero-hit measurement-type search across all widths and downstream, and width-qualified claims ('first X at N-bit') are mechanically mapped to `width_only`/`new_content`. Test: `new_modality` share drops from 23/85 toward ~6/85.
- **Same-pipeline cap.** At most 2 accepted recipes per `archive_collection` per run (e.g. `modiseuwest/modis-061-cogs`, `ftp.ebi.ac.uk/empiar`, `physionet-open`, `openneuro`). On this run it would have stopped MODIS #3, EMPIAR #3-4, PhysioNet #3-5 and OpenNeuro #3-5. Exceeding the cap needs a human sign-off field.
- **Breadth override is a gate, not prose.** If the judge writes a breadth note, require `breadth_override: <measured reason>`, route the family to human review, and count overrides per run.
- **Replace the per-width quota with a diversity budget.** Order the queue by the number of distinct clusters still unfilled, so saturated-cluster candidates wait instead of being judged in isolation. Optional: a cheap byte-statistics fingerprint per primary series (dtype, histogram entropy, distinct-value ratio, lag-1 autocorrelation, fill fraction, zstd ratio). Any family within a threshold distance of an existing family must address that neighbour. This catches the 8-bit '0-100 + flags' raster pile regardless of naming.

## Caveats

- The verdicts are judgment calls against the brief's definitions. Borderline OK/WEAK cases are marked in the justifications (MRO attitude, GRACE-FO magnetometer, ScanArray, Aloft VPTS, Klein side-scan, ResStock).
- Clusters and measurement-type keys were drawn after the fact. The replay numbers show what such a keyed rule would do, not what the pipeline's own vocabulary would do.
- WEAK does not mean worthless. Several WEAK families are better material than the baseline family they shadow: the EBSD and chest-CR families deepen one- and two-sample baseline families, and GRABMyo is a better EMG regime. A curator may keep some, but they should be counted as depth, not breadth.
- `datasets/zenodo_cryoet_tilt_series_i16/` is an empty untracked directory (no manifest), so it is neither baseline nor run output and was ignored.
