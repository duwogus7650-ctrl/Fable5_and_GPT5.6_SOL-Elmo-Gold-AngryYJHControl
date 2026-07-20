<!-- scope_progress: 100 -->
<!-- offline_progress: 100 -->
<!-- field_progress: 57 -->
<!-- progress_basis: Planning indicators, not safety scores. Scope means the implemented feature inventory is enumerated. Offline means code/tests/documents reviewed. Field now includes bounded live EAS/read-only comparisons, zero-torque SUPERVISED admission, and one fail-closed standalone signature attempt; it excludes a passing signature, Phase 1/2, motion verification, protection efficacy, persistent writes, and Gold-family compatibility. -->

# EAS LIVE PARITY AUDIT · PX/PU + CURRENT LIVE RECHECK · SR23 FIX

상태: **서명 RED · MF=0x80 speed-tracking fault · MO=0/TC=0 복귀 · 재시도 금지**

업데이트: **2026-07-19 KST**

## 완료 조건 · 사용자 지시 반영

- 이번 범위는 **비실기 잔여 작업 0개**가 될 때까지 자동 진행한다.
- 사용자에게 중간 단계 승인을 다시 묻지 않는다.
- 완료한 자동 순서:
  `전체 회귀 → EAS 화면·설치 도움말·기능 의미 대조 →
  문서/모니터 실측값 확정 → 최신 오프라인 UI 확인 →
  변경 범위·secret 검증 → commit → private Draft PR push/update`.
- EAS 대조는 모양뿐 아니라 control 의미, target command/register,
  enable 조건, 실행/잠금 경계까지 항목별로 기록한다.
- 추가 실기 연결/조회, 모터 enable, 통전, motion, tuning, write,
  Apply/SV는 실행하지 않는다.
- 마지막에 남을 수 있는 항목은 장비 구동·현장 측정으로만 닫히는
  `FIELD NEED-DATA`뿐이다.

## 예상 잔여시간 · 2026-07-19 23:05 KST

| 단계 | 현재 상태 | 예상 잔여 |
|---|---|---:|
| 전체 repository 회귀 | **완료 · 1964 passed / exit 0** | 0분 |
| EAS 화면/설치 도움말/기능 의미 최종 대조 | **완료** | 0분 |
| 문서·handoff·모니터 실측값 확정 | **완료** | 0분 |
| 최신 오프라인 UI/정적 검증 | **완료** | 0분 |
| diff/secret/범위 검증 + commit + private PR push/update | **완료 · PRIVATE** | 0분 |
| **비실기 전체** | **완료** | **0분** |

전체 회귀 실제값은 `1964 passed in 636.67 s`, exit 0이다.
표의 0분은 현재 승인된 감사·수정·게시 범위의 비실기 잔여를 뜻한다.
아래 `FIELD NEED-DATA`를 닫는 현장 시간은 포함하지 않는다.

## 감사 범위

- Quick Tuning: Axis Configuration, Motor, Feedback, 6단계 Automatic Tuning.
- Expert Tuning: User Units, Limits/Protections, Application Settings,
  Current, Commutation, Velocity/Position, Scheduling, Verification, Summary.
- Single Axis: 상태, Position/Velocity/Current/Sine/Homing, Digital I/O,
  Drive Mode, Terminal, Recorder docking.
- Recorder: ribbon, acquisition modes, signal/trigger, chart/view/export 범위.
- 공통 셸: 메뉴, System Configuration, Status/Monitor, persistence/authority 표시.

## 이번 live EAS 관찰

- EAS 3.0.0.26을 현재 Gold Twitter에 COM3 단독 연결해 Motor Disabled,
  Velocity 0, Active Current 0 상태에서 읽기/화면 관찰만 수행.
- Enable, Run Tuning, Verify, PTP/Jog/Current/Sine/Homing, Apply, Save/SV는 실행하지 않음.
- EAS 터미널 raw `PX=-2038379934`, `PU=-2004825502`; EAS Single
  Axis/Verification-Time 표시는 정확히 `PU`.
- `PU-PX=33554432=2^25`, XM=0, FC=1, CA[45]=1. firmware-internal
  좌표 원점은 아직 미확정이며 앱은 자동 보정하지 않음.
- EAS Current는 `Current Command 1..5`, 모두 같은 `[TC]`, 초기 0 A,
  motor-off에서 Set disabled.
- 최종 offline 기능 대조에서 EAS는 disconnected 상태에도 이전/project
  Position·Current·terminal 값을 유지했다. 최신 AngryYJH는 `OFFLINE`,
  `MOTOR STATE UNKNOWN`, `UNKNOWN-ENABLE LOCKED`로 live authority를 지우고
  bounded refresh와 5개 `Set TC`를 모두 잠갔다.
- retained EAS 값은 fresh live evidence가 아니다. 값/shape parity와 freshness
  authority를 분리한 AngryYJH 동작은 의도한 fail-closed 차이다.

## 현재 판정

- `VALUE_PARITY_OBSERVED`: raw PX, EAS display PU, UM=5, 속도/가감속/정지감속,
  Digital Input/Output 논리 상태, Current PI와 Velocity/Position 설계 게인.
- `PARTIAL_LIVE_OBSERVED / OUTPUT LOCKED`: Current readback과 별도로 EAS형
  5개 local draft 구현; 모든 Set TC는 항상 잠김.
- `NEED-DATA`: `PU-PX=2^25`의 firmware-internal 좌표 원점.
- `DOC_ONLY`: User Units, Limits/Protections, Application Settings,
  hidden Bode, Verification-Time, Summary의 기존 로컬 inspector 대부분.
  현재 비실기 구현/문서화 상태이며 live EAS 동등성으로 승격하려면 현장 실행이 필요함.
- `NOT_EXECUTED_NEED_DATA`: 실제 Automatic/Expert tuning, Commutation,
  Verification, Recorder acquisition, motion, Apply/SV.

## AngryYJH same-session 재조회

- `UM=5 Position`.
- `PX=-2038379934`, `VX=0`.
- `PU=-2004825502`, `PU-PX=+33554432=2^25`.
- `SP=4444444`, `AC=DC=SD=1000000`.
- `CL[1]=21.2132`, `PL[1]=70.7107`, `MC=140`, `TC=IQ=ID=0`.
- 28-query Position/Velocity acquisition: `59.1 ms`, CURRENT.
- 16-query Current acquisition: `37.4 ms`, CURRENT.
- 5개 Current draft: 모두 0 A / observed limit 내 / Set TC 5개 모두 disabled.
- Digital Inputs 1..6: active/GP; Digital Outputs 1..4: inactive/GP.
- installed gains: `KP1=0.0857`, `KI1=782.5188`, `KP2=0.0002`,
  `KI2=10.7000`, `KP3=85.2114`.
- 수정 제어창은 raw `PX`, EAS `PU`, delta/socket/modulo/scale을 분리하고
  상단 위치를 `RAW POSITION · PX`로 명시함.

## SR live diagnostic

- 첫 28-query 시도는 `SR safety/motion state changed`로 fail closed.
  당시 UI는 raw pre/post를 보존하지 않아 정확한 변경 bit는 `UNVERIFIED`.
- 진단은 이제 `SR_PRE`, `SR_POST`, changed bit 번호와
  bit 23 movement/standstill / bit 27 STO diagnostics 의미를 표시.
- admitted Axis Summary에서 `SR=0x0080C000`의 bit 23이 실제 관찰됐고,
  기존 status decoder가 이를 reserved로 오판한 결함을 재현.
- 설치 EAS SR 도움말에 따라 bits 21/22/23/27/30을 정의 목록에 추가.
- `MO↔SR22` 불일치는 authority를 취소하며, `SR27=1`은
  `FAULT REPORTED - NO AUTO-RETRY`로 Enable을 계속 차단.
- bit 23은 firmware/source 차이를 고려해 물리 motion 판정이 아닌
  `source-bound movement/standstill indication`으로만 표시.
- 상세 증거:
  [`docs/single-axis-sr-live-diagnostic-2026-07-19.md`](../docs/single-axis-sr-live-diagnostic-2026-07-19.md).

## 현재 코드 검증

- TDD RED: SR change 상세가 없고 live bit 23이 reserved로 거부되며
  SR27이 Enable fault로 승격되지 않는 것을 재현.
- SR/PX-PU/Current + 안전/카탈로그 직접 영향: **504 passed**.
- Single Axis Qt 통합 전체: **56 passed in 118.13s**.
- 전체 repository 회귀: **1964 passed in 636.67s, exit 0**.
- 최신 focused 재실행: **197 passed in 0.67s**.
- live SR23 Qt 핵심 경로 재실행: **1 passed in 1.06s**.
- 전체 출력에 skip/xfail 요약 없음.

## 남은 FIELD NEED-DATA · 비실기 작업 없음

1. `PU-PX=2^25`의 firmware-internal 좌표 원점은 vendor-authoritative 정의나
   통제된 현장 readback으로만 승격한다.
2. 실제 Automatic/Expert tuning, Commutation, Verification, Recorder acquisition,
   motion, Apply/SV는 현장 안전 조건과 실행 승인이 있어야 한다.
3. Current 출력은 현장 current/thermal/torque envelope와 독립 stop evidence가
   생길 때까지 계속 잠근다.
4. 다른 Gold 제품 호환성은 대상별 identity, I/O, firmware, feedback,
   protection과 구동 시험 없이는 주장하지 않는다.

## 2026-07-19 supervised field session

- current revision `f03453a`에서 AngryYJH `ONLINE · READ ONLY` admission 통과.
- `MOTOR DISABLED`, PX=`-2038379934`, VX=0, position error=0,
  active current=0 A.
- Position/Velocity `54.6 ms`, Drive Mode `2.0 ms`, Current readback,
  Digital Inputs `27.7 ms`, Digital Outputs `20.4 ms`로 bounded read 통과.
- EAS III를 단독 연결해 GCON Revision E / Twitter FW / PAL / serial,
  UM=5, I/O, STO indicators, PX/profile, five Current presets를 재대조.
- EAS Quick Tuning의 Axis/Motor/Feedback page를 실제 target에서 읽었으며
  Run/Apply/Enable/Set/Save/motion은 실행하지 않음.
- 최종 상태: AngryYJH와 EAS 모두 정상 연결 해제.
- 다음 단계는 `SUPERVISED` 연결 전 현장 3조건:
  operator·area·restraint, 이번 런의 independent E-stop/STO test,
  direction·allowed travel envelope의 물리 확인.
- 상세:
  [`docs/field-validation-session-2026-07-19.md`](../docs/field-validation-session-2026-07-19.md).

## 2026-07-19 supervised admission

- 작업자가 이번 런의 현장 대기, 축 주변 정리/구속, 독립 E-stop/STO,
  방향/허용 이동 조건 확인을 보고함.
- AngryYJH를 `ONLINE · SUPERVISED`로 연결했으며 연결 자체는 모터를
  활성화하거나 명령을 쓰지 않음.
- fresh readback: `MO=0`, `SO=0`, `MF=0`, amplifier `0x0`, `SR4=0`,
  `SR14=1`, `SR15=1`, `PS=2`, `SR12=0`, `SR13=0`, `MS=3`.
- 새 연결 세션이므로 이전 commutation authority는 정상 폐기되었고
  `Commutation Signature required this connection`으로 표시됨.
- 첫 통전 후보는 별도 signature 경로의 `+TC 0→최대 1.30 A`,
  최대 2.0초, Phase 2 미진입, 종료 `TC=0/MO=0` 및 임시 리밋 복원 확인.
- 작업자가 DC-link `48 V`, 외부 전원 current limit `5 A`를 기록하고
  `+TC 0→최대 1.30 A`, 최대 2.0초 standalone signature 실행을 승인함.
- 이 승인은 Phase 1/2, PTP/Jog/Homing/Sine, Apply/Save/SV, 증액·연장,
  자동 재시도를 포함하지 않음.

## 2026-07-19 commutation signature field result

- `23:33 KST` standalone signature를 승인 범위 안에서 1회 시작.
- 결과 `RED`: `i_ba` 미검출, 방향 미확정, `MF=0x80`.
- Gold command reference상 `MF=0x80`은 `|DV[2]-VX| > ER[2]`인
  speed-tracking error.
- raw artifact에는 `breakaway`/`signature_gate`가 없고
  `abort.segment=idle`; enable 직후, 측정 램프 진입 전 fault와 일치한다.
- 임시 `SD/HL[2]/LL[2]/ER[2]`는 forward/reverse readback으로 원복:
  `1e6/0/0/1e8`.
- result closeout: `configuration_state=RESTORED`,
  `final_state.pass=true`, `MO=0`, `TC=0`,
  `disabled_verified=true`.
- 별도 UI 확인: `MOTOR DISABLED`, `MO=0`, `SO=0`, `MF=128`,
  `VX=0`, active current=0 A, PX=`-2038379934`로 시작값과 동일.
- 사용자가 Escape로 제어를 중단했으므로 automation은 즉시 종료했고
  정상 UI disconnect는 수행하지 않음. 마지막 관찰은
  `ONLINE · SUPERVISED`지만 무토크/정지 상태.
- raw evidence와 SHA-256:
  [`docs/evidence/field-2026-07-19/README.md`](../docs/evidence/field-2026-07-19/README.md).
- **재시도·fault clear·MO=1 금지**. 다음 실기 전 `DV[2]`, `VE`,
  enable-time `ER[2]` transaction을 진단해야 함.

## 계속 잠긴 기능

- 모든 motor energization/motion: `MO=1`, `BG`, PTP/Jog/Current/Sine/Homing.
- 실제 Quick/Expert tuning과 Commutation/Verification.
- 파라미터 assignment, Apply/Revert, Save/SV, firmware download.
- unrestricted Terminal 및 Digital Output actuation.

이 감사의 live 관찰은 기능 동등성·제어 성능·기계 안전·STO/E-stop·다른 Gold 제품
호환성을 증명하지 않는다.
