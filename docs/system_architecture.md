# How the inspection system fits together

The robot discovers the world through onboard sensors. Cosmos Reason 2 chooses
every action from a list the safety layer allows. The scenario script only
authors the world, for example which drum is heating. Dashed boxes are not
built yet.

```mermaid
flowchart LR
    subgraph Laptop["Laptop (repo checkout)"]
        CLI["tools/hot_hall.py<br/>up · run · down"]
        REQ["scripts/hot/*.py<br/>sensing · scenario_lib · agent<br/>+ scenario (world setup only)"]
        RES["out/hot/&lt;run&gt;/<br/>video.mp4 · report.md · report.json<br/>decisions.json · log.jsonl"]
    end

    subgraph Modal["Modal"]
        subgraph Worker["Hot hall worker · L40S · stays up 4 h"]
            RELAY["serve(): request queue → Isaac,<br/>frames → mp4, results back"]
            subgraph Isaac["Isaac Sim 6.2 (sim/hot_server.py)"]
                WORLD["Hall stage via load_layout()<br/>28 drums · labels · ID plates<br/>authored faults: hot drum, H2 vent, contamination"]
                SPOT["Spot<br/>learned locomotion policy (physics)"]
                subgraph Sensors["Onboard sensors"]
                    LIDAR["RTX LiDAR<br/>Ouster OS1-32"]
                    IMU["Physics IMU"]
                    ENC["Joint encoders"]
                    RGBD["Onboard RGB-D"]
                    PTZ["PTZ zoom camera"]
                    MODELS["Sensor models<br/>LWIR thermal · H2 · mic · gamma ·<br/>temp/RH · swab"]
                end
                subgraph Sensing["Perception and navigation (sensing.py)"]
                    NAV["Leg odometry + gyro<br/>→ ICP scan-match to store map"]
                    THERM["Thermal hotspot → depth →<br/>drum via map"]
                    HISS["Hiss detector<br/>(band energy over mic floor)"]
                    CORR["Corrosion<br/>segmentation stand-in"]
                end
                AGENT["agent.py<br/>findings → safety layer → offered actions"]
                EXEC["Action executor<br/>route · face · swab · retreat"]
                REPORT["Report<br/>criteria.py grades + summary"]
            end
        end
        subgraph Cosmos["Cosmos service · L40S (tools/cosmos_vllm.py)"]
            VLLM["vLLM OpenAI API<br/>nvidia/Cosmos-Reason2-2B"]
        end
        VOL[("Volumes<br/>HF weights · vLLM cache")]
        SEC[("Secrets<br/>huggingface · cosmos-vllm")]
    end

    HF[("Hugging Face Hub")]
    GH[("GitHub repo")]
    YOLO["YOLO corrosion detector<br/>(teammates, pending)"]

    CLI -- "script source" --> RELAY
    REQ --> CLI
    RELAY -- "exec on live stage" --> AGENT
    WORLD --> Sensors
    SPOT --> Sensors
    LIDAR --> NAV
    IMU --> NAV
    ENC --> NAV
    RGBD --> THERM
    MODELS --> THERM
    MODELS --> HISS
    RGBD --> CORR
    NAV --> AGENT
    THERM --> AGENT
    HISS --> AGENT
    CORR --> AGENT
    MODELS -- "gamma, H2, temp/RH, swab results" --> AGENT
    AGENT -- "image + readings + findings + allowed actions" --> VLLM
    PTZ -- "plate crop" --> VLLM
    VLLM -- "action + reason · plate ID · summary" --> AGENT
    AGENT --> EXEC
    EXEC -- "velocity commands" --> SPOT
    AGENT --> REPORT
    REPORT -- "summary request" --> VLLM
    RELAY -- "mp4 + report" --> RES
    HF --> VOL
    VOL --> VLLM
    SEC -.-> VLLM
    SEC -.-> RELAY
    YOLO -.-> CORR
    Laptop -- "git push" --> GH
```

## What each part is

| Part | Real or modelled |
| --- | --- |
| Hall, drums, Spot locomotion, RGB-D, PTZ, LiDAR, IMU, encoders | Isaac Sim physics and RTX rendering |
| Gamma, temperature/RH, H2, microphone, LWIR thermal, swab | Sensor models of authored sources. Isaac has no native sensor for these |
| Navigation | Real estimator on sensor data. Ground truth is used only for the error shown in the overlay |
| Thermal, hiss and ID detection | Real algorithms on sensor output. IDs are read by Cosmos from PTZ crops |
| Corrosion detection | Simulator segmentation, until the YOLO detector lands |
| Decisions | Cosmos Reason 2 over safety-checked actions. A rules baseline takes over if Cosmos is unreachable, and that is labelled in the video |
| Thresholds | `sim/inspection_config.json`. Sources and limits are in [inspection_source_register.md](inspection_source_register.md). H2 has no alarm setpoint |

`tools/run_hall.py` jobs, such as `tools/run_plates.py`, render
texture-accurate stills with the same container recipe as the hot worker.
Renders from `isaac_sim_modal.py` currently draw one texture on every surface.
