# Elmo Drive Recording — grounded API (for autotune R/L capture)

Purpose: the current-loop autotune must capture voltage & current at 400–800 Hz during
sinusoidal excitation. Serial polling is too slow → use the drive's high-speed recorder.

Two paths were grounded. **Use the .NET path (primary).** The 2-letter path is documented
here only for context / fallback.

Provenance: `.NET reflection` = live offline reflection of `ElmoMotionControlComponents.Drive.EASComponents.dll`
(no hardware). `CR` = Gold Line Command Reference MAN-G-CR 1.406 (`docs/command-reference.txt`).
`RN` = Drive .NET Library 1.0.0.8 Release Notes PDF (fitz). `FW` = firmware-release-notes.txt.
`EX` = official Drive .NET 1.0.0.8 code examples archive, SHA-256
`0E12B2B332D35E26DD5B81797E442D568BA966FE752930B849C19E09F7379222`, member
`Code Examples/DriveDotNetRecording/RecordingOperator.cs`.

---

## PRIMARY — .NET Drive Recording API (returns physical doubles; no hex/BH parsing)

**Namespaces (reflection-confirmed — get these wrong and it AttributeErrors live):**
`…EASComponents.Recording.{RecordingSetup, TriggerSetup, TriggerSetupType, TriggerSlope,
TriggerMode, RecordingStatus, RecordingData, DriveRecording}` ·
`…EASComponents.Personality.{RecordingSignalSetup, DrivePersonalityModel}` ·
`…EASComponents.{IDriveRecording, IDriveCommunication}` (root).

Flow (from RN Chapter 4 + reflection):

1. **Personality (signal list source).** `IDriveCommunication.CreatePersonalityModel(string personalityPath, out IDriveErrorObject err)`.
   Populates `comm.PersonalityModel` (`DrivePersonalityModel`). RN: "the library can upload the
   personality data from the drive and save it into an XML file … obtaining the list of recording
   signals." The implemented ladder is populated communication model → identity-matched cached XML →
   upload from the connected drive and parse. A pre-populated communication-model catalog may supply
   signals, but it has no XML-version comparison and therefore records
   `firmware_personality_match=false`. A cached XML is accepted only when the normalized firmware
   portion of `<version>` is non-empty and exactly equals normalized live `VR` (case-insensitive), and
   its integer `Pal:` value equals live `VP`; otherwise a current-session upload is required.

2. **Signal list.** `comm.PersonalityModel.SignalsMetaData` : `Dictionary<Int32, RecordingSignalSetup>`.
   - `RecordingSignalSetup` props (reflection): `Int32 SignalIndex`, `Int32 SignalType`,
     `Int32 SignalSize`, `String Name`, `String CategoryName`, `String Classification`. (ctor()).
   - Key = signal index. **This is what `elmo_link.recorder_signals()` returns** (list of Names, or the
     RecordingSignalSetup objects). Autotune `_resolve_signals` regex-matches Name for
     voltage(not bus)/`IQ|active current`/`current command`.
   - Expected names (FW/CR): "Active Current" (A), "Bus Voltage" (excluded), "Total Current Command".
     **LIVE-UNKNOWN (U3 core)**: whether a non-bus **voltage-command** signal (Vq/Vd) exists in the list —
     there is NO 2-letter command for it, so the recorder personality is the only source. Dump live.

3. **Record.** `IDriveRecording rec = comm.GetRecordingObject()` then:
   - `RecordingSetup setup = new RecordingSetup()` (reflection props):
     `TriggerSetup TriggerSetup`, `Int32 TimeResolution`, `Double SamplingTime`,
     `Double RecordingDuration`, `Int32 RecordingLength`, `List<RecordingSignalSetup> SignalData`.
   - `TriggerSetup` props: `RecordingSignalSetup TriggerSignal`, `TriggerSetupType SetupType`,
     `TriggerSlope SlopeType`, `Double Low`, `Double High`, `Int32 Delay`, `TriggerMode TriggerMode`.
   - Enums: `TriggerSetupType = {Immediate, Begin, Digital, Analog, Combination}`,
     `TriggerSlope = {Positive, Negative, Window}`, `TriggerMode = {Manual, Normal}`.
     → **immediate capture: SetupType = Immediate**.
   - `SignalData` = the RecordingSignalSetup instances (from SignalsMetaData) for the signals to record.
   - `bool ConfigureRecording(RecordingSetup)`, `bool StartRecording()`.
   - Before the vendor configure/start calls, `elmo_link` stores a provisional pending handle. If an
     exception is returned after crossing `StartRecording()`, the UI reports
     `START_OWNERSHIP_UNKNOWN` and keeps recorder ownership fail-closed; only Recorder Stop/recovery
     is allowed because the drive may already be armed.
4. **Monitor.** poll `RecordingStatus GetRecordingStatus()` : enum `{ROff, RWait, REnd, RProgress}`.
   ROff=error/cancel, RWait=awaiting trigger, REnd=done, RProgress=running. `void StopRecorder()` requests
   abort, but a no-exception return is not success evidence: ownership is released only after the same
   recorder reads back `ROff` or `REnd`.
5. **Upload.** `RecordingData UploadRecordingData()` → `RecordingData.Data` : `Dictionary<Int32, Double[]>`
   (value = physical double array). **No factor/offset/hex — already physical.**
   - Recorder Stop cannot preempt an `UploadRecordingData()` vendor call already in progress. When
     Stop wins that race, returned host data is discarded, no late `COMPLETED`/data event is
     published, and the terminal UI state remains `CANCELLED`.
   - **LIVE-CONFIRMED (2026-07-13, autotune run #4): Data keys are POSITIONAL 0..N-1 in
     SignalData request order — NOT SignalIndex.** (6-signal request returned keys [0..5];
     'A Voltage' has SignalIndex 19 → SignalIndex lookup fails. `elmo_link._map_upload_data`
     maps positionally and raises IOError when the key set ≠ {0..N-1}.)
   - **DOCUMENTED (EX)**: the example assigns `SamplingTime=TS` in µs and
     `TimeResolution=4`, explicitly describing the gap as `4 × TS`. Therefore
     `dt_s = TimeResolution × SamplingTime_us × 1e-6`.
   - Before upload, the implementation reads back `SamplingTime`, `TimeResolution`, and
     `RecordingLength` from the configured setup object. It fails closed unless all three are
     finite/positive as applicable and exactly agree with the stored configured TS, integer
     resolution, and requested sample count (`SamplingTime` uses a tight numeric tolerance).

Interface: `IDriveCommunication.GetRecordingObject() -> IDriveRecording`,
`CreatePersonalityModel(String, IDriveErrorObject&) -> Boolean`, `PersonalityModel {get;set;}`.

### Recovery and capture provenance

- If disconnect cleanup cannot confirm terminal `ROff`/`REnd` after `StopRecorder()`, a v2 record is
  atomically latched in `.omc/state/recorder_unknown.json`, keyed by COM port and opaque hashed drive
  identity. Recovery can clear only the exact matching record after a live Stop plus terminal-status
  readback; a different drive on the same COM cannot clear it. Missing or legacy-unproven identity
  stays fail-closed as `RECOVERY_REQUIRED_UNKNOWN`.
- CSV export creates a `.meta.json` sidecar with a capture UUID, start-attempt/completion UTC times,
  target and firmware/PAL/boot fields, requested/actual timing and sample counts, and CSV SHA-256.
  Its capture manifest also records SHA-256 values for `main.py`, `elmo_link.py`,
  `recorder_control.py`, the loaded Drive .NET DLL, Personality XML and canonical signal catalog;
  Personality source/cache-match evidence; and an opaque SHA-256 identity derived from `SN[4]`
  without exporting the raw serial token.

---

## FALLBACK — 2-letter recording (RC/RG/RL/RP/RR + BH). Do NOT parse BH unless forced.

From CR (fable-reader). Recording itself works via ASCII; **but the signal name↔index list is NOT in
CR** (personality only; the `LS` command is undocumented). And our provisional `_parse_bh` was WRONG:

- `RC=<bitfield>` bit N-1 = signal mapped by `RV[N]` (max 16). RC/RG/RL/RP writes invalidate prior data.
- `RG=<1..65535>` sampling divisor (RG=1 → sample time = WS[29], default 2×TS).
- `RL=<1..16384>` length; per-signal = 16384/nsignals (4 signals → 4096, matches RECORDER_MAX_RL).
- `RP[0]` time quantum: **0=2×TS, 1=TS**. `RP[3]` trigger: **0=Immediate**. RP[8]/[9]=upload window (0,0=all).
- `RR=2` immediate start; read `RR`: −1=no data, **0=done/ready**, 1..3=awaiting trigger. `RR=0` kills.
- `RV[N]=X` maps static var X → RC bit N-1 (non-volatile; EAS may have reprogrammed → read RV[1..16] live).
- **BH=<bitfield>** (NOT an index — `BH=(1<<bit)`; `BH=idx` is a bug). Upload = **hex-binary** text
  (2 hex chars/byte): 20-byte header [type(0-1) 0=int/1=float, size(2-3) 2/4/8, len(4-7),
  sampling(8-11), **factor float(12-19)**], then data; physical = raw × factor (**no offset**). Endian/float
  format/framing = live-unknown. `BS[N]` = documented per-sample fallback (slow).

Confirmed bugs in current `autotune_current.py` (superseded by using the .NET path):
- B1: `BH=%d % idx` → must be bitfield. B2: `_parse_bh` text format wrong. R2: add `RR=0` kill before setup.

---

## Implementation decision

Wrap the .NET recorder in `elmo_link`:
- `recorder_signals()` → names from `PersonalityModel.SignalsMetaData` (build model once on connect).
- `record(signal_indices, length, time_resolution) -> {index_or_name: np.ndarray, "dt": float}` via
  GetRecordingObject→Configure→Start→poll REnd→UploadRecordingData.

Then autotune `_record`/`_list_recorder_signals` call these link methods (drop the raw RC/RG/BH path
and its B1/B2 bugs). Sim tests mock `record()` with the same dict shape. Live bring-up confirms the
remaining LIVE-UNKNOWNs (voltage signal existence and target-specific vendor behavior not covered by
the exact configure/upload readback gates).
