# EAS III 조작영상 → 미니-EAS UI 스토리보드

출처: `media/operation_video.mp4` (269s, 2558×1522). 4초 주기 67프레임 + 컨택트시트 2장에서 추출.
프레임 N ≈ (N-1)×4초. 하이브리드 판독(Opus 직독 + 수치 빽빽 화면은 fable-vision 정밀 위임 예정).

## 워크플로우 전체 흐름 (영상 순서)
1. **연결** (0–40s): System Configuration → Add Gold Drive → Connection Type=Direct Access USB, Serial Port=COMx → Connect (진행 다이얼로그) → 접속.
2. **축/전기기계 설정** (44–52s): Drive Quick Tuner → Axis Configurations.
3. **모터 설정** (60–68s): Motor Settings (전류·속도·극쌍·R·L·Ke) + Drive–M1/M2/M3–Motor 결선도.
4. **피드백 설정** (70–140s): Feedback Settings + 파라미터 테이블 편집(다수 프레임, 값 빽빽).
5. **자동 튜닝** (144–176s): Automatic Tuning 마법사 — 6단계 순차 실행 + 진행바 + 로그, 종료 시 "Recommended Actions Before Leaving the Tuner" 다이얼로그.
6. **구동 + 레코딩** (176–264s): Single Axis Motion(모니터+조그) + Recorder(듀얼 차트). Enable→In Motion, 조그 구동, 레코딩 시도.

---

## PART 1 — 클론에서 재현할 UI/워크플로우 (영상에 실제로 보임)

### 공통 셸
- 타이틀 `Elmo Application Studio III`. 상단 리본(탭: File / Parameters / System Configuration / Upload And Download / Floating Tools; 툴별로 Drive Quick Tuner / Recording 등으로 바뀜). 우상단 큰 **STOP** 버튼(빨강).
- 좌하단 **모드 스위처**: System Configuration / Drive Setup and Motion / Drive Programming / Maestro Setup and Motion / Maestro Programming.
- 좌측 **툴셋 나열**(Drive Setup and Motion 모드): Quick Tuning · Expert Tuning · Motion-Single Axis · Motion-Multiple Axes · Drive Script Manager · Application Tools · Command Macros · Parameters Explorer · Parameters Comparison · Error Mapping · ECAM Table Editor · Automated Identification · Group Motion · Drive SIL · Non-Linear Current FF.
- 좌측 트리: Workspace "Default" → Drive01 (G-Twitter).

### 화면 A — System Configuration / 연결 (frame 8)
- 우측 Item Configuration 표. **General**: Target Name(Drive01) / Hardware Board Type(Unknown→접속후 GCON Rev E) / Target Version / Target Type(Gold Drive) / Target Serial Number.
- **Target Connection**: Connection Type = `Direct Access USB` 드롭다운(옵션: Offline/Direct Access UDP/EtherCAT EoE UDP/Direct Access USB/Direct Access RS232/CAN/Drive under ctrlX CORE), Serial Port USB = COMx 드롭다운.
- 리본 Device 그룹: Connect / Disconnect / Remove / Gateries. 접속 시 "Connecting… Completed" 진행 다이얼로그.

### 화면 B — Drive Quick Tuner ▸ Axis Configurations (frame 13)
- Axis and Control Configuration = `Single Axis`; Axis Identity; Electro Mechanical Configuration = `Rotary Motor Rotary Load`; Total Gear Reduction Ratio Input(Den)/Output(Num); Transmission=None.
- Feedback (Loop) Configuration 라디오: **Single Feedback** / Dual Feedback / No Feedback.
- Loop Feedback Configuration = `Rotary Feedback`; Mode of Operation = `Position [UM = 5]`.
- 체크박스 Using Brake / Unbalanced-Vertical Axis. 우측 모터 일러스트.
- 좌측 서브트리: Axis Configurations · Motor and Feedback(Motor Settings ✓, Feedback Settings ✓) · Automatic Tuning ✓.
- 리본(Drive Quick Tuner 탭): Drive Load/Drive Save/Reset/Force Upload/Force Download · Apply/Revert/Apply All/Revert All · Import/Export Page Parameters. 하단: Revert / Apply / Errors…

### 화면 C — Motor Settings (frame 17)  ★모터 파라미터
- Motor Database = `Not in Use` (+ Load…). Motor Type `CA[28]`.
- Peak Current[Arms]=**50** · Continuous Stall Current[Arms]=**15** · Maximal Motor Speed[RPM]=**3600** · Pole Pairs per Revolution=**16** · R phase-phase[ohm]=**0.119** · L phase-phase[mH]=**0.0357** · Ke[Vrms/Krpm]=**0**.
- 우측 Drive–M1/M2/M3–Motor 결선 다이어그램.

### 화면 D — Feedback Settings (frames 19–30, 값 빽빽 → fable-vision 위임 대상)
- 피드백 타입/해상도/센서 파라미터 테이블. 파란 하이라이트 행 선택·드롭다운. (정밀 값은 구현 시 위임 추출.)

### 화면 E — Automatic Tuning 마법사 (frame 38)  ★튜닝
- Tuning Status 6단계(체크 진행): **Initialization(Starting Phase) → Current Identification → Current Design → Commutation → Velocity & Position Identification → Velocity & Position Design**.
- `Run Automatic Tuning` 버튼 + `Start from Phase` 드롭다운. 진행바 + 로그창(완료 단계 나열) + Full Log 체크.
- 종료 시 다이얼로그 "Recommended Actions Before Leaving the Tuner"(권장조치 체크리스트).

### 화면 F — Single Axis Motion + Recorder (frames 45–67)  ★대시보드/구동 (핵심)
- **Status - Motion**: Position[cnt] · Pos.Error[cnt] · Velocity[cnt/sec] · Active Current[Amp] · Status(Motor Disabled↔In Motion) · Program Status · 큰 상태등(빨강=Disabled / 초록=Enabled).
- **Status – IO and Safety**: Digital In Bit 1–6 / Digital In Func(GP×6) / Digital In Stat(초록점) / Safety STO1·STO2·ERR(점).
- **Motion**: Drive Mode(Position[UM=5]) · Enable↔Disable 토글(빨강→초록). 탭: Position / Velocity / Current / Sine Reference / Homing.
- Motion Parameters(Velocity 탭): Acc/Dec/Stop Dec [cnt/sec²]=1E+6 · Smooth[msec] · Speed[cnt/sec]. **Jogging** ◀ ▶ + Run Held 체크 + Stop.
- **Terminal** 패널: `Drive01>` 프롬프트 + Commands 목록 + "Press Ctrl+h for Command Reference menu".
- **Recorder**(우측): 리본 Recording 탭(Resolution 100µs · Record Time · Buffer Size 0.2s · Single/Rollover · Trigger · Signals · Single/Normal/Auto/Interval · Start/Immediate/Upload/Stop · Settings Preset · Multi Drive Recording). Chart #1 / Chart #2 시간축 플롯(Y −40..40, X 0..10s).
- 관측된 라이브 값 예: Disabled 시 Pos=19785 Vel=499; Enabled/In Motion 시 Pos=12124061 Vel=3932674 Active Current=0.124A (조그 구동 중).

---

## PART 2 — 영상으로 알 수 없는 엔진/물리 (도메인·.NET 라이브러리·Command Reference로 채움)

| 항목 | 무엇이 숨어있나 | 어디서 채우나 |
|---|---|---|
| **자동 튜닝 알고리즘** | Current ID/Design·Commutation·Vel/Pos ID/Design은 **드라이브 펌웨어 내부**가 계산. EAS는 명령으로 트리거·모니터만. | Command Reference의 튜닝 트리거 명령 시퀀스 + .NET `IDriveCommunication`. 클론은 재구현이 아니라 **드라이브 내장 튜닝을 명령으로 구동**. |
| **단위계(UM)** | Position[cnt]·Velocity[cnt/sec]의 cnt↔기계각 변환(엔코더 해상도×극쌍), `UM=5`(Position 유닛모드)의 의미. | Command Reference(UM/PX/VX 등) + 모터/피드백 파라미터. |
| **모터 파라미터 의미** | R·L·Ke·극쌍이 정류·전류루프 설계에 어떻게 들어가나. | 모터제어 도메인([[motor-controller-designer]]) + 튜닝 문서. |
| **레코딩 신호 정의** | Chart#1/#2가 무슨 신호를 그리나, 해상도·트리거·버퍼 의미. | .NET `IDriveRecording` + personality의 recording signal list. |
| **Safety(STO1/STO2/ERR)** | 상태 비트의 물리적 의미·안전 로직. | Command Reference 상태 레지스터(SR) + 안전 매뉴얼. |
| **명령 니모닉 매핑** | Enable=MO=1, 조그=JV+BG, 상태=SR/MF 등 각 버튼→명령. | Command Reference(정독 필요). |

---

## 검증 흐름
UI는 이 스토리보드로 재현하되, **정확성 검증은 영상이 아니라 실드라이브 실측**으로 — `elmo_link`로 같은 명령을 실제 COM3 드라이브에 보내 EAS와 동일한 응답/거동이 나오는지 `feedback-runner` 루프로 대조(예: VR/상태/파라미터 읽기는 이미 GREEN). 모션 명령은 안전절차 하에서만.

## 다음 (구현 순서 제안)
1. SDD 셸 이식 → **화면 A(연결) + 화면 F(Single Axis Motion, 읽기전용 텔레메트리)** 부터.
2. Command Reference 정독(fable-reader용 텍스트 추출) → 버튼→명령 매핑 표 완성.
3. 화면 C/E(모터설정·튜닝) → 화면 D(피드백, 값 fable-vision 위임).
