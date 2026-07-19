# EAS III UI Layout Blueprint — from recorded keyframes

> Purpose: developer-ready spec to rebuild EAS III **layout structure** (not
> theme) in the AngryYJH PyQt6 app. Extracted by two parallel fable-vision
> passes over `media/keyframes/` (67 main frames) and `media/fb_keyframes/`
> (106 Feedback frames). Values are transcribed from the frames; items marked
> **[ambiguous]** or "미관측" were not confirmed and must not be invented.
> Live EAS is only needed for the few never-opened surfaces (Advanced band,
> Expert Tuning, Recorder Signals/Trigger dialogs, Add-Device icon labels).

---

## 0. Common application shell (all screens)

Vertical stack, top to bottom:

1. **Title bar**: app icon (left) — centered title `Elmo Application Studio III` — right: minimize / restore / close.
2. **Menu/tab row** (ribbon tab strip). Context dependent:
   - System Configuration mode: `File | Parameters | System Configuration | Upload And Download | Floating Tools`
   - Quick Tuning mode: `File | Parameters | Drive Quick Tuner | Floating Tools`
   - Motion + Recorder mode: `File | Parameters | Tools | Views | Floating Tools | Recording | View Design` — magenta contextual group label **"Recorder"** above the `Recording`/`View Design` pair.
3. **Ribbon** (~110 px): groups of large icon buttons, each group with a caption underneath (`Device`, `Deployment`, `Import & Export`, ...). Far right of the ribbon on every screen: a large round red **STOP** button. Above it: ribbon-collapse chevron `^` and `?` help.
4. **Body**: left dock panel (~250 px) + main area (varies per screen).
5. **Status bar** (bottom, 1 line): left = lightbulb icon + context text (`Feedback Settings Page`, `Current Toolset: Motion - Single Axis`, ...); right = two small window icons + progress strip.

### Left dock panel (same structure in all workspaces)
- **Panel header**: workspace name + `<<` collapse chevron (`System Configuration <<` / `Drive Setup and Motion <<`).
- **Workspace tree**: `▾ 🗀 Workspace "Default"` → child `Drive01 (G-Twitter)` (red x-icon before connection).
- **Tool list** (only in Drive Setup and Motion workspace; 16px icon + label; selected item steel-blue highlight):
  1. Quick Tuning  2. Expert Tuning  3. Motion - Single Axis  4. Motion - Multiple Axes
  5. Drive Script Manager  6. Application Tools  7. Command Macros  8. Parameters Explorer
  9. Parameters Comparison  10. Error Mapping  11. ECAM Table Editor  12. Automated Identification
  13. Group Motion  14. Drive SIL  15. Non-Linear Current FF
- **Bottom mode switcher** (5 stacked full-width Outlook-style bars, active highlighted):
  1. System Configuration  2. Drive Setup and Motion  3. Drive Programming
  4. Maestro Setup and Motion  5. Maestro Programming
  - plus a thin layered-panels icon strip at the very bottom.

### Quick Tuner wizard chrome (screens 1–4)
- Ribbon groups: **Device** = Drive Load, Drive Save, Reset, Force Upload, Force Download · **Deployment** = Apply, Apply All, Revert, Revert All (small 2×2 with check/undo icons) · **Import & Export** = Import Page Parameters, Export Page Parameters. (Motor Settings adds **Motor DB** = Load..., Edit...)
- **Page header strip**: blue icon + `Drive Quick Tuner` | breadcrumb of current page | far right `Drive01`.
- **Center page-tree** (own ~350 px column between left dock and content):
  - `● Axis Configurations`
  - `− ● Motor and Feedback` → `✓ Motor Settings`, `✓ Feedback Settings`
  - `✓ Automatic Tuning`
  (green check = completed; selected = blue row; invalid page = red warning triangle icon)
  - Bottom of column: `<<` and `>>` wizard nav buttons.
- **Bottom-right action bar** (all Quick Tuner pages): `Revert | Apply (blue when armed) | Errors...` (Errors turns red when invalid params exist).

---

## 1. Feedback Settings (Drive Quick Tuner)

Main content = **two columns**.

**Left column — "Feedback on Motor"**
- Header row: label `Feedback on Motor` — right-aligned `Position:` + numeric read-only field.
- **Sensor selector dropdown** (full width): e.g. `Serial Absolute - EnDat 2.2 designation 22, Port A`. Open list (each entry has a small type icon; list is scrollable = may exceed captured items):
  Pulse and Direction Port A/B · Quad Exclusive 1 Port A · Resolver Port B · Serial - Panasonic Incremental Port A · Serial Absolute BiSS General / BiSS / EnDat 2.1 desig 22 / EnDat 2.2 desig 22 / Hiperface Port A&B / IAI / Kawasaki / Mitsubishi / Panasonic / Sanyo·Nikon / SSI / Tamagawa (all Port A) · Serial Exclusive #3 (red icon) · Virtual Absolute - Gurley Port B.
- **Property grid** (2 cols name|value; scrollable; section headers have `−` collapse boxes), EnDat 2.2:
  - `Feedback Control Function` : `Position + Velocity + Commutation` (read-only)
  - `Use Digital Halls` : `No` (dropdown)
  - **Section: Sensor Parameters**
    - `Direction` : `Non Invert` (dropdown: Non Invert / Invert)
    - `Clock Frequency (MHz)` : `5.000` (dropdown)
    - `Input Glitch Filter (nanosecond)` : `120` (dropdown)
    - `Serial Data Polling` : `Every TS` (dropdown: Every 2 TS / Every TS)
    - `Error Bitwise Mask` : `0x0` (text)
    - `Read EnDat External Temperature` : `No` (dropdown)
    - `Communication Time (microsecond)` : `60` (text)
    - `Absolute Position Offset` : `0` (text)
    - `Encoder Maintenance` : **[Open] button** (right-aligned in value cell)
    - `Velocity FIR Filter Window` : `Disabled` (dropdown: Disabled,2..8)
  - **Section: Serial Encoder Frame** (header has a small frame/∞ icon button)
    - `HW Sensor Resolution (Bits)` : `19` (read-only text)
    - `SW Sensor Resolution (Bits)` : `16` (dropdown)
    - `Rotary Multi-turn Resolution` : `16` (text)
    - `High Bits Mask (Bits)` : `0` (dropdown 0..8)
  - **Section: Resolution**
    - `counts/revolution` : `65536` (read-only)
  - **"Advanced" collapsible band** at bottom, full width, double-chevron toggle at far right — never expanded in captures (contents unknown).

**Right column — "Feedback on Load"**: header `Feedback on Load` + `Position:` empty; sensor dropdown `None`; empty parameter area (populates only when a load sensor is chosen).

**Encoder Maintenance dialog** (modal): title `Encoder Maintenance` + X; body vertical stack: `Set Datum Shift TW[18]` button → input (`0`) → `Reset Multi-turn TW[19]` button → `Reset Errors TW[20]` button.

Row set is **sensor-dependent** (rebuild dynamically): EnDat 2.1 uses `Error Bit Mask` dropdown, no external-temp row, Clock 2.500 / Glitch 240; BiSS adds Resolution Type/BiSS Mode/Warning Report + Position LSB/Error Bit Number/Protocol Total Bits; Hiperface adds Multiplication Factor/serial-status-polling/Glitch Filter + cycles/rev 16384 & counts/rev 16777216; SSI adds Sensor Data Presentation/First Clock Delay; etc.

---

## 2. Motor Settings (Drive Quick Tuner)

Single-column form, label left / control right (full-width controls):
1. `Motor Database` : field `Not in Use` + `Load...` button (same row)
2. `Motor Type CA[28]` : dropdown (Rotary Brush / Rotary Brushless (3 Phase))
3. `Peak Current [Arms]` : text **[ambiguous, ~50]**
4. `Continuous Stall Current [Arms]` : text **[ambiguous, ~15]**
5. `Maximal Motor Speed [RPM]` : `3600`
6. `Pole Pairs per Revolution` : `16`
7. `R - resistance [ohm] phase to phase` : `0.119`
8. `L - inductance [mH] phase to phase` : `0.0357`
9. `Ke - back emf constant [Vrms/Krpm]` : `0`
10. Framed **illustration panel**: blue "Drive" box with M1/M2/M3 lines to a "Motor" circle (3-phase wiring).
Ribbon adds group **Motor DB**: `Load...`, `Edit...`.

---

## 3. Axis Configurations (Drive Quick Tuner)

Form (left ~55% labels+controls, right ~45% illustration):
1. `Axis and Control Configuration` : dropdown `Single Axis`
2. (indent) `Axis Identity` : dropdown (empty)
3. `Electro Mechanical Configuration` : dropdown `Rotary Motor Rotary Load`
4. (indent) `Total Gear Reduction Ratio` : `Input (Den)` field + right `Output (Num)` field (two fields, one row)
5. (indent) `Transmission` : `None` (disabled)
6. `Feedback (Loop) Configuration` : radios `◉ Single Feedback | ○ Dual Feedback | ○ No Feedback`
7. `Loop Feedback Configuration` : dropdown `Rotary Feedback` (grayed)
8. `Mode of Operation` : dropdown `Position [UM = 5]`
9. `Using Brake` : checkbox (unchecked)
10. `Unbalanced / Vertical Axis` : checkbox (unchecked)
11. Right: large framed servo-motor illustration.

---

## 4. Automatic Tuning (Drive Quick Tuner)

1. **Section "Tuning Status"**: vertical list of 6 phases, each with status marker (green ✓ done / blue ● pending / bold running):
   Initialization (Starting Phase) · Current Identification · Current Design · Commutation · Velocity & Position Identification · Velocity & Position Design
2. **Section "Tuning"**: `Run Automatic Tuning` button · `Start from Phase:` + dropdown (`Initialization`) · far right `☐ Full Log`.
3. **`Tuning Stage: <current phase>`** heading.
4. Large bordered **log panel**: completed phases as underlined hyperlink-style lines.
5. Full-width **progress bar** with `Cancel` at its right end.
6. Bottom action bar `Revert | Apply | Errors...`.

**"Tuning Summary" dialog** (modal at completion): heading `Recommended Actions Before Leaving the Tuner`; `☑ Save Parameters in Drive (SV)`; `☑ Upload Parameters from Drive` + path + `...`; `☐ Save Design Plants` + path + `...`; `Import to DB...`; log box; progress bar; buttons `Apply | Close`.

---

## 5. Motion - Single Axis + Recorder (toolset workspace)

3-pane workspace under the **Recording** ribbon.

### Ribbon ("Recording" tab, contextual group "Recorder")
- **Target Device**: `Target` dropdown (`Drive01`), `Filter` dropdown (`All Devices`), `☐ Lock Target`.
- **File**: Open, Save, Save As.
- **Recording Time Settings**: `Resolution` (`100 µs`), `Record Time` (`0.164 s`), `Buffer Size` (`0.2 s`), radios `○ Single / ◉ Rollover`.
- **Options**: `◉ Single / ○ Interval`; `◉ Normal / ○ Auto`; `Trigger...`, `Signals...`, `Interval...`.
- **Activation**: `Start` (yellow ▶), `Immediate` (orange ▶), `Upload` (blue ▲), `Stop` (gray ■, disabled when idle).
- **Settings**: `Load...`, `Save...`, `Settings Preset ▾`.
- **Multi Drive Recording**: `☐ Multi Drive Recording`, `Manage Drives...`, empty list, trash icons.

### Center-left pane — "Single Axis Motion"
1. **Status - Motion** (2-col grid): `Position [cnt]` | `Pos.Error [cnt]` | `Enabled/Disabled`; `Velocity [cnt/sec]` | `Status:` (In Motion / Stand Still & In Target / Motor Disabled) | round LED; `Active Current [Amp]` | `Program Status: No Program`; `Last Fault:` (empty).
2. **Status – IO and Safety**: left table `Digital In Bit`(1..6)/`Func`(GP×6)/`Stat`(6 LEDs); right `Safety` STO1/STO2/ERR LEDs; below `Digital Out Stat` + 4 checkboxes.
3. **Motion**: `Drive Mode:` dropdown `Position [UM =5]` · `0` chip · **Disable/Enable toggle** with embedded LED (green `Disable` armed / red `Enable` off). Tab strip `Position | Velocity | Current | Sine Reference | Homing`. `Motion Parameters`: Acc/Dec/Stop Dec `1E+6`, Smooth `0`, Speed `4444444`. `Jogging` sub-panel: `◀`/`▶` (orange latched), `☐ Run Held`, red `Stop`.
4. **Terminal panel**: `:\> Terminal` + toolbar + `Drive01`; left console prompt `Drive01>`; right `Commands- Untitled`; footer `Command Reference` + `Press Ctrl+h ...`.

### Right pane — "Recorder"
Header: chart icon + `Recorder` + round toolbar (green/orange play, red stop, signals-probe, fit) + `Untitled` + `Drive01`.
- **Chart #1** and **Chart #2** stacked; each: title top-left, per-chart icons top-right (settings/info/close), empty grid, Y −40..40, X 0..10 `Time (sec)`.
- Chart right-click menu order: Change plot area color / Hide Y Axis Label / Display Y Axis in Hex / Connect Time Base (Xch) Master / Slave / Connect Rider / Chart Editor / — / Zoom in XY / X / Y / to Markers / Manual Zoom / — / Zoom Out / Unzoom / Unzoom All / — / Move Left / Right / — / Single Rider / Add Cursor / Add Rider.

---

## 6. System Configuration workspace

### Ribbon (`System Configuration` tab)
- **Device**: `Connect` (green), `Disconnect` (gray), `Remove` (red X), two `Gateways` small buttons.
- **Workspace File**: `Save`, `Open`, 3 small icons **[ambiguous]**, `Zip & Send`.
- **Add Device**: two rows of ~7 small device icons **[ambiguous labels]**.

### Main area — "Item Configuration" property grid
- Workspace selected: **General** → `Workspace Name` : `Default`; workspace file path row.
- Drive selected: **General** → `Target Name` `Drive01`, `Hardware Board Type`, `Target Version`, `Target Type` `Gold Drive`, `Target Serial Number`; **Target Connection** → `Connection Type` dropdown `Direct Access USB`, `Serial Port USB` dropdown `COM#`.
  (Live capture 2026-07-20: HW `GCON Revision E`, Version `Twitter 01.01.16.00 08Mar2020B01G`, PAL `90.1 (V1)`, serial `22033647`, `Direct Access USB` / `COM3`.)

### Workspace tree context menu order
Open Workspace Folder / Collapse All / Expand All / — / New / Open / Save / Save as... / Clear / — / Add Gold Drive / Add SimplIQ / Add Platinum / Add Titanium / Add Gold Maestro EtherCAT / CAN / Platinum Maestro EtherCAT / CAN / Titanium Maestro EtherCAT / CAN.

---

## Not verifiable from these frames (do not invent when rebuilding)
- Feedback **Advanced** section contents (never expanded).
- Small **Add Device** ribbon icon labels; the 3 small Workspace File icons.
- `Peak Current` / `Continuous Stall Current` values (occluded).
- **Expert Tuning**, Parameters Explorer, other left-list tools (never opened).
- Recorder `Signals...` / `Trigger...` dialogs (never opened).
