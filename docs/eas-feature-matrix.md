# EAS III 기능 구현 매트릭스

> **ACTIVE-SCOPE NOTE — 2026-07-17:** 이 매트릭스는 전체 기능 inventory/backlog다. 현재 실행 범위,
> 중단 지점과 다음 순서는 [`current-scope-handoff.md`](current-scope-handoff.md)를 우선한다.

Recorder 상단 리본의 항목별 쉬운 설명과 구현/잠금 상태는
[`eas-recorder-ribbon.md`](eas-recorder-ribbon.md)를 기준으로 한다. 로컬 firmware·manual
자료의 버전/해시/적용 범위는 [`local-elmo-artifact-audit.md`](local-elmo-artifact-audit.md)에 기록한다.

기준일: 2026-07-18<br>
대상: 이 저장소의 `AngryYJH Control`과 현재 Gold Twitter 드라이브 1축

이 문서는 “EAS를 전부 복제했다”는 선언이 아니라, 각 기능의 근거와 위험도를 분리하는
개발 기준표다. 다른 드라이브·펌웨어·피드백 센서에서 같은 결과가 난다고 가정하지 않는다.

## 판정 기준

- `LIVE`: 현재 장비에서 명령/되읽기 또는 실구동 결과가 관측된 기능.
- `OFFLINE`: 테스트·시뮬레이터·DLL reflection까지만 통과한 기능.
- `MODEL`: 명령 참조, 펌웨어 노트, EAS 화면 관측으로 설계했지만 해당 조합의 실기 검증이 부족한 기능.
- `NEED-DATA`: 명령 ID, 단위, 펌웨어 지원 여부 또는 안전 오라클이 부족한 기능.
- `UNSUPPORTED`: 공장 전용·라이선스 보호·서명 우회 또는 안전 인터록 우회 없이는 제공하지 않을 기능.

`LIVE`도 필드 안전 인증을 뜻하지 않는다. 소프트웨어 STOP은 독립 STO/E-stop을 대신하지 않는다.

## 2026-07-18 EAS 미연결 UI 관찰 기준선

`OBSERVED`: 설치된 EAS III를 실행한 뒤 target tree가
`Drive01 (G-Twitter 140A / 100V) (Disconnected)`인 상태에서 아래 화면만 열었다.
Connect, Enable, Run Automatic Tuning, Apply, Save, Reset, Force Upload/Download,
PTP 또는 Recorder activation은 누르지 않았다. 이 target 이름/형식은 저장된 EAS workspace 표시이며
실제 board readback이나 Gold 계열 호환성 증거가 아니다. 직접 serial/device identity는 문서에 기록하지 않는다.

| EAS 화면 | 미연결 상태에서 직접 관찰한 구조 | 현재 AngryYJH 대응 / 차이 |
|---|---|---|
| Quick Tuning | `Axis Configurations`; `Motor and Feedback → Motor Settings / Feedback Settings`; `Automatic Tuning` | Motor/Feedback 읽기·preview와 Quick guided flow가 대응한다. EAS page import/export·wizard Apply/Revert parity는 미구현 |
| Quick Automatic Tuning | `Initialization (Starting Phase) → Current Identification → Current Design → Commutation → Velocity & Position Identification → Velocity & Position Design`; Start-from-phase, Full Log, Run/Cancel | 6단계 명칭/순서는 현재 Quick UI와 일치. EAS 실행 버튼은 Disconnected에서 disabled였고, 이 관찰은 알고리즘/수치 동등성을 증명하지 않음 |
| Expert Tuning | Axis; Motor/Feedback; User Units; Limits/Protections; Application Settings; Current; Commutation; Velocity/Position; Summary | v2는 Current P1 → Velocity/Position P2의 두 단계 순수 offline Candidate Lab과 공통 P1/commutation/P2/Verify를 제공. candidate와 installed readback은 분리하며 아래 세부 차이는 backlog |
| Expert 세부 | `Current Limits`; `Motion Limits and Modulo`; `Protections`; `Settling Window`; `Inputs and Outputs`; Current `Identification / Design / Verification-Time`; Commutation; Velocity/Position `Identification / Design / Scheduling / Verification-Time`; Summary | P2 v2는 explicit `K_a/B`, count/s·peak-A basis, `GS[2]=0` single-point MODEL만 구현. User Units, protection/limit 편집, I/O, settling, filter, scheduling, time-domain verification, summary 및 EAS import/export는 아직 parity가 아님 |
| Motion - Single Axis | Position/position error/velocity/active current/last fault/status/program status; Digital In/Out; `STO1/STO2/ERR`; Drive Mode(UM); Enable; `Current / Stepper / Sine Reference`; PTP Absolute/Relative; Terminal/Command Reference; 2-chart Recorder | core telemetry, session zero, locked finite PTP, 별도 Recorder와 `MO/SO/MF/PS/SR/MS` 기반 Safety Snapshot MODEL projection 구현. Digital I/O, mode별 수동 구동, terminal, EAS recorder docking parity는 미구현/NEED-DATA |

이 관찰은 **UI inventory**다. Disconnected 화면이므로 command ID, 단위, firmware 지원,
side effect, rollback, save semantics, motor response 또는 safety를 검증하지 않는다.

## 기능 범위

상단 `File / Parameters / Tools / Views / Floating Tools`는 로컬 실행이 확인된 항목만 활성화한
애플리케이션 메뉴 v1이다. 원본 EAS 메뉴 동등성은 주장하지 않는다. 공통
`OperationSpec` 카탈로그가 `LOCAL UI / LOCAL FILE / DRIVE READ / DRIVE STATE / RAM WRITE /
ENERGIZES / MOTION / PERSIST-SV / SAFETY STOP / NEED-DATA`를 분류하며, Quick/Expert 메뉴는
같은 Tuning 엔진을 안내형 식별·설계와 후보 검토·installed-gain Verify 화면으로 나눠 보여준다.
하드웨어 게인 Apply/Save는 durable pre-assignment gain-trial WAL이 생길 때까지 잠긴다.

| 영역 | 현재 상태 | 근거 수준 | 다음 게이트 |
|---|---|---|---|
| EAS Quick/Expert/Single Axis 미연결 UI inventory | 직접 화면 구조 매핑 | OBSERVED UI · NO DRIVE I/O | 연결·실행 동작과 수치 parity는 각각 별도 oracle/현장 gate |
| USB 연결, 펌웨어/PAL/부트 식별 | 구현 | LIVE | 다른 통신 경로별 동일 identity/readback 계약 |
| PX/VX/PE/IQ/MO 텔레메트리 | 구현 | LIVE | stale-telemetry 표시와 통신 품질 카운터 |
| Session Zero (`PX=0`) | 구현 | LIVE 1회 + OFFLINE 회귀 | MO=0·정지·무전류·PX 되읽기 유지; 전원 재인가 후 복원된다고 주장하지 않음 |
| Motor Settings 읽기/durable 저장 | transaction 구현 | OFFLINE fault injection; 과거 direct-write LIVE 이력은 별개 | 최신 흐름의 RAM rollback·단일 SV·냉간 audit 감독 실기 |
| Feedback 공통 설정 | 읽기/Preview-only 구현; direct save 잠금 | LIVE readback: 현재 EnDat 2.2 조합 | versioned 명령/type/range/side-effect registry와 센서별 golden readback |
| EAS 23종 Feedback 패널 | 읽기/preview UI 구조 구현; 저장 잠금 | MODEL; 일부 ID 미확정 | registry에 포함되지 않은 센서·필드는 계속 fail-closed |
| EnDat Encoder Maintenance (`TW[18..20]`) | 구현 | LIVE: 현재 드라이브 명령 확인 | 명령 자체가 encoder datum/NVM 동작임을 유지; 별도 `SV`를 붙이지 않음 |
| Personality upload와 레코더 신호 목록 | 구현 | LIVE | 연결 generation별 재발견; 펌웨어별 신호 이름·단위 검정 |
| 고속 Drive Recording | Immediate finite v1 구현 | LIVE positional key + OFFLINE lifecycle/반례 | Normal/Auto/Interval/Rollover trigger 계약과 post-Configure timing 실기 readback |
| Recorder CSV/provenance | 구현 | OFFLINE | raw CSV + UTC/target/timing/SHA-256 metadata sidecar의 현장 capture 검증 |
| Phase 1 R/L 식별과 전류 PI 설계 | 구현 | LIVE: 식별/설계 | 최신 코드로 감독 식별·후보 산출 재검증; gain Apply와 분리 |
| P1 게인 임시 적용/복원/SV | production Apply/Save pre-I/O 잠금; state machine은 synthetic-only | OFFLINE 전체 회귀·drive I/O 0 fail-closed 반례 | P2_LIMITS와 공존하는 durable pre-assignment gain-trial WAL 및 real session-bound verifier 전에는 잠금 유지 |
| 커뮤테이션 서명 | 구현 | LIVE + OFFLINE 회귀 | 매 전원 투입 시 제한 전류·방향·최종 `TC=0/MO=0` 확인 |
| Phase 2 속도/위치 식별·설계 | 구현 | LIVE 이력 + OFFLINE 회귀 | 현재 EAS 설정 provenance를 독립 되읽기한 뒤 재개 |
| Expert Candidate Lab v2 P1→P2 | explicit R/L/TS P1과 K_a/B P2 immutable LOCAL MODEL 구현; installed readback·hardware authority 분리 | OFFLINE MODEL; 동결 기준점·대수 oracle·mutation/음성 대조·세 스킨 1366×820 | 다른 motor/feedback/firmware/Gold 제품 일반화 금지; EAS 수치 parity와 실기 안정성 별도 |
| Expert filter / gain scheduling | UI에 `FILTER NEED-DATA`, `GS[2]=0 ONLY` 경계 고정; KV/GS/KG emulation/write 없음 | 공개 command reference의 이름·기본 mode만 MODEL | exact transfer/discretization/range 및 table interpolation/index-selection oracle 확보 |
| P2 게인 적용·검증·복원·SV | installed-gain Verify 구현; production Apply/Save pre-I/O 잠금; trial state machine은 synthetic-only | 과거 LIVE 이력 + OFFLINE 세션/권한/UNKNOWN·drive I/O 0 반례 | durable pre-assignment gain-trial WAL 전에는 새 trial/Save 금지; installed-gain Verify는 판정만 제공 |
| P1_CONFIG/P2_LIMITS/Motor durable ledger + legacy P2 audit | active production scope 구현; legacy P2 record 판정 엔진 유지 | OFFLINE crash/write/readback/손상/identity/interprocess 반례 | 임시 구성 rollback·Motor SV 응답 유실 뒤 냉간 OFF/ON + query-only audit 현장 검증 |
| 자동 설정 프로필 | Motor v1 구현; Feedback 잠금 | Motor OFFLINE, Feedback NEED-DATA | Feedback versioned registry → RAM trial/readback/rollback → 별도 SV |
| 유한 Single-Axis PTP | backend/STOP transaction 구현, live 잠금 | OFFLINE 42-test kernel | 기계 envelope·정방향·limit·정지거리·독립 E-stop/STO evidence 전에는 gate 해제 금지 |
| Single Axis Safety Snapshot v1 | 기존 `MO/SO/MF/PS/SR/MS`의 zero-new-I/O read-only projection 구현 | OFFLINE MODEL; 2013 command reference decode; `NOT STO TEST EVIDENCE` | 현재 firmware 의미 readback, 독립 STO/E-stop 배선·응답·torque isolation은 별도 현장 gate |
| 일반 수동 Jog/Homing/Current/Sine | 미구현 | NEED-DATA | 별도 안전 요구사항·limit·watchdog·fault-state 설계 후에만 추가 |
| 범용 Scope/Plot/Export | Recorder selection/export + 읽기 전용 2-lane View + shared-X Zoom + local FFT + full+A:B Signal Statistics/Values + local A/B drag/snap + provenance-bound Statistics CSV | backend LIVE + View/Zoom/A:B/CSV OFFLINE; endpoint/delta/RMS/Tolerance %와 nearest original sample 의미 STATIC-IL VERIFIED; FFT STAND-IN | exact EAS glyph/shortcut/persistency/file parity, exact Apply-to-All, verified unit metadata, advanced trigger |
| Tool Organizer v0.1 | modeless session-only 8-page 표시/숨김·재정렬·Reset; safety shell과 active recovery page 보호 | OFFLINE · PARTIAL · LOCAL_UI; zero-new-drive-I/O | EAS activity/Favorites 전체 조건과 native persistence는 별도 근거 필요 |
| EAS-native Tool Organizer persistence | 미구현·잠금 | NEED-DATA | EAS 저장 위치/schema/version/unknown-field/손상 복구와 재시작 round-trip oracle |
| HOST-OBSERVED Status Monitor v0.1 | modeless fixed PX/VX/PE/IQ/MO projection + session-only line 추가/삭제/재정렬/Reset | OFFLINE · PARTIAL · LOCAL_UI projection; 기존 core-admitted telemetry만 소비하고 새 polling/I/O 없음 | exact authority/fail-closed 계약은 아래 절; EAS 전체 polling·signal·display parity와 분리 |
| Full EAS Status Monitor polling/signals/gauge/Quick Watch | 미구현·잠금 | NEED-DATA | visible-only 0.5 s sampling, arbitrary variables/arrays, multi-target, user units, color/gauge/warning, Quick Watch/topmost의 runtime oracle와 bounded READ ownership |
| EAS-native Status Monitor `.smc`/`.sac` configuration | 미구현·잠금 | NEED-DATA | help의 extension 모순 해소, schema/version/unknown-field/corruption/N/A-target 처리와 EAS open-save-open fixture |
| Host-observed Status / Session Log v0.1 | bounded viewer + redacted JSON/CSV 구현 | OFFLINE · PARTIAL | 기존 앱 이벤트만 소비; drive history/source timestamp가 아님 |
| Full EAS Fault/Ack/Clear Manager | 미구현·잠금 | NEED-DATA | drive-origin history/timestamp, EC/SR/MF taxonomy, Ack/Clear/Reset 권한·복구 계약 |
| System Configuration Inspector v0.1 | admission된 단일 Gold/Direct Access USB target의 one-level read-only host projection | OFFLINE · PARTIAL; 화면 open/render는 zero-new-drive-I/O | board type은 UNOBSERVED/NEED-DATA; firmware/PAL/boot는 sanitized/redacted host display of readback이며 host provenance 확장과 구분 |
| Full System Configuration management | Add/Remove/Edit/Group/I/O/Virtual Axis 미구현·잠금 | NEED-DATA | topology·target identity·side effect·partial failure·rollback 계약 |
| CAN/EtherCAT 네트워크 구성 | 미구현 | NEED-DATA | 통신 하드웨어·네트워크 설정·복구 경로가 있는 별도 모듈 |
| 프로그램/파라미터 파일 업·다운로드 | 미구현 | NEED-DATA | 형식·버전·원자성·복구·비밀정보 검증 |
| 펌웨어 다운로드 | 앱에서 제공하지 않음 | 고위험 | 전용 복구 절차와 사용자의 명시적 flashing 승인 없이는 EAS 사용 |
| 비공개/공장/라이선스 보호 기능 | 제공하지 않음 | UNSUPPORTED | 우회하지 않음; 공식 문서·API·권한이 확보된 범위만 재평가 |

## Tool Organizer v0.1 계약

- organizer가 다루는 canonical 집합은 `motion / motor / feedback / tuning / axis / recorder /
  status / system`의 고정된 8개 workspace page뿐이다. 현재 세션에서 visible/available partition과
  visible 순서를 바꾸고 Reset으로 기본 순서를 복원한다. 모든 page 객체는 그대로 유지되며 최소 한
  page가 항상 visible이어야 한다.
- Connection/Disconnect, 전역 DRIVE STOP, ONLINE 표시, persistence warning과 상단 application
  menu는 layout namespace 밖의 보호된 safety shell이다. forged/unknown/duplicate/missing/all-hidden
  layout은 부분 적용 없이 거부한다.
- 미저장 P1/P2 trial 또는 tuning/Motor transaction, Recorder recording/stop/recovery/UNKNOWN,
  Motion inflight/stop/recovery가 있으면 해당 page를 숨길 수 없다. 숨긴 page의 중복 menu action도
  보이지 않고 programmatic trigger로 page를 열지 못한다.
- dialog는 modeless이고 staged 변경은 Apply 전까지 main layout을 바꾸지 않는다. Cancel은 버리고,
  render 실패는 이전 model/visibility/current page로 rollback한다. 이 동작은 `LOCAL_UI`이며
  worker, `ElmoLink`, serial, network, drive query/write/job을 호출하지 않는다.
- v0.1은 **session-only**다. 로컬 파일, Windows registry, EAS 설정에 저장하거나 다음 앱 시작에
  복원하지 않는다. EAS가 문서화한 activity/Favorites와 세션 간 저장을 재현한 것이 아니므로
  EAS-native persistence는 operation catalog에서 `NEED-DATA` 및 비활성이다.
- 공개 근거는 설치 경로
  `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Settings and Configuration.htm`
  §13.3, SHA-256
  `E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881`이다. help manifest
  `NetHelp\Default.mcwebhelp`의 SHA-256은
  `51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF`다. 이는 문서 근거이며
  실제 EAS Tool Organizer 화면·native 저장 round-trip·hardware/display 검증이 아니다.

## HOST-OBSERVED Status Monitor v0.1 계약

- UI는 `Floating Tools → Status Monitor`에서 여는 modeless dialog다. 표시 column은 `Target / Signal /
  Value / Units / Description`이고, 현재 allowlist는 `PX`→`pos`/cnt, `VX`→`vel`/cnt/s,
  `PE`→`pos_err`/cnt, `IQ`→`iq`/A, `MO`→`mo`/state의 다섯 신호로 고정된다. dialog는 새 timer,
  polling, worker/COM 호출, drive query/write/job을 만들지 않으며 core가 이미 받아들인 telemetry의
  observer일 뿐이다.
- line 추가/삭제/위·아래 이동/Reset은 immutable session config로만 유지된다. local defensive cap은
  16 lines이며 EAS 최대 line 수라고 해석하지 않는다. duplicate/unknown/mutable line은 부분 적용 없이
  거부하고 config 변경 즉시 이전 값을 모두 blank 처리한다. save/load API나 local/native persistence는 없다.
- 활성 positive generation과 exact canonical `elmo-sn4-sha256:<64 lowercase hex>` identity에 bind한다.
  sample은 core가 `fresh=True`로 attestation한 strictly increasing positive sequence이고, 다섯 신호가
  모두 존재하며 finite이고 `MO`가 정확히 0 또는 1일 때만 `CURRENT`다. stale/replay, old/wrong generation, malformed/wrong identity,
  incomplete/non-finite sample 또는 observer 오류는 전체 snapshot의 sequence와 모든 value를 blank로
  폐기한다. partial row 유지나 이전 값 fallback은 없고 snapshot/UI에는 exact identity나 digest prefix 대신
  고정 `Drive01` alias만 보인다.
- 설치 NetHelp `Supporting Tools.htm` §12.3은 one-or-more target의 선택 motion variable, arbitrary
  variable/array 입력, Target/Signal/Value/Units/Description/Gauge, target filter/lock, line 도구,
  counts/user units와 gauge limits를 설명한다. visible Status Monitor는 background에서 0.5 s마다 읽고
  숨겨지면 view를 갱신하지 않으며, 값 변화는 red/다음 동일 read는 black으로 표시한다고 적는다.
  현재 v0.1은 이 polling을 소유하지 않고 core telemetry는 dialog visibility와 독립적으로 계속된다.
- `Floating Tools.htm` §11.5의 EAS floating view는 compact Target/Signal/Value, Quick Watch,
  always-visible/top 동작과 Unpin을 설명한다. v0.1은 modeless인 것만 구현했고 Quick Watch, topmost,
  arbitrary signals/arrays, multi-target, user units, Gauge/경고 border와 EAS display parity는 `NEED-DATA`다.
- native config는 의도적으로 없다. `Supporting Tools.htm` §12.3.1.3의 Save는 `*.smc`, §12.3.1.4의
  Append 문장은 dialog를 `*.sac`라 한 직후 선택 파일을 `*.smc`라 하고 Replace는 `*.smc`라고 한다.
  따라서 확장자나 schema를 추측하지 않으며 실제 EAS fixture의 open-save-open, append/replace,
  unknown-field, corruption과 unavailable-target oracle 전까지 operation catalog에서 잠근다.
- 증거 identity는 설치 경로
  `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Supporting Tools.htm`
  SHA-256 `300B980C11BF37A5AE20803AA3038C178A2E6CD0785959791124EFA6739AAEC4`,
  같은 directory의 `Floating Tools.htm` SHA-256
  `32936D4B12A469CC950B592268D4E56A0E7BD12465C1CFA6AC88549D0B2E7E85`, help manifest
  `NetHelp\Default.mcwebhelp` SHA-256
  `51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF`다. 설치 executable
  `ElmoMotionControl.View.Main.exe` 3.0.0.26의 SHA-256은
  `C8A023EA6DCEF8BC39E3E86E0AF929269AB47BB5B8791EB99FB9A62080F719ED`다. 이 정적 근거는 실제
  EAS 3.0.0.26 dialog 관찰, native file round-trip, hardware 또는 display validation이 아니다.

## 자동 설정의 실행 계약

자동화 가능한 것은 계산·비교와 각 기능이 명시적으로 허용한 bounded transaction의 되읽기·복원이다.
다음 순서를 공통으로 사용한다.

1. 해시된 drive identity, 정확한 연결 세션 토큰과 펌웨어, 현재 전체 설정 스냅숏을 기록한다.
2. 적용 전 변경 목록과 단위 변환을 보여준다.
3. `MO=SO=VX=MF=0`, `PS=-2/-1`, 정지, 무전류, fresh telemetry를 다시 확인한다.
4. Motor profile은 첫 assignment 전에 durable WAL을 기록하고, WAL 직후 전체 snapshot을
   사전검사 값과 exact 비교한다. 각 forward/rollback assignment 직전에도 안전 상태를 재조회한다. RAM에 적용한 뒤 모든 대상
   레지스터를 독립 되읽기한다.
5. Motor의 pre-SV 일부 실패·timeout·불일치는 역순 원값 복원과 전체 되읽기를 수행한다.
   복원이 확인되면 `SV` 없이 종료하고, 확인되지 않으면 `UNKNOWN`으로 잠가 새 시험·enable·motion·반복 `SV`를 금지한다.
6. Production P1/P2 gain Apply와 Save는 durable pre-assignment gain-trial WAL이 없으므로 첫 drive
   I/O 전에 fail-closed한다. trial/restore/Save state machine은 exact `SYNTHETIC_NO_HARDWARE`
   회귀에서만 열린다. `Verify Installed P2 on Motor`는 현재 설치 게인을 대상으로 commutation
   signature와 `P2_LIMITS` WAL을 요구하지만 판정만 반환하며 Apply/Save 권한을 만들지 않는다.
   Motor v1은 한 확인창에서 RAM 적용과 단일 `SV`까지의 bounded transaction 전체를 명시하며
   중복 요청을 잠근다.
7. 영구 `SV`는 전체 readback이 일치하고 해당 request의 record ID-bound durable authority가 있을 때 정확히 한 번만 실행한다.
   `PERSISTING` fsync 뒤 full profile/안전 snapshot과 마지막 안전 조회도 재검증하며, 실패하면 UNKNOWN·SV 미실행이다.

위 재조회는 외부 EAS/CAN/EtherCAT master와 원자적 interlock이 아니다. 실기 프로필 저장은 다른
master의 배타적 제어권이 확인될 때까지 `NEED-DATA`다. Motor 변경·연결 세대 변경 시 과거 P1/P2
결과와 복구 trial authority는 폐기하고 이전 worker의 지연 신호도 무시한다.

Production에서 mutation 가능한 P1_CONFIG, P2_LIMITS, Motor는 첫 RAM assignment 전에 해시된
drive identity, 정확한 VR/VP/VB·connection epoch와 original/applied profile을 checkout 밖
`%LOCALAPPDATA%\AngryYJHControl\safety`의 SHA-256 검증 원장에 interprocess lock으로 atomic
기록한다. Motor만 전체 applied readback 뒤 `PERSISTING`으로 전이해 단일 `SV` authority를 얻는다.
기존 P2 gain audit 엔진은 legacy/offline ambiguous-SV record를 판정할 수 있지만 현재 production
UI/domain은 새 P2 trial 또는 gain `SV` record를 만들지 않는다. P1 gain Save도 잠겨 있다.

원장 기록 뒤 응답 유실이나 강제 프로세스 종료가 발생해도 `UNKNOWN` 잠금은 유지된다. 해제는
사용자가 UNKNOWN 이후 냉간 OFF/ON 또는 동등한 reset을 현장에서 확인하고, 새 connection epoch의
동일 drive identity·VR/VP/VB에서 disabled 안전 상태와 안정된 두 query-only snapshot을 확인한
때만 가능하다. `SV`, `LD`, `RS`, assignment는 audit에서 보내지 않는다. 해제 record에는 reset
attestation, 새 epoch, 정확한 software context, 두 snapshot과 별도 evidence SHA-256을 archive한다.
P1_CONFIG/P2_LIMITS/Motor는 exact 비교를 사용하고 legacy P2 gain record만 0.1% 판정 허용오차를
사용한다. 이 원장을 모르는 구버전 checkout은 UNKNOWN 중 제어용으로 사용하지 않는다.

Audit 결과는 `RESOLVED_APPLIED_PROFILE` 또는 `RESOLVED_ORIGINAL_PROFILE`처럼 전원 재인가 뒤
관측된 durable configuration/gain/Motor profile만 말한다. 특정 `SV`의 인과적 성공/실패,
whole-drive flash 동일성, 커뮤테이션 유효성, motion safety는 계속 `UNKNOWN`이며 별도 검증이
필요하다. 현재 active production 원장 범위는 P1_CONFIG, P2_LIMITS, Motor이고 legacy P2 record
판정만 호환 유지한다. Feedback assignment/SV는 이 원장만 재사용해 임의로 열지 않으며,
versioned write registry와 sensor-ID side-effect/rollback 계약이 먼저다.

모터 enable, motion, 커뮤테이션 전류 인가, 영구 encoder datum 변경, 안전 한계 확대는
설정 프로필의 자동 실행 항목에 포함하지 않는다.

## 문서화되었다고 구현 가능한 것은 아니다

- 공식 Command Reference/Drive .NET Library에 공개된 기능은 capability/firmware gate와 되읽기를
  붙여 구현할 수 있다.
- EAS 화면 또는 personality XML에서만 관측된 항목은 우선 읽기 전용으로 발견하고, 명령·단위·복원
  경로를 확인한 뒤에만 쓰기를 연다.
- 알 수 없는 명령을 실제 드라이브에 탐색적으로 쓰지 않는다. read-only reflection, personality,
  공식 릴리스 노트, 동일 조건 A/B diff 순으로 근거를 올린다.
- 공장 서비스·서명·라이선스·안전 인터록을 우회해야 하는 기능은 구현 목표에서 제외한다.

## Recorder View Design v3 + Time/FFT/A:B Signal Statistics 계약

View Design은 worker나 `ElmoLink`를 소유하지 않는 로컬 읽기 전용 계층이다. 정확한
`COMPLETED` lifecycle, `VALIDATED` manifest, `ResolvedRecorderRequest`, capture ID,
connection/UI generation, drive identity와 worker completion token이 모두 결속된 capture만 표시한다. UI에서도
`validate_capture()`를 다시 실행하며, `dt`, 샘플 수, finite 값, 정확한 Personality 신호명이
하나라도 불일치하면 차트와 CSV 권한을 열지 않는다.

두 chart의 기본 시간축은 `index × actual dt`이고 단위는 추정하지 않는다. chart·summary·CSV는
한 immutable evidence snapshot을 공유한다. v1은 총 16K sample 상한과 lane당 1채널 제한 안에서
full waveform을 렌더하고 auto y-range도 full evidence에서 계산한다. raw CSV가 분석·보관 증거다. 새 capture 시작 시 이전
view authority를 즉시 폐기하고, 연결 변경 시 기존 차트는 남겨도 `HISTORICAL / OFFLINE`으로만
표시한다.

Manual Time Zoom은 capture data를 수정·감축하지 않고 공통 X(time) viewport만 두 chart에
적용한다. 범위는 capture domain 안에서 최소 2개 실제 sample을 포함해야 한다. Y 범위는
Personality-owned unit을 추정하지 않기 때문에 chart별 독립으로 유지한다. 레이아웃 JSON은
`angryyjh-recorder-view-layout/v3` 로컬 형식이며 v1은 Full Time+Time mode, v2는 저장된
시간창+Time mode로 이관한다. v3는 `plot_mode`를 명시한다. EAS의 Apply-to-All
축/대상/undo/persistency 의미와 파일 호환은 `NEED-DATA`다.

로컬 FFT는 full immutable capture의 one-sided peak amplitude `STAND-IN`이며 직사각 창,
detrend/zero padding 없음, DC 포함, Y 하한 0을 명시한다. Signal Statistics는 설치 EAS NetHelp가
문서화한 entire-signal field를 같은 full evidence에서 `DERIVED`로 계산하되, prose의 RMS와 literal
`sqrt(sum)/N` 수식이 모순된다. 설치 ViewModel/Action DLL의 실제 IL은 두 경로 모두 N으로 나눈 뒤
`Math.Sqrt`를 호출해 표준 RMS 의미를 확정한다. 로컬은 overflow-safe 안정화 계산이므로 극단값의
bit-identical rounding은 미주장한다. Zoom/FFT/lane과 독립이고 계산 실패가 capture/CSV 권한을
취소하지 않으며 EAS의 `startIndex < endIndex` gate에 맞춰 N=1은 잠근다. Local A/B는 exact
integer sample index, inclusive `N=B-A+1`, endpoint Signal Values, signed `ΔX/ΔY`, Tolerance %를 구현했다.
Time chart의 A/B 선은 현재 visible viewport의 exact 원본 sample로 mouse drag/snap하며 거리 동률은
낮은 index를 택한다. A<B를 유지하고 release 때 inclusive 통계를 한 번 계산한다. 통계 CSV v1은
capture binding, exact source-view SHA-256, 범위, signal 순서, CURRENT/HISTORICAL_OFFLINE authority를
한 UTF-8 파일에 넣어 같은 디렉터리 temp+fsync+replace로 게시한다. 이는 local-only 형식이며 EAS
Save As 호환을 주장하지 않는다. EAS Marker/Cursor의 정확한 glyph/shortcut/persistency, FFT-bin
range는 계속 `NEED-DATA`다. Rollover,
Normal/Auto/Interval, Multi-drive,
`.mat`, EAS layout schema도 계속 별도 근거/실패 계약이 필요한 기능이다.

## Host-observed Session Log v0.1 계약

- 최대 512개 host-observed 이벤트와 정확한 drop count만 유지하며, 단일 payload도 64 KiB로 제한한다.
- 앱 로컬 connection generation과 `CURRENT / HISTORICAL / REJECTED`를 구분한다. 이전 worker,
  sequence replay, source timestamp 회귀, invalid telemetry는 현재 상태를 되살리지 못한다.
- host UTC/monotonic은 앱 관찰 시각이며 drive source timestamp나 vendor fault history가 아니다.
- `MO/SO/MF/SR/MS`는 기존 Axis Summary가 이미 읽어 전달한 값만 수동 소비한다. `MF != 0`은
  raw `ERROR` 표시까지만 하며 원인 taxonomy나 복구 의미를 추정하지 않는다.
- JSON/CSV는 버튼 시점의 detached snapshot을 target alias·포트·경로·SN[4] 비식별화 후 같은
  디렉터리 temp+fsync+replace로 저장하고 최종 readback SHA-256을 확인한다.
- 화면 열기·렌더·내보내기는 drive query/write/job을 만들지 않는다. Ack/Clear/Reset과 full EAS
  fault manager는 계속 `NEED-DATA` 및 비활성이다.

## Single Axis Safety Snapshot v1 계약

- `single_axis_status.py`는 Qt, worker, link를 import하지 않는 순수 decoder다.
- 입력은 이미 현재 worker의 Axis Summary가 전달한 `MO/SO/MF/PS/SR/MS`로 제한한다.
  화면 표시를 위해 새 drive query, polling, job enqueue 또는 write를 만들지 않는다.
- 의미 해석은 로컬 `MAN-G-CR Ver. 1.406 (2013)`의 SR bit 표를 사용하므로
  현재 2020 firmware에 대해 `MODEL`이다.
- `SR14/SR15=1`은 오직 drive가 enable permission을 보고했다는 뜻으로 표시하며,
  `STO OK`, `SAFE`, `GREEN`, 독립 안전 회로 시험 완료로 표시하지 않는다.
- missing, bool, NaN/Inf, non-integral, 초대형 정수 또는 범위 밖 값은 전체 projection을
  `UNKNOWN`으로 blank한다.
- 2013 reference의 reserved SR bit, `{0,3,5,7,B,D}` 밖 amplifier code와
  profiler code 11–15는 현재 firmware 의미를 추정하지 않고 `UNKNOWN`으로 blank한다.
- `SO/SR4` 또는 `PS/SR12` 불일치는 `INCONSISTENT · AUTHORITY UNKNOWN`이다.
- current worker 이외 signal, shutdown-pending, disconnect 또는 worker 교체 뒤 signal은
  snapshot을 복구하지 못한다. current worker summary의 configuration/energy fail-safe latch와
  safety projection freshness gate는 분리한다.
- telemetry authority 상실·energizing 중에는 projection을 즉시 blank하고 queued summary도
  이를 복구하지 못한다. 이후 fresh telemetry authority와 새 summary가 모두 있어야 복구한다.
- Digital In/Out, Current/Stepper/Sine Reference와 Terminal은
  `eas.single_axis.*` operation으로 분리해 `NEED-DATA` 잠금을 유지한다.

## 다음 구현 순서

1. Expert v2 P1→P2 순수 OFFLINE 모델의 전체 회귀·독립 리뷰·runtime smoke를 유지.
2. Expert filter/scheduling은 현재처럼 `NEED-DATA`를 유지하며 공개 근거를 대조해
   명시적 입력·단위·범위가 고정된 항목만 구현.
3. EAS 미연결 세부 화면과 operation catalog 구현/잠금 상태를 항목별 대조.
4. Digital I/O·수동 reference·Terminal은 mapping/limit/watchdog/rollback 근거 전까지
   `NEED-DATA` 유지.
5. 현장 gate가 준비된 개별 동작만 별도 승인 후 제한 검증.
