# AngryYJH Control — Elmo Gold Twitter 미니-EAS 제어 프로그램

Made by 여재현 (SPG). Elmo **Gold Twitter** 서보드라이브를 위한 자체 PyQt6 데스크톱 제어
프로그램. Elmo Application Studio III(EAS III)의 핵심 기능을 정품 Drive .NET Library +
실기 오라클로 재현한다.

> **2026-07-18 현재 활성 범위는 Quick Tuning + 제한형 Single Axis Motion +
> Expert Candidate Lab v2 + 로컬 Evidence/Page Status inspector이다. 독립 안전 검토의
> Critical/Important 소프트웨어 finding은 닫혔지만, 최신 리비전의 감독 실기와 현장 motion envelope가
> 없으므로 hardware 사용은 계속 차단된 Offline Hardened Candidate · Private Draft 상태다.**
> 현재 구현·증거·중단 지점·재개 순서는
> [`docs/current-scope-handoff.md`](docs/current-scope-handoff.md), 실시간 표시용 요약은
> [`tasks/status.md`](tasks/status.md)를 기준으로 한다. Production P1/P2 gain Apply/Save와 finite PTP
> live gate는 잠겨 있다. `.omc/paf5-brief.md`와 전체 EAS 계획은
> 과거 개발 맥락 및 장기 backlog 참고 자료다.

---

## 무엇인가

- **대상**: Gold Twitter / HW `GCON Revision E` / FW `Twitter 01.01.16.00` / S/N 22033647 / `Direct Access USB, COM3`.
- **통신 = Path A**: pythonnet(netfx)로 정품 `ElmoMotionControlComponents.Drive.EASComponents.dll`을
  파이썬에서 로드 → 2글자 Elmo 명령 + .NET Drive Recording/Personality API. **하드웨어가 아니라
  소프트웨어 골조·테마·교훈만** 선례([Fable5-SDD-Control-Program])에서 재사용.
- **실기 오라클 규율**: 모든 값을 실드라이브 대조로 확정. 모션/통전은 사용자 감독 하에서만.

## 실행 / 테스트

```bash
python main.py                    # GUI (테마: AYJH_THEME=qdd|angrybirds|amber)
python main.py --smoke            # 헤드리스 스모크 (연결/텔레메트리)
python main.py --smoke-feedback   # 23센서 피드백 패널
python main.py --smoke-autotune   # 오토튠 GUI 배선
python main.py --smoke-velpos     # Phase 2 + 커뮤테이션 서명 GUI/워커 배선
python main.py --smoke-encoder    # Encoder Maintenance
python main.py --smoke-recorder   # EAS형 Recorder 리본/페이지(하드웨어 I/O 없음)
python -m pytest tests/ -q        # 전체 유닛/시뮬 회귀시험
```

## 화면 구성

| 화면 | 내용 | 상태 |
|---|---|---|
| **Motion** | 실시간 텔레메트리(PX/VX/PE/IQ/MO) + generation-bound Session Zero + 제한형 finite PTP | 텔레메트리/Soft Zero LIVE 이력 · finite PTP OFFLINE 및 live 잠금 |
| **Motor Settings** | Peak/Cont 전류(√2 rms), MaxSpeed, 극쌍, Motor Type + durable 저장 transaction | 🟡 OFFLINE fault-injection; 최신 저장 흐름 실기 대기 |
| **Feedback** | 23종 센서 동적 읽기 패널 + 별도 **Encoder Maintenance**; registry 전에는 명시적 Preview-only | 읽기/정비 LIVE 이력 · 설정 쓰기 fail-closed |
| **Tuning** | Phase 1/2 식별·설계 후보, installed-gain Verify, connection-bound 커뮤테이션 서명 + no-I/O Expert P1→P2 MODEL/Evidence/Page Status | Expert v2와 로컬 inspector OFFLINE 검증 · 과거 hardware LIVE 이력과 분리 · production gain Apply/Save 잠금 |
| **Axis Setup** | UM/feedback routing/FC/BP/SC/limit/profile 원시값 요약 | 🟡 read-only v1; 쓰기 잠금 |
| **Recorder** | target-bound Personality 신호, 16K 계산, Immediate, retry/cancel, CSV+SHA metadata + 읽기 전용 듀얼 차트/시간 줌/로컬 FFT/full+A:B 통계 | 🟡 backend LIVE · View/Time/FFT/A:B Statistics OFFLINE 검증 |
| **Status / Log** | 최대 512개 host-observed 이벤트, generation/scopes, raw status, 비식별화 JSON/CSV | 🟡 OFFLINE · drive fault history 아님 · Ack/Clear/Reset 잠금 |
| **System Configuration** | 이미 admission된 단일 Gold/Direct Access USB target의 one-level host projection | 🟡 OFFLINE · PARTIAL · 관리 기능 잠금 |
| **File → Tool Organizer** | 고정된 8개 page의 세션 내 표시/숨김·순서 변경·기본값 복원 | 🟡 OFFLINE · PARTIAL · 저장 없음 |
| **Floating Tools → Status Monitor** | modeless HOST-OBSERVED PX/VX/PE/IQ/MO + 세션 내 line 추가/삭제/재정렬/Reset | 🟡 OFFLINE · PARTIAL · 새 polling/drive I/O 없음 |

상단 Recorder 리본의 쉬운 기능 설명과 잠금 이유는
[`docs/eas-recorder-ribbon.md`](docs/eas-recorder-ribbon.md), 로컬 차트의 정확한 범위는
[`docs/recorder-view-design.md`](docs/recorder-view-design.md), 바탕화면 Elmo 자료의 적용 범위와
firmware 해시 주의사항은 [`docs/local-elmo-artifact-audit.md`](docs/local-elmo-artifact-audit.md)를 본다.

## 지금까지 (핵심 성과)

### Expert Candidate Lab v2 — 순수 오프라인 P1→P2

- phase-to-phase `R/L/TS` Current P1 MODEL과 명시적 count/s·peak-A
  `K_a/B` Velocity/Position P2 MODEL을 두 단계로 분리한다.
- P2는 완전한 passing P1 MODEL만 입력으로 받고 `KP[2]`, `KI[2]`, `KP[3]`와
  modeled PM/GM을 계산한다. `I_c`는 선형 소신호 설계에서 제외한다.
- invalid 입력은 이전 완전한 모델을 보존하고, 새 P1 성공은 종속 offline P2만 폐기한다.
- 계산은 `ElmoLink`, `DriveWorker`, command queue 또는 installed readback을 사용하지 않으며
  Apply/Save/Verify 권한을 열지 않는다.
- `SINGLE-POINT`, `GS[2]=0 ONLY`, `FILTER NEED-DATA`를 화면에 고정한다. 다른 motor,
  feedback, firmware, Gold 제품 일반화나 EAS 내부 알고리즘 동등성을 주장하지 않는다.
- 상세 단위·수치·음성 대조:
  [`docs/expert-tuning-offline-v2.md`](docs/expert-tuning-offline-v2.md).
- 세 번째 `FILTER / SCHED EVIDENCE` 단계는 MAN-G-CR 1.406에서 확인된 filter type,
  KV controller slot, `GS[2]` mode와 KG table topology만 순수 로컬로 탐색한다.
  KV/KG/GS 절 사이의 다섯 가지 문서 충돌과 누락된 SimplIQ §15.4를 그대로
  `NEED-DATA`로 보여주며 filter 계산·controller 선택·KV/GS/KG write는 제공하지 않는다.
  상세 계약:
  [`docs/expert-filter-scheduling-evidence-v0.1.md`](docs/expert-filter-scheduling-evidence-v0.1.md).
- 네 번째 `STATUS / ERRORS` 단계는 현재 메모리의 P1/P2/evidence만
  `MISSING / BLOCKED / STALE / INVALID / CURRENT LOCAL MODEL / DOCUMENTED PARTIAL`로
  분류한다. `LOCAL STATUS ONLY · NOT EAS ENTER/APPLY STATE · NOT INSTALLED`이며,
  EAS page icon/Summary parity나 drive read/write를 제공하지 않는다. 상세 계약:
  [`docs/expert-page-status-v0.1.md`](docs/expert-page-status-v0.1.md).

### Fault / Status / Session Log v0.1

- 이미 앱에 전달된 연결·telemetry 상태 전이·Axis raw status·Recorder·motion·persistence 이벤트만
  수동 소비한다. 화면 열기·렌더·export가 drive query/write/job을 만들지 않는 poison-worker
  회귀 계약을 둔다.
- connection generation별 `CURRENT / HISTORICAL / REJECTED`, sequence/source-time 회귀 차단,
  정확한 drop count와 64 KiB/event 상한을 적용한다.
- JSON/CSV는 버튼 시점의 detached snapshot을 target alias·포트·사용자 경로·SN[4] 비식별화 후
  atomic replace하고 readback SHA-256을 확인한다.
- host 시각은 drive source timestamp/history가 아니다. Full EAS fault taxonomy와
  Ack/Clear/Reset은 계속 `NEED-DATA` 및 비활성이다.

### System Configuration Inspector v0.1

- 화면 열기와 렌더는 worker를 호출하거나 새 drive query/write/job을 만들지 않는다. 이미 연결
  admission을 통과한 현재 generation의 단일 `Gold Drive / Direct Access USB` telemetry와
  metadata만 `Workspace → Drive01` 한 단계 tree에 투영한다.
- firmware/PAL/boot는 기존 VR/VP/VB readback의 NFC-normalized, control-neutralized,
  local-identifier-redacted host display이며 raw readback과 동일하다고 주장하지 않는다.
  target class·connection type·generation·수신 시각은 host provenance로 분리한다.
  Hardware Board Type은 검증된 공개 read mapping이 없어
  `UNOBSERVED / NEED-DATA`이며 target class를 board readback으로 표시하지 않는다.
- Add/Remove/Edit, Group, I/O, Virtual Axis와 full EAS System Configuration management는
  side effect·rollback 계약이 없어 `NEED-DATA`로 UI와 operation catalog에서 계속 잠겨 있다.

### Tool Organizer v0.1

- `File → Tool Organizer`는 modeless `LOCAL_UI`다. Motion, Motor, Feedback, Tuning, Axis,
  Recorder, Status, System의 고정된 8개 page만 현재 세션에서 표시/숨김·재정렬하며 Reset으로
  기본 순서를 복원한다. 최소 한 page는 항상 보이고, 숨겨도 page 객체나 backend는 제거하지 않는다.
- Connection/Disconnect, 전역 DRIVE STOP, ONLINE 상태와 persistence 경고는 organizer의
  namespace 밖에 있어 숨길 수 없다. Tuning trial/transaction, Recorder recording/recovery,
  Motion 실행/정지/recovery가 진행 중이면 해당 복구 page를 숨기는 적용도 거부한다.
- v0.1은 세션 전용이며 파일·레지스트리·EAS 설정에 저장하지 않는다. dialog 열기, Apply/Cancel/Reset은
  worker/COM을 호출하거나 drive query/write/job을 만들지 않는다. EAS native 구성 persistence와
  activity/Favorites 전체 동등성은 `NEED-DATA`이며 full EAS parity를 주장하지 않는다.
- 공개 기준은 설치된 `Settings and Configuration.htm` §13.3
  (SHA-256 `E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881`)과
  `Default.mcwebhelp`
  (SHA-256 `51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF`)다.
  실제 EAS Tool Organizer 화면의 display parity나 hardware 동작을 검증했다는 뜻은 아니다.

### HOST-OBSERVED Status Monitor v0.1

- `Floating Tools → Status Monitor`는 modeless 보조창이다. 별도 timer, polling, worker 호출,
  drive query/write/job을 만들지 않고 앱 core가 이미 admission한 현재 telemetry만 표시한다. 고정
  allowlist는 `PX`(cnt), `VX`(cnt/s), `PE`(cnt), `IQ`(A), `MO`(state)이며 dialog를 닫거나
  숨겨도 core polling의 ownership이나 주기는 바뀌지 않는다.
- line 추가/삭제/위·아래 이동/기본값 복원은 현재 process session 안에서만 동작한다. 로컬 상한
  16 lines는 이 앱의 방어 한계일 뿐 EAS 최대 line 수에 대한 근거가 아니며, 파일·registry·EAS
  설정으로 저장하거나 다음 실행에 복원하지 않는다.
- 값이 `CURRENT`가 되려면 활성 positive generation, canonical hashed SN[4] identity, strictly
  increasing positive sequence, core의 명시적 fresh admission, 다섯 신호 전체의 complete finite 값과
  `MO∈{0,1}`이 모두 맞아야 한다. stale/replay, generation·identity mismatch, incomplete/non-finite sample,
  configuration 변경 또는 observer 오류가 하나라도 있으면 일부 row를 남기지 않고 모든 값을
  즉시 blank로 폐기한다. 정확한 identity나 digest prefix는 snapshot/UI에 노출하지 않고 고정 `Drive01`
  alias만 사용한다.
- 설치 NetHelp가 설명하는 EAS 전체 범위인 visible-only 0.5 s sampling, arbitrary variables/arrays,
  multi-target, user units, value-change color, gauge/warning limits, Quick Watch/topmost floating 동작은
  아직 `NEED-DATA`다. native configuration도 미구현이며 도움말 자체가 Save/Replace는 `.smc`,
  Append 설명은 `.sac`와 `.smc`를 함께 적어 형식이 모순되므로 fixture 기반 open-save-open oracle
  전까지 잠근다.
- 공개 근거는 설치된 `Supporting Tools.htm` §12.3
  (SHA-256 `300B980C11BF37A5AE20803AA3038C178A2E6CD0785959791124EFA6739AAEC4`),
  `Floating Tools.htm` §11.5
  (SHA-256 `32936D4B12A469CC950B592268D4E56A0E7BD12465C1CFA6AC88549D0B2E7E85`)와
  `Default.mcwebhelp`
  (SHA-256 `51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF`)다.
  이는 static public help 근거이며 실제 EAS Status Monitor 화면, native file round-trip, hardware 또는
  display parity를 검증했다는 뜻은 아니다.

### 과거 실기 관찰 이력 — 최신 working tree 검증과 분리
- **연결·텔레메트리·Motor/Feedback 읽기**: 실드라이브 대조 GREEN. 과거 직접 쓰기 이력은
  현재 durable 저장 transaction의 검증을 대신하지 않는다.
- **Encoder Maintenance 영점**(실기 확정): `TW[18]=0`(단일회전) + `TW[19]=1`(다회전, 소켓인자!
  `TW[19]=0`은 드라이브가 Drive error 21로 거부) → PX=0, **전원 off/on 후에도 유지(datum 영구,
  SV 불필요)**. 대조로 Soft Zero(PX=0)는 전원 후 절대위치로 복귀(휘발성).

### Motor Settings durable 저장

- Motor profile 저장은 안전 사전검증 → checkout 밖 durable write-ahead record → RAM 적용·전체
  되읽기 → 실패 시 원값 rollback·되읽기 → 단일 승인 `SV` 순서다. 동일 요청의 중복 클릭과
  반복 `SV`는 차단한다.
- WAL 직후와 각 RAM 쓰기·복원 직전에 `MO=SO=VX=MF=0`, `PS=-2/-1`을 재확인하며,
  공식 범위 `VH[2]≤2^31-1`, `CL[1]<MC`, `PL[1]≤MC`를 적용한다. Motor 변경이나 재연결은
  이전 P1/P2 결과의 Apply 권한을 폐기한다.
- 전체 적용값을 `PERSISTING`으로 fsync한 뒤에도 profile과 안전 상태를 다시 읽고, `SV` 바로 전
  마지막 안전 조회가 실패하면 `SV` 없이 UNKNOWN으로 잠근다.
- 연결/Motor 변경 세대에 P1/P2 결과·RAM trial·검증 토큰을 결속하고, 이전 worker의 지연 신호는
  버린다. Motor 저장과 튜닝/검증 dispatch는 UI에서 동시에 queue에 들어갈 수 없다.
- `SV` 응답 유실, session 변경, rollback 불완전 또는 원장 closeout 실패는 성공으로 추측하지
  않고 `UNKNOWN`으로 잠근다. 전원 재인가 뒤 같은 identity/profile을 query-only로 감사하기
  전에는 새 설정 쓰기, enable, motion을 허용하지 않는다.
- 현재 근거 수준은 OFFLINE fault injection이다. 실제 드라이브의 최신 Motor transaction과
  응답 유실 후 냉간 재인가 audit은 감독 실기 전이다. 다른 EAS/CAN/EtherCAT master의 동시 enable을
  소프트웨어 조회만으로 원자적으로 막을 수 없으므로 실기 중 배타적 제어권도 별도 현장 게이트다.
- Feedback direct save는 별도 versioned write registry가 센서/펌웨어별 명령·타입·범위,
  `CA[41]` 부작용, 복원 순서와 reset audit을 고정할 때까지 UI와 dispatch 양쪽에서 잠근다.
  `TW[18..20]` Encoder Maintenance는 이 profile/SV 흐름에 포함하지 않는다.

### 과거 실기 이력 — 자체 전류루프 오토튠 (Phase 1) R/L 측정
EAS의 게인 알고리즘은 재현 불가지만, **드라이브 명령으로 R·L을 실측 + 표준 PI 설계**로 게인 산출.
매 실기 런이 실물 특유의 문제를 하나씩 벗겨내며 완성:

1. 여진 주파수 한계(TS=100µs→f_max 1250Hz) → 주파수 자동산출.
2. 레코더 신호목록 → **.NET personality 업로드 흐름**(UploadPersonality + 5이벤트 콜백 + Start +
   FINISHED 폴 → CreatePersonalityModel → 254 신호).
3. 레코딩 업로드 → **.NET Drive Recording API**(RecordingData.Data 키는 **위치 0..N-1**, SignalIndex 아님).
4. **전압 단위**(가장 어려웠던 부분): "A/B/C/D Voltage"는 볼트가 아니라 **레그 PWM 듀티 카운트**(mid=3750=0V).
   보정 = 중성점차감 `v_A−mean(A,B,C)` + Vbus/7500 스케일 + **복소-Z 스큐 회전보정**(기록전압이 전류보다
   1.5·TS 앞섬). 드라이브 게인계 = **ph-ph**(KP=ω_c·L_pp, EAS 대비 −0.018%). KI = 2·α·ω_c/2π(EAS 매칭).

**실기 측정 결과(8회차, 감독 하)**: R_pp≈0.14–0.15Ω(터미널, 모터 0.119 + 케이블·FET 기생),
**L_pp=41.34µH(4주파수 산포 1%)**, KI=812.87(EAS 812.94와 −0.0087%), PM≈59°. 게이트 G2/G3/G4 통과.

- P1 식별 중 바뀌는 **임시 구성**은 첫 assignment 전에 durable `P1_CONFIG` WAL로 기록하고,
  종료 시 전체 원값 복원·되읽기 뒤에만 원장을 닫는다. 이 WAL은 gain trial WAL이 아니다.
- 현재 gain용 pre-assignment WAL은 P2 검증의 별도 `P2_LIMITS` WAL과 안전하게 공존하지 못한다.
  따라서 hardware-capable link의 `Apply P1 → RAM`과 legacy `apply_gains()`는 snapshot/query/write
  전 domain에서 거부되며 UI도 `LOCKED`로 표시한다. RAM trial begin/restore 회귀는 명시적인
  `SYNTHETIC_NO_HARDWARE` 링크에서만 실행된다.
- on-motor P1 verifier도 RED stub이므로 `Save P1 → SV`는 UI/worker/domain/transport에서 계속
  잠겨 있다. Production P1은 현재 **후보 산출만 가능**하다.

### 과거 실기 이력 — 자체 속도/위치 오토튠 (Phase 2) + 검증런 (2026-07-15)

**과거 실기에서는 측정 → 게인 산출 → 적용 → 검증을 수행했다. 현재 production revision은
측정·게인 후보 산출과 installed-gain Verify까지만 열고 새 gain Apply/Save는 잠근다.**

- P2 RAM trial/검증/복원/SV state machine과 fault-injection 회귀는 남아 있지만, 새 gain assignment
  전에 살아남는 durable trial record가 없다. 그래서 hardware-capable link의 `Apply P2 → RAM`은
  첫 drive command 전에 거부되고 `Save P2 → SV`도 UI에서 잠긴다. 명시적 synthetic link만
  RAM trial 회귀를 실행할 수 있다.
- `Verify Installed P2 on Motor`는 현재 설치된 게인을 대상으로 하며 connection-bound commutation
  signature와 `P2_LIMITS` WAL을 계속 요구한다. 이 검증은 새 gain Apply/Save 권한을 만들지 않는다.
- 미저장 P1/P2 시험 중에는 다른 튜닝·좌표·설정 쓰기, 연결 해제와 앱 종료를 차단한다.
  예기치 않은 연결 끊김은 전원 OFF를 증명하지 못하므로 해당 스냅숏을 유지하고 재연결 후
  해시된 동일 drive identity·새 connection token·MO=0·전체 게인 되읽기가 일치할 때만
  `Restore P1/P2 → Original` 전용으로 다시 채택한다. 이전 검증/Save 권한은 재사용하지 않는다.
- `SV` 응답 유실은 저장 성공/실패를 추측하지 않고 `UNKNOWN`으로 잠근다. 같은 링크에서는 새
  설정 쓰기, enable/motion, 반복 `SV`가 차단된다. 기존 P2 persistence engine은 SV 직전,
  P1 임시 구성과 Motor는 첫 RAM assignment 전에 identity·VR/VP/VB·connection epoch와 profile을
  interprocess-serialized durable ledger에 기록하므로 강제 앱 종료 뒤에도
  잠금이 유지된다. 다만 production gain trial begin 자체가 잠겨 있으므로 최신 UI에서 새 P2 gain
  record를 만들 수는 없다. 해제는 현장 냉간 OFF→ON 확인 + 새 세션의 동일 target + 2회 query-only
  readback으로 해당 record profile이 확인된 때만 가능하다. 이 결과는 특정 SV의 인과나
  커뮤테이션/motion safety를 증명하지 않는다. 안전 원장은 checkout 밖
  `%LOCALAPPDATA%\AngryYJHControl\safety`에 있고, 해제 근거 snapshot도 해시와 함께 archive한다.
  이 원장을 모르는 구버전 앱은 UNKNOWN 중 제어용으로 사용하지 않는다.

- **플랜트 실측**: K_a = **2.76e6 cnt/s²/A** — 독립 **5회 재현**(2.7733/2.7537/2.7607/2.7545/2.7642e6,
  편차 0.7% 이내). I_c ≈ 0.45–0.48 A, i_ba ≈ 0.9–1.1 A.
- **검증런(F2/G5) GREEN** — 우리 게인(KP[2]=0.000166 / KI[2]=10.7 Hz / KP[3]=85.2114):
  300rpm OS **0.8%**·정착 292ms·I_ss 0.475A / 900rpm OS **0.3%**·정착 888ms·I_ss 0.518A.
- **EAS 게인 대조**(0.000155/22.1/181): 300rpm 0.8%·296ms·0.482A / 900rpm 0.3%·886ms·0.519A —
  **구분 불가한 동등 성능**. 단 이 시험은 **프로파일러 지배 구간**(정착의 실체 = AC 램프
  328ms/983ms)이라 두 세트 모두 "램프 완벽 추종"만 증명한다. 설계 차이는 외란 억제·더 빠른
  지령에서 드러날 것 → 결론은 "우리가 낫다"가 아니라 **"상용 EAS와 같은 설계점에 도달"**.
- **서명 전용 경로(2026-07-15 추가)**: `Run Commutation Signature (≤1.30 A)`는 +TC를
  0→1.30A로 최대 2초만 램프하고, i_ba 0.50..1.30A·정방향만 GREEN으로 판정한다. UNIT-DIAG,
  UM=3, 식별 펄스, JV에는 진입하지 않으며 모든 종료에서 TC=0·MO=0·임시 제한 복귀를 되읽어
  확인한다. 미검출·역방향 RED도 `final_state`에 되읽기 결과를 남기며, 종료 증거가 불완전하면
  원래 RED 사유에 종료 확인 실패를 함께 표시한다. 게인 Apply/SV와도 분리되어 있다.
  **실기 GREEN: i_ba=0.679 A, 방향 +1,
  종료 MO=0·TC=0**.
- **안전 장치**: K_a 열화 조기검출(직전 GREEN의 0.5× 미만 → RED), installed-gain Verify의
  `P2_LIMITS` 사전 WAL·전체 복원 되읽기, UM3 드래그 판별(기계 vs 커뮤 구분). Legacy/synthetic
  gain state machine도 적용·복원·SV 직전 전체 되읽기를 검사하지만 production Apply/Save 권한은 없다.

## 남은 것 (다음에 이어서)

아래는 기존 기술 backlog다. **현재 실행 우선순위와 완료 gate는
[`docs/current-scope-handoff.md`](docs/current-scope-handoff.md)가 우선한다.**

- **EAS 설정 provenance 복구**: GUI에서 Motor Direction=Non-Invert와 커뮤테이션 GREEN을 확인했지만,
  EAS가 취소 전에 Velocity/Position Identification·Design까지 자동 진행했다. Summary의 SV는 실행하지
  않았고 주 게인은 RAM에 원값을 다시 적용했으나, 필터 등 전체 변경 집합의 사전 스냅숏이 없어 현재
  설정 복구 판정은 YELLOW다. 전체 관련 명령을 독립 되읽기하기 전에는 Phase 2 폐루프 실기를 재개하지 않는다.
- **앱 자체 커뮤테이션 식별** (마지막 EAS 의존, 필요성 확정): EAS 위저드가 이 감속기에서
  **"Positive and Negative Movements are Uneven"으로 실패**한다 — ±대칭 이동 전제가 백래시·정지마찰로
  깨지기 때문. 우리 HOLD-CONFIRM(유격 통과 vs 진짜 회전 구분) 로직으로 **백래시 내성 커뮤 ID** 설계 가능.
  → btw-001/007/012.
- **스펙 문서**: `docs/autotune-velpos-spec.md` §6에 적응 캡처창·정착 의미(프로파일러 램프 포함)·
  커뮤 2층 모델 반영.
- **모션 화면**: 유한 PTP 백엔드와 STOP/Disable transaction은 오프라인 구현됐지만,
  기계 이동범위·정방향·limit 입력·검증된 SD/정지거리·독립 E-stop/STO 시험값이 없어
  live 실행은 `NEED-DATA`로 잠겨 있다. 자유 Jog/Homing/Current/Sine도 계속 잠금.
- **Recorder 고급 기능**: View Design은 완료 capture의 로컬 읽기 전용 듀얼 차트,
  `Apply X-range to both charts` 시간 줌, full-capture one-sided peak FFT, Y축 0 하한,
  축 span이 `0.001` 미만일 때의 지수 표기를 `STAND-IN`으로 구현했다. FFT는 직사각 창,
  detrend/zero padding 없음, DC 포함 계약이며 수동 시간창은 FFT에서 무시하되 보존한다.
  설치 EAS NetHelp가 문서화한 field는 같은 full immutable capture와 exact integer-index A:B
  inclusive range에서 `DERIVED` 읽기 전용 표로 구현했다. A/B endpoint Signal Values, signed
  `ΔX/ΔY=C2-C1`, chart 수직선, `N=B-A+1`, Tolerance %도 포함한다. 단, prose의 Root Mean Square와 literal `sqrt(sum)/N` 수식이 모순되어
  설치 EAS 3.0.0.26 ViewModel/Action DLL IL을 대조했고, 두 경로 모두 N으로 나눈 뒤 `Math.Sqrt`를
  호출해 표준 RMS 의미가 `STATIC-IL VERIFIED`됐다. 로컬은 overflow-safe 안정화 계산이므로 극단값
  bit-identical rounding은 미주장한다. 줌/FFT/lane과 독립이고 통계 overflow가 capture/CSV 권한을
  취소하지 않는다. 범위를 바꾸면 stale 결과를 즉시 지우고, FFT에서는 A/B를 보존하되 편집을 잠근다.
  EAS 일반 Zero Scale의 `Y축을 0에서 시작` 의미는 설치 NetHelp로 확인했다. Time chart의 A/B
  선은 현재 보이는 원본 sample에 mouse drag로 snap하며 동률은 낮은 index를 택하고, release 때
  inclusive 통계를 한 번 계산한다. 결과는 capture binding·exact source SHA-256·범위·CURRENT 또는
  HISTORICAL/OFFLINE authority가 들어간 단일 원자적 local Statistics CSV로 내보낼 수 있다.
  EAS의 정확한 glyph·shortcut·persistency/file parity, FFT-bin range, `.mat`, Rollover,
  Normal/Auto/Interval, Multi-drive와 EAS 원본 레이아웃 파일 호환은 계속 `NEED-DATA`다.
- **Full EAS Fault/Ack/Clear**: drive-origin history/source timestamp, EC/SR/MF taxonomy,
  Ack/Clear/Reset 권한·side effect·실패 복구 계약이 없어 host-observed v0.1과 분리해 잠근다.

### 운영 규칙 (이 유닛 필수 — 매 전원 투입마다)

**유효 전기각 δ는 전원 세션 스코프의 RAM 상태다.** 저장된 CA[7]이 비트단위 동일해도 전원 사이클
하나로 δ가 0°→103°로 튄다(실측). CA[7]은 위저드 실행 기록일 뿐 커뮤 결정자가 아니다.

1. 전원 투입 → 앱의 **Run Commutation Signature (≤1.30 A)** 실행(Phase 2 버튼 아님).
2. 서명 확인: **i_ba = 0.9 ± 0.4 A AND +TC→+dpx**, 종료 `TC=0·MO=0` 확인. RED면
   EAS 위저드 → 다시 1.
   - 위저드 전 **출력축을 손으로 흔들어 정지마찰을 깨고 완전 정지 대기**(EAS 자체 Resolution:
     "wait for the motor to stabilize") — 이 요령으로 성공률이 크게 오른다.
3. **서명 GREEN 전에는 폐루프(JV/조그/위치이동) 절대 금지** — cos δ<0이면 어떤 게인이든 양의 피드백.
4. **위저드 세션에서 터미널로 CA를 만지지 말 것** — 커뮤 리셋 → MF 폴트 → 에러 58(SO must be on).

## 파일 지도

- `main.py` — PyQt6 GUI(DriveWorker 스레드 + 8-page workspace + 스모크).
- `elmo_link.py` — pythonnet 전송층(2글자 명령 + .NET personality/recording 래퍼, 모션 게이트).
- `autotune_current.py` — 전류루프 오토튠(측정·복소Z·스케일·게이트·게인식).
- `expert_tuning_offline.py` — no-I/O immutable Expert P1/P2 MODEL과 P1 Bode dataset.
- `expert_page_status.py` — no-I/O Expert P1/P2/evidence local status projection.
- `feedback_spec.py` — 23센서 EAS 패널 스펙.
- `recorder_view.py` — 차트·요약·CSV가 공유하는 불변 capture evidence, 2-lane layout v3,
  full-capture FFT, full+A:B Signal Statistics/endpoint values와 축 표기 모델, 보조 SCREENING 감축 모델.
- `session_log.py` — bounded host-observed event model, generation/scopes, 비식별화 atomic JSON/CSV.
- `status_monitor.py` — session-only fixed-signal projection, generation/identity/sequence/freshness gate,
  full-blank fail-closed snapshot.
- `system_configuration.py` — admission 완료 target만 받는 zero-new-I/O 단일 target projection.
- `tool_organizer.py` — Qt/drive/persistence 없는 8-page 세션 layout model.
- `theme_qdd.py` / `theme.py` / `theme_angrybirds.py` — 스킨.
- `docs/recording-api.md` — .NET Drive Recording API 그라운딩(리플렉션 확정).
- `docs/eas-feature-matrix.md` — EAS 기능별 LIVE/OFFLINE/MODEL/지원 제외 범위와 자동 설정 계약.
- `docs/expert-tuning-offline-v2.md` — Expert v2 입력 basis, 수치 모델, 검증과 NEED-DATA 경계.
- `docs/expert-page-status-v0.1.md` — Expert local page 상태, 권한, EAS 비동등성 계약.
- `docs/persistence-audit.md` — active P1_CONFIG/P2_LIMITS/Motor 원장과 legacy P2 record의
  전원 재인가 후 query-only 판정 계약.
- `.omc/paf5-brief.md` — 상세 연속성 로그(모든 결정·수치·실기 발견).
- `vendor/elmo-downloads/` — 정품 .NET 라이브러리·펌웨어·문서(사용자 다운로드).

## 안전

Motor 설정 저장의 계약은 MO=0 게이트 + 변경 전 원본 + 첫 assignment 전 durable WAL + RAM
되읽기/복원 + 검증된 단일 SV다. P1/P2 gain은 crash-safe pre-assignment trial WAL이 없으므로
production Apply/Save를 drive I/O 전에 잠근다. P1은 real session-bound on-motor verifier도 아직
없다. Feedback direct save도 versioned registry 전까지 잠겨 있다. Abort는 disable·복원을
시도하지만 즉시 기계 정지나 완전한 원상복원을 증명하지 않는다.
**무인 통전 금지.**

[Fable5-SDD-Control-Program]: https://github.com/duwogus7650-ctrl/Fable5-SDD-Control-Program
