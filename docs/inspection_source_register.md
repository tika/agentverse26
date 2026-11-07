# Inspection source register

Reviewed 7 November 2026. This is the reference for the pitch, simulation
configuration and inspection report. The original project brief is preserved
in [inspection_criteria_source.txt](inspection_criteria_source.txt).

## Why Sellafield and which waste

| Source | What we take from it | How we use it |
| --- | --- | --- |
| [UK Radioactive Waste Inventory, Sellafield site, 2025 stock table](https://ukinventory.nda.gov.uk/site/sellafield/) | At **1 April 2025**, reported Sellafield stocks were **76,200 m³ ILW**, **3,020 m³ LLW**, **1,960 m³ HLW** and **0 m³ VLLW**, against a rounded total of **81,200 m³**. These are reported stock volumes. Conditioned volumes, packaged volumes and future arisings have separate columns. | ILW is the strongest site-specific reference for the store. LLW is also present and provides a useful comparison in our mixed test scene. The 16 LLW and 12 ILW drums are our test allocation. Site stock volumes give no basis for that drum ratio or for mixing the categories in an actual store. |
| [NDA Group Strategy, March 2026, waste definitions](https://www.gov.uk/government/publications/the-nda-group-strategy-effective-from-march-2026) | UK LLW has upper boundaries of **4 GBq/t alpha** and **12 GBq/t beta/gamma**. ILW exceeds the LLW boundaries, with heat generation low enough that it does not need to be taken into account in storage or disposal design. | Waste class comes from the inventory record. An external gamma dose-rate reading at Spot's pose cannot supply activity per tonne or classify a package. |
| [Sellafield Encapsulated Product Stores](https://nda.blog.gov.uk/sellafield-five-facilities-we-have-repurposed-to-support-mission-delivery/) and [2025/26 annual report](https://www.gov.uk/government/publications/sellafield-ltd-annual-report-and-accounts-202526) | Sellafield has three heavily shielded Encapsulated Product Stores for ILW. Its annual report describes the scale and complexity of the cleanup. | These are the facility and programme references for the pitch. Describe the scene as a Sellafield-inspired interim store. We have no global ranking or basis for calling the scene a replica. |
| [UK inventory, waste management and packaging](https://ukinventory.nda.gov.uk/information-hub/about-radioactive-waste/how-do-we-manage-radioactive-waste/) | Typical ILW packages include **500 L stainless steel drums** and **3 m³ stainless steel boxes**. | This supports the visual choice of a 500 L ILW drum. Our 200 L LLW drum, dimensions, aisle layout and counts are scene choices. |

Use the dated Sellafield stock table when discussing the site. The national
percentages in the original brief combine different categories and reporting
scopes and should be omitted from a description of the test hall.

## Which numbers inform decisions

| Source | What it actually says | How we use it for LLW and ILW |
| --- | --- | --- |
| [IRR17, regulation 12 and Schedule 3](https://www.legislation.gov.uk/uksi/2017/1075/pdfs/uksi_20171075_en.pdf) | The standard effective dose limit for employees and trainees aged 18 or older is **20 mSv per calendar year**, subject to the regulations' provisions. | Human exposure context for remote inspection of either category. It supplies no robot mission limit. The simulated **50 mSv** budget and **40 mSv** return trigger are project choices. |
| [HSE L121, regulation 17, paragraphs 297–298](https://www.hse.gov.uk/pubns/priced/l121.pdf) | The ACOP discusses **7.5 µSv/h averaged over a working day** for controlled-area designation. The guidance discusses **instantaneous readings above 100 µSv/h**. The regulation separately addresses likely annual exposure, including **6 mSv effective dose**. | We borrow 7.5 and 100 for the live amber marker and retreat trigger. These are **instantaneous simulation rules** for the robot in either aisle. The map does not perform a controlled-area assessment or determine waste class. |
| [IAEA SSR-6 Rev. 2, 2025 edition, paragraph 508](https://doi.org/10.61092/iaea.439y-2h8h) | Routine transport limits for **non-fixed contamination on external package surfaces** are **4 Bq/cm²** for beta/gamma and low-toxicity alpha emitters and **0.4 Bq/cm²** for other alpha emitters, averaged over **300 cm²**. | We borrow these as escalation values for a **simulated floor swab**. The demo separates beta/gamma and alpha and does not model alpha subcategories, a calibrated wipe or a 300 cm² averaging area. These values apply as demo choices near either waste class. |
| [NDA interim ILW storage guidance, August 2026, §3.1 and Table 4](https://assets.publishing.service.gov.uk/media/6ab51b7efceb6fb3a6501177/Industry_storage_guidance_Issue_1_August26.pdf) | Graded package performance and intervention triggers, with indicators tied to storage functions such as containment, shielding, and handling. Operators set thresholds appropriate to their storage system. | We use the Ideal, Tolerable and Failing structure for the inspection report and borrow it for LLW in the mixed demo. The guide supplies the rationale for monitoring. The cutoffs below are ours. |

## What we borrow from industry practice

| Source | What we take from it | How we reference it |
| --- | --- | --- |
| [Sellafield R&D review 2021/22, corrosion monitoring and acoustic detection](https://www.gov.uk/government/publications/annual-research-and-development-review-202122/annual-research-and-development-review-202122) | Monitoring air temperature, relative humidity and salt deposition, and inspecting corrosion coupons. Separate research investigated acoustic detection of deflagrations. | Supports environmental trends and a possible acoustic workstream. A coupon is a proxy for storage conditions and an acoustic event is a prompt for investigation. The source supplies no numerical alarm settings for our mixed hall. |
| [Sellafield Spot deployment](https://www.gov.uk/government/news/robotics-in-the-spot-light) and [February 2026 swab trial](https://www.gov.uk/government/news/new-robot-swabbing-technology-trialled-for-the-first-time-at-sellafield) | Spot collected laser and gamma imaging data. In a separate controlled trial, an operator used a quadruped-mounted swab to collect mock contamination. | Supports carrying separate visual, geometric and radiological sensors, and requesting a surface sample where safe. Our virtual swab is an abstraction. The trial supplies neither autonomous swab criteria nor a measurement threshold for either waste class. |
| [WIPP technical assessment, thermal-runaway model](https://www.wipp.energy.gov/special/technical_assessment_team_report.pdf) | The model estimated **about 70 days** to runaway and **about 1 °C wall-temperature rise at runaway** in the modelled drum. | A case for testing thermal observability and comparing repeat readings. This US drum and its chemistry provide no warning setpoint for Sellafield LLW or ILW packages. |
| [HSE flammable gas detector guidance](https://www.hse.gov.uk/pubns/gasdetector.pdf) | Detector response depends on gas and technology. The hydrocarbon infrared detectors described there cannot detect hydrogen. | Choose a target gas before simulating concentration and response. A hiss can prompt a check. It supplies no gas identity, concentration or LLW/ILW alarm threshold. |
| [Boston Dynamics data acquisition](https://dev.bostondynamics.com/docs/concepts/writing_services_for_data_acquisition.html), [time sync](https://dev.bostondynamics.com/docs/concepts/base_services.html) and [coordinate frames](https://dev.bostondynamics.com/docs/concepts/geometry_and_frames) | Payload data acquisition, synchronized measurements and sensor poses. | In Isaac, attach simulation time and pose to each reading. Associate findings with a drum only where there is evidence. This integration pattern applies to either category. |
| [Orbit repeat inspections](https://bostondynamics.com/blog/automated-inspections-made-simple/) and [Berkeley Lab radiation scene data fusion](https://nuclearscience.lbl.gov/research/research-programs/applied-nuclear-physics/applied-nuclear-physics-research/radiation-imaging-and-nuclear-robotics/) | Repeat views support trend review. Combining radiation measurements, pose and scene geometry can support source localisation. | Compare gamma at matched pose and standoff. Report the measured field and keep source hypotheses separate. These references motivate the workflow and supply no drum-level cutoffs. |

## Values we chose for the simulator

The executable settings are in [inspection_config.json](../sim/inspection_config.json).
The initial source strengths are in [drums.py](../sim/drums.py) and the
radiation walk override is in [spot_spill.py](../scripts/spot_spill.py).

| Setting | Current value | Basis and use |
| --- | --- | --- |
| Visual corrosion and bulge | **1% / 10%** visible rust area and **2% / 5%** diameter increase | Demo grading boundaries. Calibrate rust masks and depth repeatability before interpreting them as measured condition changes. |
| Dose relative to baseline | **+20% / +100%** grading boundaries, with a separate rule for a large decrease | Demo anomaly cutoffs. Compare at the same reference pose. Validate against ordinary repeat-run variation and changes to neighbouring sources. |
| Environment | **5–25 °C** and **over 60% RH** for flags | Demo bands. The monitoring rationale comes from Sellafield R&D. We have no basis for adopting these as operational limits for either waste category. |
| Gamma field | **1 / 20 µSv/h at 1 m** nominal source strengths for the LLW/ILW fixtures, **280** for the radiation-walk hotspot, **25** for the leak fixture, **0.2 µSv/h** background, **10%** noise, **0.5** multiplier per intervening drum and **0.1 m** distance clamp | Synthetic inputs to exercise the decisions. They do not derive from the GBq/t classification boundaries. A visible spill, loose contamination and an elevated gamma field should be evaluated separately. |
| Robot and tool | **1 m** inspection standoff, **0.5 m** minimum clearance, **0.5 m/s** cap within **2 m** of drums, **2 m** person stop, **2 s** sensor timeout, **10 s** swab delay, **0.08 m** sample-patch tolerance, **5%** swab noise | Demo policy and simulator timing. The swab-patch tolerance is a geometric shortcut. Actual arm reach requires its own check. |
| Detector and planner | **0.4–0.7** configured uncertainty band, **2 s** planner latency target | Engineering settings. Choose production detector thresholds on held-out layouts. Measure latency on the deployment GPU. |

For the pitch, use the inventory and facility sources for **why this site and
waste class**, the monitoring sources for **why these measurements**, and
the simulator config for **why Spot took this action in the demo**.
