# Physical inventory and sensor backend

The 24 × 28.30 m warehouse uses a session-specific physical inventory for all
420 packages. A fresh seed changes the package contents, condition and visual
defects. A fixed seed replays them. This is a synthetic inspection benchmark.

## Launch and read observations

```sh
/path/to/isaac-sim/python.sh sim/build_environment.py --warehouse-v3 \
  --seed 42 --output sim/out/inspection/physical-42/warehouse.usda \
  --fault-manifest sim/out/evaluator/physical-42.json
```

Without `--fault-manifest`, the launcher creates one under the ignored
`sim/out/environment/evaluator/` directory and records its path in the build
report. Treat build reports and manifests as simulator-side files. Do not pass
them to the agent. USD carries the normal identity labels and physical-looking
geometry and textures. It carries no private inventory fields.

The manifest's top-level `drums` list retains the visual-fault records for
earlier tooling. `physical_inventory.drums` has every package, including clean
packages, keyed by `drum_id`. When creating a session in process, you can build
an inventory with `warehouse_physics.generate_inventory(layout, seed)` and
pass it as `inventory=` to `generate_session`. The generator attaches the
rendered appearance metadata to the same inventory object.

Add `sim/warehouse-v3` to the simulator Python path and keep the backend
outside the agent process:

```python
from warehouse_sensors import WarehouseSensors

sensors = WarehouseSensors.from_manifest(private_manifest_path)
reading = sensors.sample(
    robot_xyz, sim_seconds, gamma_xyz=gamma_detector_xyz, gas_xyz=gas_inlet_xyz
)
# Send reading and the normal sensor frame references to the agent.
```

- Position units are metres in warehouse world coordinates. Pass monotonically
  increasing simulation seconds and use the actual detector and inlet poses.
  `dose_rate_uSv_h` is the gamma detector's total reading.
  `mission_dose_mSv` integrates that noisy reading over elapsed time.
- `hydrogen_ppm` is local air at the inlet. A null value with
  `hydrogen_status: below_detection` means the instrument did not resolve a
  concentration above its synthetic detection limit. It does not prove that no
  gas is present. The same distinction applies to swab channels.
- For directional gamma, `gamma_bins(position, yaw_rad)` gives a blurred
  synthetic bearing cue with 16 bins. It carries no source identity.
- For LWIR, call `thermal_from_camera(optical_depth, segmentation, intrinsics,
  camera_to_world)` on matched Isaac frames. Supply optical depth in metres,
  Replicator semantic data with the existing `class` and `drum_id` labels,
  pixel intrinsics, and the USD camera-to-world matrix. The backend uses the
  private segmentation only to look up materials. Return only the apparent °C
  image and its external timestamp to the agent. NaN denotes missing depth.
- For removable contamination, use `start_swab(contact_xyz, time_s,
  robot_xyz=pose, robot_stopped=True)` and poll with `poll_swab(time_s)`.
  This is a virtual tool. It checks planar reach and dwell, then samples a
  defined floor footprint. It does not actuate a physical arm.
- For unresolved readings, retain `below_detection` or mark attribution
  inconclusive. Check a second view for bulges, compare thermal readings at
  similar view angles, and sample upwind and downwind before attributing a plume.
  A 3.32 m aisle gives space to leave its centreline for a legal standoff pose.

The older 28-drum `SensorWorld` and its agent contract remain separate. The
warehouse adapter can be called by an autonomy loop and is exercised in the
Isaac check. The legacy agent and its detection policy have not been
ported to the 420-drum scene.

## Physical assumptions and source register

| Quantity | LLW | ILW |
|---|---|---|
| Waste-form families | Dry soft waste, offcuts, conditioned filters | Grouted mixed metal, immobilised sludge, grouted pucks |
| Synthetic net mass | 35–180 kg | 560–1,050 kg |
| Synthetic free-gas volume | 8–20% of 208 L | 5–12% of 500 L |
| Package and thermal appearance | Painted steel, nominal emissivity 0.87 | Grouted stainless design with retained teal display finish, nominal effective emissivity 0.48 |
| Effective gamma attenuation | 0.7–3.2 m⁻¹ | 12–19 m⁻¹ |
| Nominal gas pathway | Sealed | Filtered |
| Reactive scenario H₂ generation | 2–18 mL STP/day | 8–60 mL STP/day |

These are calibrated scenario settings, not measured population distributions,
package acceptance criteria or operational thresholds. Values, units and
sensor assumptions are in [physical_config.json](physical_config.json).

- **Inventory and dose.** UK activity concentration boundaries are 4 GBq/t
  alpha and 12 GBq/t beta/gamma. The generator checks package-class consistency
  using synthetic activity components. The non-gamma components are equivalent
  pools, not identified radionuclides. Three finite-height source samples
  per package, exponential path attenuation through each nominal cylinder,
  and count noise generate dose. Effective coefficients are synthetic
  waste-form proxies. Scattering, detailed spectra and detector calibration
  would require a validated transport model. The published 100 W per standard
  500 L drum is a transport limit and is not used as typical decay heat.
  [UK Inventory classification](https://ukinventory.nda.gov.uk/information-hub/factsheets/what-are-the-main-waste-categories/) · [NWS container designs](https://www.gov.uk/guidance/application-of-waste-package-specifications-for-low-heat-generating-waste-standardised-waste-container-designs) · [NDA Derived Inventory, Table 30](https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/835821/NDA_Report_no_DSSC-403-01_-_Geological_Disposal_-_Derived_Inventory_Report_a.pdf) · [NIST XCOM](https://www.nist.gov/pml/xcom-photon-cross-sections-database)
- **Temperature.** A lumped heat model separates deposited decay energy and
  chemical heat. Localized chemical heat can create a warm patch, while
  emissivity and reflected radiation can alter apparent temperature even on a
  cool shell. The thermal renderer uses a grey-body approximation and
  simulated detector noise. It does not reconstruct internal temperature.
  [Sellafield-relevant environmental thermometry](https://arxiv.org/abs/2010.03395) · [500 L vent thermometry](https://arxiv.org/abs/1807.07816)
- **Gas and deformation.** Separate first-order gas retention and pressure
  relaxation terms use headspace volume, age of the episode and vent state.
  A finite release pulse uses an explicit gas reservoir. The outdoor-style
  advection–diffusion kernel is a lightweight indoor plume approximation
  without rack-resolved CFD. An inlet samples that field after a travel delay
  and response lag. Restricted vents can support a bulge with weak external
  evidence. An ILW lobe can instead be assigned to solid internal expansion.
  Methane is zero in this scenario mix. [NDA Waste Package Evolution](https://assets.publishing.service.gov.uk/media/5a81e778ed915d74e3400adf/NDA_Report_no_DSSC-451-01_-_Geological_Disposal_-_Waste_Package_Evolution_Status_Report.pdf) · [ILW deformation study](https://www.sciencedirect.com/science/article/abs/pii/S0141029616308148) · [HSE detector response and sampling](https://www.hse.gov.uk/pubns/gasdetector.pdf)
- **Surface contamination.** Rust and contamination are independent. A breach
  or material transfer can produce a removable deposit with no change to the
  package's gamma source. A wipe estimates activity from its footprint,
  simulated recovery and count uncertainty. Neither a wipe nor ambient dose
  diagnoses the condition of the whole package. [IAEA contamination screening guidance](https://nucleus.iaea.org/sites/nss-oui/Published%20Collections/m_8e6b9ecd-c4fc-40df-bf0e-b297f9d5bace/c_cef87a11-e17d-4c56-95b4-ca8a07aa10d5bace__1_0.Html)

## Calibration and replay

Run `verify_physical_sensors.py --out checks/physical-sensor-calibration.json`
with the local OpenUSD Python environment. It exercises three seeds, class
consistency, gas delay and localization, warm and cool shell controls, clean
and positive wipes, cumulative dose, and the observation boundary. The trace
samples route-node positions independently. It does not drive the robot.
Run `verify_fault_session.py` for same-seed geometry and material replay.

The RTX launcher accepts `--fault-seed` to verify the session and capture
co-registered simulated LWIR frames from the Isaac inspection cameras.

The release run verified all 420 physical records and semantic labels, 79 static
physics probes, and three co-registered apparent-temperature captures including
a warm ILW control. A separate launch loaded Spot and attached its body camera.
The three-seed synthetic field and paired controls are in the
[calibration report](checks/physical-sensor-calibration.json). The exact Isaac
build, asset fingerprint, and frame summaries are in the
[Isaac validation report](checks/physical-isaac-summary.json).
